"""Job submission, idempotency, ownership checks, budgets, cancellation and retry.

Submission is an outbox: the job row (status PENDING) and its input artifact are
durably recorded first; only then is the RQ message sent and the row moved to
QUEUED. If Redis is down, the job stays PENDING and the reconciler enqueues it
later — it can never be lost or stuck forever.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics as pystats
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.jobs import ANALYSIS_ENGINE_VERSION
from app.jobs import queue as jq
from app.jobs.artifacts import ArtifactStore, sha256_bytes
from app.jobs.models import AnalysisJob, JobEvent, JobStatus, JobTile, Stage, TileStatus, as_utc, utcnow
from app.jobs.resources import STAGE_DESCRIPTIONS, background_limits, classify, estimate_resources
from app.services import area_analysis as aa
from app.services import area_geometry as ag
from app.services import boundaries
from app.services import spatial_trend_analysis as sta
from app.services.regional_tiling import NASA_MAX_SPAN, NASA_MIN_SPAN
from app.utils.errors import AnalysisTooLargeError, EarthScopeError, InvalidRequestError
from app.utils.validators import resolve_variable, validate_years

logger = logging.getLogger(__name__)
JOB_ID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"

# Failures caused by the request itself: retrying cannot help, a new analysis is needed.
INPUT_ERROR_CODES = {
    "INVALID_REQUEST", "INVALID_GEOMETRY", "GEOMETRY_TOO_COMPLEX", "COUNTRY_NOT_FOUND", "ANALYSIS_TOO_LARGE",
    "PARAMETER_NOT_AVAILABLE", "TEMPORAL_RANGE_UNAVAILABLE", "LOCATION_NOT_SUPPORTED", "NO_VALID_DATA",
    "BOUNDARY_VERSION_CHANGED", "INPUT_CHANGED", "STORAGE_BUDGET_EXCEEDED",
}


class JobNotFoundError(EarthScopeError):
    status_code = 404
    error = "JOB_NOT_FOUND"


class JobStateError(EarthScopeError):
    status_code = 409
    error = "JOB_STATE_CONFLICT"


class JobNotReadyError(EarthScopeError):
    status_code = 409
    error = "JOB_NOT_READY"
    retryable = True


class JobExpiredError(EarthScopeError):
    status_code = 410
    error = "JOB_EXPIRED"


class JobLimitError(EarthScopeError):
    status_code = 429
    error = "JOB_LIMIT_EXCEEDED"
    retryable = True


class IdempotencyConflictError(EarthScopeError):
    status_code = 409
    error = "IDEMPOTENCY_KEY_REUSED"


@dataclass
class JobRequest:
    iso3: str | None
    geometry: dict[str, Any] | None
    name: str | None
    variable: str
    start_year: int | None
    end_year: int | None
    coverage_threshold: float | None
    method: str
    correction: str
    alpha: float


@dataclass
class Plan:
    req: JobRequest
    area: aa.AreaSpec
    variable: Any
    start: int
    end: int
    coverage: float
    preflight: dict[str, Any]
    estimates: dict[str, Any]
    classification: dict[str, Any]
    config: dict[str, Any]
    config_hash: str


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Preflight / plan
# --------------------------------------------------------------------------- #

def build_plan(req: JobRequest, settings: Settings, db: Session | None = None) -> Plan:
    var = resolve_variable(req.variable)
    start, end = validate_years(req.start_year if req.start_year is not None else settings.default_start_year,
                                req.end_year if req.end_year is not None else settings.default_end_year,
                                settings, var.coverage_start_year)
    thr = settings.regional_coverage_threshold if req.coverage_threshold is None else req.coverage_threshold
    if not 0.5 <= thr <= 1.0:
        raise InvalidRequestError("coverage_threshold must be between 0.5 and 1.0.")
    sta.validate_settings(req.method, req.correction, req.alpha)
    area = aa.area_from_request(req.iso3, req.geometry, req.name, settings)
    pf = aa.preflight(area, var, start, end, settings)
    est = estimate_resources(pf, measured_history(db) if db is not None else None, settings, area.n_vertices)
    cls = classify(pf, est, settings)
    b = area.boundary or {}
    config = {
        "area": {"kind": area.kind, "iso3": area.iso3, "name": area.name, "geometry_id": area.geometry_id,
                 "boundary": {"source": b.get("source"), "version": b.get("version"), "boundary_id": b.get("boundary_id")} if b else None},
        "variable": {"id": var.id, "parameter": var.parameter, "community": var.community, "expected_unit": var.expected_unit},
        "period": {"start_year": start, "end_year": end},
        "coverage_threshold": round(thr, 4),
        "statistics": {
            "regional": "OLS, Mann-Kendall, Hamed-Rao (canonical + conservative), Yue-Wang, Sen's slope + CI, autocorrelation, HAC",
            "spatial_method": req.method, "correction": req.correction, "alpha": req.alpha,
            "significance_alpha": settings.significance_alpha, "confidence_level": settings.confidence_level,
            "min_valid_months_per_year": settings.min_valid_months_per_year, "min_annual_records": settings.min_annual_records,
        },
        "data_mode": "LIVE",
        "grid": ag.grid_for(var).name,
        "tiling": {"min_span_deg": NASA_MIN_SPAN, "max_span_deg": NASA_MAX_SPAN},
        "software_version": ANALYSIS_ENGINE_VERSION,
    }
    return Plan(req, area, var, start, end, thr, pf, est, cls, config, canonical_hash(config))


def preflight_payload(plan: Plan, settings: Settings) -> dict[str, Any]:
    pf, cls = plan.preflight, plan.classification
    return {
        "variable": plan.variable.id, "start_year": plan.start, "end_year": plan.end,
        "data_mode": plan.config["data_mode"],
        "preflight": pf,
        "background": {
            **cls,
            "estimates": plan.estimates,
            "stages": [{"id": k, "label": Stage.LABELS[k], "description": d} for k, d in STAGE_DESCRIPTIONS],
            "limits": background_limits(settings),
            "config_hash": plan.config_hash,
        },
    }


def measured_history(db: Session) -> dict[str, Any] | None:
    """Per-tile download and per-cell statistics durations from recent completed LIVE jobs."""
    rows = db.execute(
        select(AnalysisJob.metrics).where(AnalysisJob.status == JobStatus.COMPLETED, AnalysisJob.data_mode == "LIVE")
        .order_by(AnalysisJob.completed_at.desc()).limit(50)
    ).scalars().all()
    tile = [m["seconds_per_tile_round"] for m in rows if m and m.get("seconds_per_tile_round")]
    cell = [m["seconds_per_cell_stats"] for m in rows if m and m.get("seconds_per_cell_stats")]
    if len(tile) < 3 or len(cell) < 3:
        return None
    return {"n_jobs": min(len(tile), len(cell)), "seconds_per_tile": pystats.median(tile),
            "seconds_per_cell_stats": pystats.median(cell)}


# --------------------------------------------------------------------------- #
# Submission
# --------------------------------------------------------------------------- #

def _event(db: Session, job_id: str, level: str, message: str, stage: str | None = None, data: dict | None = None) -> None:
    db.add(JobEvent(job_id=job_id, at=utcnow(), level=level, stage=stage, message=message[:2000], data=data))


def _enforce_limits(db: Session, owner: str, ip: str | None, n_tiles: int, settings: Settings) -> None:
    now = utcnow()
    active = db.scalar(select(func.count()).select_from(AnalysisJob)
                       .where(AnalysisJob.owner_hash == owner, AnalysisJob.status.in_(JobStatus.ACTIVE)))
    if active >= settings.job_max_active_per_session:
        raise JobLimitError(f"You already have {active} analyses queued or running (limit {settings.job_max_active_per_session}).",
                            ["Wait for one to finish or cancel one on the Analysis Jobs page."])
    total_active = db.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status.in_(JobStatus.ACTIVE)))
    if total_active >= settings.job_max_global_active:
        raise JobLimitError("The analysis service is at capacity right now.", ["Please try again in a few minutes."])
    hour = db.scalar(select(func.count()).select_from(AnalysisJob)
                     .where(AnalysisJob.owner_hash == owner, AnalysisJob.created_at >= now - timedelta(hours=1)))
    if hour >= settings.job_max_submissions_per_hour:
        raise JobLimitError(f"At most {settings.job_max_submissions_per_hour} analyses can be submitted per hour.",
                            ["Please try again later."])
    if ip:
        day_ip = db.scalar(select(func.count()).select_from(AnalysisJob)
                           .where(AnalysisJob.client_ip_hash == ip, AnalysisJob.created_at >= now - timedelta(days=1)))
        if day_ip >= settings.job_max_submissions_per_ip_per_day:
            raise JobLimitError("The daily number of background analyses from this network has been reached.",
                                ["Please try again tomorrow."])
    tiles_today = db.scalar(select(func.coalesce(func.sum(AnalysisJob.tiles_total), 0))
                            .where(AnalysisJob.owner_hash == owner, AnalysisJob.created_at >= now - timedelta(days=1)))
    if tiles_today + n_tiles > settings.job_daily_tile_budget_per_session:
        raise JobLimitError(
            f"This analysis needs {n_tiles} NASA requests; your remaining daily budget is "
            f"{max(0, settings.job_daily_tile_budget_per_session - tiles_today)}.",
            ["NASA POWER is a shared public service; the budget resets after 24 hours."])


def submit(db: Session, plan: Plan, owner: str, ip: str | None, idem_key: str | None, force_new: bool,
           settings: Settings, store: ArtifactStore) -> tuple[AnalysisJob, bool, str | None]:
    """Record and enqueue a job. Returns (job, created, reason_if_existing)."""
    cls = plan.classification
    if not cls["eligible"]:
        raise AnalysisTooLargeError(
            "This region exceeds the background analysis budget of this deployment." if plan.preflight["n_cells"] else cls["reasons"][0],
            cls["reasons"] + ["Draw a custom polygon around a smaller part of the region."])

    if idem_key:
        existing = db.scalar(select(AnalysisJob).where(AnalysisJob.owner_hash == owner, AnalysisJob.idempotency_key == idem_key))
        if existing is not None:
            if existing.config_hash != plan.config_hash:
                raise IdempotencyConflictError("This Idempotency-Key was already used for a different analysis.")
            return existing, False, "idempotency_key"
    existing = db.scalar(select(AnalysisJob).where(AnalysisJob.owner_hash == owner, AnalysisJob.active_dedupe_key == plan.config_hash))
    if existing is not None:
        return existing, False, "active_duplicate"
    if not force_new:
        existing = db.scalar(select(AnalysisJob).where(
            AnalysisJob.owner_hash == owner, AnalysisJob.config_hash == plan.config_hash,
            AnalysisJob.status == JobStatus.COMPLETED).order_by(AnalysisJob.completed_at.desc()).limit(1))
        if existing is not None:
            return existing, False, "completed_duplicate"

    _enforce_limits(db, owner, ip, plan.preflight["n_tiles"], settings)

    job_id = str(uuid.uuid4())
    now = utcnow()
    a = plan.area
    input_doc = {
        "iso3": plan.req.iso3, "geometry": plan.req.geometry, "name": plan.req.name, "variable": plan.variable.id,
        "start_year": plan.start, "end_year": plan.end, "coverage_threshold": plan.coverage,
        "method": plan.req.method, "correction": plan.req.correction, "alpha": plan.req.alpha, "config": plan.config,
    }
    input_ref = f"{store.job_prefix(job_id)}/input.json"
    input_bytes = json.dumps(input_doc, sort_keys=True).encode()
    store.write_bytes(input_ref, input_bytes)
    b = a.boundary or {}
    job = AnalysisJob(
        id=job_id, owner_hash=owner, client_ip_hash=ip, idempotency_key=idem_key, job_type="area_analysis",
        area_kind=a.kind, area_name=a.name[:120], iso3=a.iso3, geometry_id=a.geometry_id,
        boundary_source=b.get("source"), boundary_version=b.get("version"),
        variable_id=plan.variable.id, parameter=plan.variable.parameter, community=plan.variable.community,
        start_year=plan.start, end_year=plan.end, coverage_threshold=plan.coverage,
        method=plan.req.method, correction=plan.req.correction, alpha=plan.req.alpha,
        data_mode=plan.config["data_mode"], config=plan.config, config_hash=plan.config_hash,
        active_dedupe_key=plan.config_hash, tier=cls["tier"],
        preflight={k: plan.preflight[k] for k in ("n_cells", "n_tiles", "n_months", "n_values", "grid")} | {"estimates": plan.estimates},
        input_ref=input_ref, input_sha256=sha256_bytes(input_bytes), software_version=ANALYSIS_ENGINE_VERSION,
        dataset_version=f"NASA POWER Monthly Regional API · {plan.variable.data_source}",
        status=JobStatus.PENDING, stage=Stage.QUEUED, activity="Recorded; waiting to be queued",
        tiles_total=plan.preflight["n_tiles"], cells_total=plan.preflight["n_cells"],
        created_at=now, updated_at=now, checkpoints={}, metrics={},
    )
    db.add(job)
    _event(db, job_id, "info", f"Job submitted ({cls['tier']} tier, {plan.preflight['n_tiles']} NASA requests, "
                               f"{plan.preflight['n_cells']} grid cells, {job.data_mode}).", Stage.QUEUED)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        store.remove_tree(store.job_prefix(job_id))
        existing = db.scalar(select(AnalysisJob).where(AnalysisJob.owner_hash == owner, AnalysisJob.active_dedupe_key == plan.config_hash))
        if existing is None and idem_key:
            existing = db.scalar(select(AnalysisJob).where(AnalysisJob.owner_hash == owner, AnalysisJob.idempotency_key == idem_key))
        if existing is None:
            raise
        return existing, False, "active_duplicate"
    hand_to_queue(db, job)
    return job, True, None


def hand_to_queue(db: Session, job: AnalysisJob, from_statuses: tuple[str, ...] = (JobStatus.PENDING,)) -> bool:
    """Send the RQ message, then mark QUEUED. On failure the job keeps its status for the reconciler."""
    try:
        rq_id = jq.enqueue(job.id)
    except Exception as exc:  # noqa: BLE001 - Redis down, network error, ...
        logger.warning("Enqueue failed for job %s: %s", job.id, type(exc).__name__)
        db.rollback()
        _event(db, job.id, "warn", "The task queue is temporarily unavailable; the job will be queued automatically when it recovers.")
        db.commit()
        return False
    now = utcnow()
    res = db.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == job.id, AnalysisJob.status.in_(from_statuses))
                     .values(status=JobStatus.QUEUED, rq_job_id=rq_id, queued_at=now, updated_at=now,
                             activity="Waiting for a worker"))
    db.commit()
    db.refresh(job)
    return res.rowcount == 1


# --------------------------------------------------------------------------- #
# Ownership, listing
# --------------------------------------------------------------------------- #

def get_owned(db: Session, job_id: str, owner: str) -> AnalysisJob:
    import re

    if not re.match(JOB_ID_RE, job_id or ""):
        raise JobNotFoundError("No analysis job with this id exists for your session.")
    job = db.get(AnalysisJob, job_id)
    # Same response for "does not exist" and "belongs to someone else": ids are never confirmed to strangers.
    if job is None or job.owner_hash != owner:
        raise JobNotFoundError("No analysis job with this id exists for your session.")
    return job


def list_owned(db: Session, owner: str, limit: int = 50) -> list[AnalysisJob]:
    return list(db.scalars(select(AnalysisJob).where(AnalysisJob.owner_hash == owner)
                           .order_by(AnalysisJob.created_at.desc()).limit(limit)))


# --------------------------------------------------------------------------- #
# Cancel / retry
# --------------------------------------------------------------------------- #

def cancel(db: Session, job: AnalysisJob) -> AnalysisJob:
    for _ in range(3):
        db.refresh(job)
        now = utcnow()
        if job.status in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RETRYING):
            # Not running anywhere: cancel immediately. A worker that later receives the
            # RQ message cannot claim it (claim requires a claimable status).
            res = db.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == job.id, AnalysisJob.status == job.status)
                             .values(status=JobStatus.CANCELLED, active_dedupe_key=None, cancel_requested_at=now,
                                     updated_at=now, activity="Cancelled before processing started",
                                     expires_at=now + timedelta(days=7)))
            if res.rowcount:
                _event(db, job.id, "info", "Cancelled by the user before processing started.")
                db.commit()
                db.refresh(job)
                return job
        elif job.status == JobStatus.RUNNING:
            res = db.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == job.id, AnalysisJob.status == JobStatus.RUNNING)
                             .values(status=JobStatus.CANCEL_REQUESTED, cancel_requested_at=now, updated_at=now,
                                     activity="Cancellation requested; stopping at the next safe checkpoint"))
            if res.rowcount:
                _event(db, job.id, "info", "Cancellation requested; the worker stops at the next safe checkpoint.")
                db.commit()
                db.refresh(job)
                return job
        elif job.status == JobStatus.CANCEL_REQUESTED:
            return job
        else:
            raise JobStateError(f"A {job.status.lower()} job cannot be cancelled.")
        db.rollback()
    raise JobStateError("The job changed state while cancelling; please try again.")


def resumable_summary(db: Session, job: AnalysisJob) -> dict[str, Any]:
    verified = db.scalar(select(func.count()).select_from(JobTile)
                         .where(JobTile.job_id == job.id, JobTile.status == TileStatus.VERIFIED)) or 0
    return {"verified_tiles": verified, "tiles_total": job.tiles_total,
            "checkpoints": sorted(k for k in (job.checkpoints or {}) if not k.startswith("chunk:")),
            "statistics_chunks_done": sum(1 for k in (job.checkpoints or {}) if k.startswith("chunk:"))}


def retry(db: Session, job: AnalysisJob, settings: Settings, store: ArtifactStore) -> AnalysisJob:
    db.refresh(job)
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise JobStateError(f"Only failed or cancelled jobs can be retried (this job is {job.status.lower()}).")
    if job.status == JobStatus.FAILED and (job.error_retryable is False or job.error_code in INPUT_ERROR_CODES):
        raise JobStateError(
            "This analysis failed because of its input, so retrying cannot succeed. Please start a new analysis.",
            [f"{job.error_code}: {job.error_message}"])
    if job.manual_retries >= settings.job_max_manual_retries:
        raise JobLimitError("This job has reached its retry limit. Please start a new analysis.")
    if job.area_kind == "country" and job.iso3:
        current = boundaries.country_meta(job.iso3).get("version")
        if current != job.boundary_version:
            raise JobStateError(
                "The country boundary dataset has changed since this job was submitted, so it cannot be resumed "
                "without silently mixing boundary versions. Please start a new analysis.",
                [f"Recorded: {job.boundary_version}; current: {current}."])
    if not store.verify(job.input_ref, job.input_sha256):
        raise JobStateError("The stored input of this job is no longer available (it may have expired). Please start a new analysis.")
    _enforce_limits(db, job.owner_hash, None, 0, settings)
    now = utcnow()
    try:
        res = db.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == job.id, AnalysisJob.status == job.status).values(
            status=JobStatus.PENDING, active_dedupe_key=job.config_hash, auto_attempts=0,
            manual_retries=AnalysisJob.manual_retries + 1, error_code=None, error_message=None, error_retryable=None,
            next_attempt_at=None, lease_owner=None, lease_expires_at=None, cancel_requested_at=None, expires_at=None,
            updated_at=now, activity="Retry requested; resuming from verified checkpoints"))
        db.execute(update(JobTile).execution_options(synchronize_session=False).where(JobTile.job_id == job.id, JobTile.status.in_((TileStatus.FAILED, TileStatus.RETRYING,
                                                                                         TileStatus.DOWNLOADING)))
                   .values(status=TileStatus.PENDING, attempts=0, retry_at=None, updated_at=now))
        if not res.rowcount:
            raise JobStateError("The job changed state; please reload and try again.")
        summary = resumable_summary(db, job)
        _event(db, job.id, "info", f"Retry requested by the user; {summary['verified_tiles']} of {summary['tiles_total']} "
                                   "NASA tiles are already verified and will not be downloaded again.", data=summary)
        db.commit()
    except IntegrityError:
        db.rollback()
        other = db.scalar(select(AnalysisJob.id).where(AnalysisJob.owner_hash == job.owner_hash,
                                                       AnalysisJob.active_dedupe_key == job.config_hash))
        raise JobStateError("An identical analysis is already queued or running.", [f"Job {other}"]) from None
    db.refresh(job)
    hand_to_queue(db, job)
    return job


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #

def _iso(dt) -> str | None:
    dt = as_utc(dt)
    return dt.isoformat(timespec="seconds") if dt else None


def stage_list(job: AnalysisJob) -> list[dict[str, Any]]:
    names = [k for k, _ in Stage.ORDER]
    cur = names.index(job.stage) if job.stage in names else (len(names) if job.status == JobStatus.COMPLETED else -1)
    out = []
    for i, k in enumerate(names):
        state = "done" if (i < cur or job.status == JobStatus.COMPLETED) else ("current" if i == cur and job.status in JobStatus.ACTIVE else "pending")
        if i == cur and job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            state = job.status.lower()
        out.append({"id": k, "label": Stage.LABELS[k], "state": state})
    return out


def progress_dict(job: AnalysisJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "stage_label": Stage.LABELS.get(job.stage, job.stage),
        "activity": job.activity,
        "progress_pct": 100.0 if job.status == JobStatus.COMPLETED else min(99.0, round(job.progress_pct or 0.0, 1)),
        "is_active": job.status in JobStatus.ACTIVE,
        "download": {"tiles_completed": job.tiles_completed, "tiles_total": job.tiles_total,
                     "tiles_retrying": job.tiles_retrying, "tiles_failed": job.tiles_failed},
        "processing": {"cells_processed": job.cells_processed, "cells_total": job.cells_total},
        "attempts": {"total": job.attempt_count, "automatic": job.auto_attempts, "max_automatic": None, "manual_retries": job.manual_retries},
        "updated_at": _iso(job.updated_at),
        "heartbeat_at": _iso(job.heartbeat_at),
        "stages": stage_list(job),
    }


def job_dict(job: AnalysisJob, settings: Settings, events: list[JobEvent] | None = None) -> dict[str, Any]:
    base = f"/api/analysis/jobs/{job.id}"
    p = progress_dict(job)
    p["attempts"]["max_automatic"] = settings.job_max_attempts
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "tier": job.tier,
        "data_mode": job.data_mode,
        "area": {"kind": job.area_kind, "name": job.area_name, "iso3": job.iso3, "geometry_id": job.geometry_id,
                 "boundary_source": job.boundary_source, "boundary_version": job.boundary_version},
        "variable_id": job.variable_id,
        "parameter": job.parameter,
        "community": job.community,
        "start_year": job.start_year,
        "end_year": job.end_year,
        "config": job.config,
        "config_hash": job.config_hash,
        "preflight": job.preflight,
        "progress": p,
        "error": {"code": job.error_code, "message": job.error_message, "retryable": bool(job.error_retryable)}
        if job.error_code else None,
        "created_at": _iso(job.created_at),
        "queued_at": _iso(job.queued_at),
        "started_at": _iso(job.started_at),
        "updated_at": _iso(job.updated_at),
        "completed_at": _iso(job.completed_at),
        "expires_at": _iso(job.expires_at),
        "software_version": job.software_version,
        "dataset_version": job.dataset_version,
        "can_cancel": job.status in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.RUNNING),
        "can_retry": job.status == JobStatus.CANCELLED or (
            job.status == JobStatus.FAILED and bool(job.error_retryable) and job.error_code not in INPUT_ERROR_CODES),
        "has_results": job.status == JobStatus.COMPLETED,
        "links": {"self": base, "progress": f"{base}/progress", "results": f"{base}/results",
                  "spatial": f"{base}/spatial", "artifacts": f"{base}/artifacts"},
        "events": [{"at": _iso(e.at), "level": e.level, "stage": e.stage, "message": e.message} for e in (events or [])],
    }


def recent_events(db: Session, job_id: str, limit: int = 30) -> list[JobEvent]:
    return list(reversed(db.scalars(select(JobEvent).where(JobEvent.job_id == job_id)
                                    .order_by(JobEvent.id.desc()).limit(limit)).all()))
