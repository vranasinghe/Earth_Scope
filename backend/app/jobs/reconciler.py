"""Reconciler: makes the system converge after crashes, outages and restarts.

Run as its own process (Docker service ``scheduler``)::

    python -m app.jobs.reconciler

Every cycle (default 20 s):

1. **Outbox** — PENDING jobs whose RQ message was never sent (Redis down at
   submission) are enqueued.
2. **Due retries** — RETRYING jobs whose back-off has elapsed are enqueued.
3. **Lost messages** — QUEUED jobs whose RQ entry disappeared (Redis restart
   without persistence, manual flush) are enqueued again.
4. **Orphaned jobs** — RUNNING jobs whose lease expired (worker crashed, was
   killed or lost the database) go back to RETRYING and resume from their
   checkpoints; after ``job_max_attempts`` they FAIL with WORKER_LOST.
   CANCEL_REQUESTED jobs with an expired lease become CANCELLED.
5. **Expiry** — results / checkpoints past their retention are deleted and the
   job becomes EXPIRED; unreferenced shared NASA tiles are garbage-collected.

All transitions are compare-and-set updates, so several reconcilers (or a
reconciler racing a worker) cannot corrupt a job.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import timedelta
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.jobs import queue as jq
from app.jobs.artifacts import ArtifactStore, get_store
from app.jobs.db import ensure_schema, get_sessionmaker
from app.jobs.models import AnalysisJob, JobEvent, JobStatus, JobTile, utcnow
from app.jobs.service import hand_to_queue

logger = logging.getLogger("earthscope.reconciler")
ALIVE_RQ_STATES = {"queued", "started", "deferred", "scheduled"}


def _event(s: Session, job_id: str, level: str, message: str) -> None:
    s.add(JobEvent(job_id=job_id, at=utcnow(), level=level, stage=None, message=message, data=None))


def reconcile_once(sm: sessionmaker[Session], settings: Settings, store: ArtifactStore,
                   rq_state: Callable[[str | None], str | None] = jq.rq_job_state, gc_tiles: bool = False) -> dict[str, int]:
    now = utcnow()
    out = {"enqueued_pending": 0, "enqueued_retry": 0, "requeued_lost": 0, "recovered_orphans": 0,
           "failed_orphans": 0, "cancelled_orphans": 0, "expired": 0, "tile_blobs_removed": 0}
    with sm() as s:
        # 1. outbox
        for job in s.scalars(select(AnalysisJob).where(
                AnalysisJob.status == JobStatus.PENDING,
                AnalysisJob.updated_at < now - timedelta(seconds=settings.job_pending_requeue_seconds))).all():
            if hand_to_queue(s, job, (JobStatus.PENDING,)):
                out["enqueued_pending"] += 1
        # 2. due automatic retries
        for job in s.scalars(select(AnalysisJob).where(
                AnalysisJob.status == JobStatus.RETRYING,
                (AnalysisJob.next_attempt_at.is_(None)) | (AnalysisJob.next_attempt_at <= now))).all():
            if hand_to_queue(s, job, (JobStatus.RETRYING,)):
                out["enqueued_retry"] += 1
        # 3. lost queue messages
        for job in s.scalars(select(AnalysisJob).where(
                AnalysisJob.status == JobStatus.QUEUED,
                AnalysisJob.queued_at < now - timedelta(seconds=settings.job_queued_recheck_seconds))).all():
            if rq_state(job.rq_job_id) not in ALIVE_RQ_STATES:
                _event(s, job.id, "warn", "The queue message for this job was lost (queue restart); it was queued again.")
                s.commit()
                if hand_to_queue(s, job, (JobStatus.QUEUED,)):
                    out["requeued_lost"] += 1
        # 4. orphaned jobs (expired lease)
        stale = s.scalars(select(AnalysisJob).where(
            AnalysisJob.status.in_((JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)),
            AnalysisJob.lease_expires_at < now)).all()
        for job in stale:
            cond = (AnalysisJob.id == job.id, AnalysisJob.status == job.status, AnalysisJob.lease_expires_at < now)
            if job.status == JobStatus.CANCEL_REQUESTED:
                res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(*cond).values(
                    status=JobStatus.CANCELLED, lease_owner=None, lease_expires_at=None, active_dedupe_key=None, updated_at=now,
                    activity="Cancelled (the worker stopped before confirming)", expires_at=now + timedelta(days=settings.job_failed_retention_days)))
                if res.rowcount:
                    _event(s, job.id, "info", "Cancellation completed by the reconciler (the worker was no longer running).")
                    out["cancelled_orphans"] += 1
            elif job.auto_attempts < settings.job_max_attempts:
                res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(*cond).values(
                    status=JobStatus.RETRYING, lease_owner=None, lease_expires_at=None, next_attempt_at=now, updated_at=now,
                    activity="The worker stopped responding; resuming from the last verified checkpoint"))
                if res.rowcount:
                    _event(s, job.id, "warn", "The worker stopped sending heartbeats (crash, restart or lost connection). "
                                              "The job resumes from its last verified checkpoint.")
                    out["recovered_orphans"] += 1
            else:
                res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(*cond).values(
                    status=JobStatus.FAILED, lease_owner=None, lease_expires_at=None, active_dedupe_key=None, updated_at=now,
                    error_code="WORKER_LOST", error_retryable=True,
                    error_message=f"The worker stopped responding {job.auto_attempts} times; verified checkpoints are kept for Retry.",
                    activity="Failed", expires_at=now + timedelta(days=settings.job_failed_retention_days)))
                if res.rowcount:
                    _event(s, job.id, "error", "The job failed after repeated worker losses.")
                    out["failed_orphans"] += 1
            s.commit()
        # 5. expiry
        for job in s.scalars(select(AnalysisJob).where(
                AnalysisJob.status.in_((JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)),
                AnalysisJob.expires_at.is_not(None), AnalysisJob.expires_at < now)).all():
            res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == job.id, AnalysisJob.status == job.status).values(
                status=JobStatus.EXPIRED, updated_at=now, activity="Results and checkpoints deleted after the retention period",
                active_dedupe_key=None))
            if res.rowcount:
                s.commit()
                store.remove_tree(store.job_prefix(job.id))   # input, work and result; shared tiles are GC'd separately
                out["expired"] += 1
        s.commit()
        if gc_tiles:
            keep = set(s.scalars(select(JobTile.blob_sha256).join(AnalysisJob, AnalysisJob.id == JobTile.job_id)
                                 .where(AnalysisJob.status != JobStatus.EXPIRED, JobTile.blob_sha256.is_not(None))).all())
            out["tile_blobs_removed"] = store.gc_tile_blobs(settings.job_tile_cache_retention_days * 86400, keep)
    if any(out.values()):
        logger.info("reconcile %s", out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Earth Scope job reconciler")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    ensure_schema()
    sm, store = get_sessionmaker(), get_store()
    cycle = 0
    while True:
        try:
            reconcile_once(sm, settings, store, gc_tiles=(cycle % 180 == 0))
        except Exception as exc:  # noqa: BLE001 - DB / Redis outage: try again next cycle
            logger.warning("reconcile cycle failed: %s: %s", type(exc).__name__, exc)
        if args.once:
            return
        cycle += 1
        time.sleep(settings.job_reconcile_interval_seconds)


if __name__ == "__main__":
    main()
