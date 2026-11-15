"""Checkpointed background analysis pipeline (run inside an RQ worker).

Execution model
---------------
* A worker **claims** a job with one compare-and-set UPDATE (claimable status,
  or RUNNING with an expired lease). Two workers can never both succeed.
* While it runs, a heartbeat thread extends the **lease** and picks up
  cancellation requests. Every write the worker makes is conditional on still
  holding the lease; if another worker took over (after this one stalled), the
  write fails and this worker stops without touching the job.
* Every stage writes a **checkpoint** (atomic file + SHA-256 in PostgreSQL)
  and skips its work on a later attempt when that checkpoint verifies:
  verified NASA tiles are never downloaded again, completed statistics chunks
  are never recomputed. All stages are deterministic, so re-running one after a
  crash yields the same bytes (at-least-once execution, idempotent effects —
  not "exactly once").
* Results are written to a staging directory, verified, and published with a
  single directory rename; the job becomes COMPLETED only after that and after
  the completion row is committed.

The science is delegated to the same functions the synchronous endpoints use.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

import numpy as np
import redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.jobs import ANALYSIS_ENGINE_VERSION
from app.jobs.artifacts import ArtifactCorruptError, ArtifactError, ArtifactStore, dumps, gz, sha256_bytes, strict_json
from app.jobs.coordination import GlobalNasaLimiter, LimiterCancelled
from app.jobs.db import with_db_retry
from app.jobs.models import AnalysisJob, JobEvent, JobStatus, JobTile, Stage, TileStatus, as_utc, utcnow
from app.jobs.service import INPUT_ERROR_CODES, canonical_hash
from app.services import area_analysis as aa
from app.services import area_geometry as ag
from app.services import regional_aggregation as ra
from app.services import regional_analysis as ran
from app.services import spatial_trend_analysis as sta
from app.services.nasa_power import NasaPowerClient
from app.services.regional_tiling import Tile, TileResult, merge_tiles, plan_tiles, validate_tile_payload
from app.utils.errors import AnalysisTooLargeError, EarthScopeError, IncompleteTileRetrievalError
from app.utils.validators import resolve_variable

logger = logging.getLogger("earthscope.jobs")


class LeaseLost(Exception):
    """Another worker owns the job now (or it was reset); stop without writing."""


class JobCancelled(Exception):
    """Cooperative cancellation reached a safe checkpoint."""


class InputChangedError(EarthScopeError):
    status_code = 409
    error = "INPUT_CHANGED"


class BoundaryChangedError(EarthScopeError):
    status_code = 409
    error = "BOUNDARY_VERSION_CHANGED"


class StorageBudgetError(EarthScopeError):
    status_code = 422
    error = "STORAGE_BUDGET_EXCEEDED"


class InfrastructureError(EarthScopeError):
    status_code = 503
    error = "INFRASTRUCTURE_UNAVAILABLE"
    retryable = True


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Claim / context / heartbeat
# --------------------------------------------------------------------------- #

def claim(sm: sessionmaker[Session], job_id: str, worker_id: str, settings: Settings) -> bool:
    """Atomically take ownership of a job. Returns False if it is not claimable."""
    def op() -> int:
        now = utcnow()
        with sm() as s:
            res = s.execute(
                update(AnalysisJob).execution_options(synchronize_session=False).where(
                    AnalysisJob.id == job_id,
                    (AnalysisJob.status.in_(JobStatus.CLAIMABLE)
                     & ((AnalysisJob.next_attempt_at.is_(None)) | (AnalysisJob.next_attempt_at <= now)))
                    | ((AnalysisJob.status == JobStatus.RUNNING) & (AnalysisJob.lease_expires_at < now)),
                ).values(
                    status=JobStatus.RUNNING, lease_owner=worker_id, lease_expires_at=now + timedelta(seconds=settings.job_lease_seconds),
                    heartbeat_at=now, started_at=func.coalesce(AnalysisJob.started_at, now), updated_at=now,
                    attempt_count=AnalysisJob.attempt_count + 1, auto_attempts=AnalysisJob.auto_attempts + 1,
                    next_attempt_at=None, activity="Worker started",
                )
            )
            if res.rowcount:
                s.add(JobEvent(job_id=job_id, at=now, level="info", stage=None, message="A worker started processing this job.",
                               data={"worker": worker_id.split(":")[0]}))
            s.commit()
            return res.rowcount
    return with_db_retry(op) == 1


class JobContext:
    def __init__(self, job_id: str, worker_id: str, settings: Settings, sm: sessionmaker[Session], store: ArtifactStore,
                 limiter: GlobalNasaLimiter | None, client: NasaPowerClient | None = None):
        self.job_id = job_id
        self.worker_id = worker_id
        self.settings = settings
        self.sm = sm
        self.store = store
        self.limiter = limiter
        self.client = client
        self.cancel_event = threading.Event()
        self.lease_lost = threading.Event()
        with sm() as s:
            job = s.get(AnalysisJob, job_id)
            assert job is not None
            s.expunge(job)
        self.job = job
        self.checkpoints: dict[str, Any] = dict(job.checkpoints or {})
        self.metrics: dict[str, Any] = dict(job.metrics or {})
        self.max_pct = float(job.progress_pct or 0.0)
        self._stage_t0: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # ---- guarded writes ------------------------------------------------------
    def _write(self, values: dict[str, Any], statuses: tuple[str, ...] = (JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)) -> None:
        def op() -> int:
            with self.sm() as s:
                res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(
                    AnalysisJob.id == self.job_id, AnalysisJob.lease_owner == self.worker_id, AnalysisJob.status.in_(statuses)
                ).values(**values, updated_at=utcnow()))
                s.commit()
                return res.rowcount
        with self._lock:
            if with_db_retry(op) == 0:
                self.lease_lost.set()
                raise LeaseLost()

    def event(self, level: str, message: str, stage: str | None = None, data: dict[str, Any] | None = None) -> None:
        def op() -> None:
            with self.sm() as s:
                s.add(JobEvent(job_id=self.job_id, at=utcnow(), level=level, stage=stage, message=message[:2000], data=data))
                s.commit()
        try:
            with_db_retry(op)
        except Exception:  # noqa: BLE001 - events are informative; never fail a job over one
            logger.warning("Could not record event for job %s", self.job_id)

    def heartbeat(self) -> None:
        now = utcnow()
        with self.sm() as s:
            res = s.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(
                AnalysisJob.id == self.job_id, AnalysisJob.lease_owner == self.worker_id,
                AnalysisJob.status.in_((JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)),
            ).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=self.settings.job_lease_seconds)))
            status = s.scalar(select(AnalysisJob.status).where(AnalysisJob.id == self.job_id))
            s.commit()
        if res.rowcount == 0:
            self.lease_lost.set()
            self.cancel_event.set()   # stops downloads promptly; check() raises LeaseLost first
            return
        if status == JobStatus.CANCEL_REQUESTED:
            self.cancel_event.set()

    @property
    def current_stage(self) -> str | None:
        return self._stage_t0[0] if self._stage_t0 else None

    def check(self) -> None:
        if self.lease_lost.is_set():
            raise LeaseLost()
        if self.cancel_event.is_set():
            raise JobCancelled()

    # ---- progress -----------------------------------------------------------
    @staticmethod
    def stage_pct(stage: str, frac: float) -> float:
        done = 0.0
        for name, w in Stage.ORDER:
            if name == stage:
                return done + w * max(0.0, min(1.0, frac))
            done += w
        return done

    def set_stage(self, stage: str, activity: str, **extra: Any) -> None:
        self.check()
        now = time.monotonic()
        if self._stage_t0 is not None:
            prev, t0 = self._stage_t0
            self.metrics.setdefault("stage_seconds", {})[prev] = round(self.metrics.get("stage_seconds", {}).get(prev, 0) + now - t0, 3)
        self._stage_t0 = (stage, now)
        self.max_pct = max(self.max_pct, self.stage_pct(stage, 0.0))
        logger.info("job=%s stage=%s worker=%s %s", self.job_id, stage, self.worker_id, activity)
        self._write({"stage": stage, "activity": activity[:300], "progress_pct": min(99.0, self.max_pct), "metrics": self.metrics, **extra})

    def progress(self, stage: str, frac: float, activity: str | None = None, **counters: Any) -> None:
        self.max_pct = max(self.max_pct, self.stage_pct(stage, frac))
        values: dict[str, Any] = {"progress_pct": min(99.0, self.max_pct), **counters}
        if activity:
            values["activity"] = activity[:300]
        self._write(values)

    # ---- checkpoints -------------------------------------------------------
    def work(self, name: str) -> str:
        return f"{self.store.job_prefix(self.job_id)}/work/{name}"

    def save_checkpoint(self, key: str, rel: str, obj: Any) -> None:
        sha, size = self.store.write_json_gz(rel, obj)
        self.checkpoints[key] = {"ref": rel, "sha256": sha, "bytes": size, "at": _iso_now()}
        self._write({"checkpoints": dict(self.checkpoints)})

    def load_checkpoint(self, key: str) -> Any | None:
        c = self.checkpoints.get(key)
        if not c:
            return None
        try:
            return self.store.read_json_gz(c["ref"], c["sha256"])
        except ArtifactError:
            logger.warning("job=%s checkpoint %s failed verification; recomputing", self.job_id, key)
            self.event("warn", f"Checkpoint '{key}' failed verification and is recomputed.")
            return None

    def save_bytes_checkpoint(self, key: str, rel: str, data: bytes) -> None:
        sha, size = self.store.write_bytes(rel, data)
        self.checkpoints[key] = {"ref": rel, "sha256": sha, "bytes": size, "at": _iso_now()}
        self._write({"checkpoints": dict(self.checkpoints)})

    def load_bytes_checkpoint(self, key: str) -> bytes | None:
        c = self.checkpoints.get(key)
        if not c:
            return None
        try:
            return self.store.read_bytes(c["ref"], c["sha256"])
        except ArtifactError:
            return None

    # ---- tiles ----------------------------------------------------------------
    def tile_rows(self) -> list[JobTile]:
        def op() -> list[JobTile]:
            with self.sm() as s:
                rows = list(s.scalars(select(JobTile).where(JobTile.job_id == self.job_id).order_by(JobTile.tile_key)))
                for r in rows:
                    s.expunge(r)
                return rows
        return with_db_retry(op)

    def update_tile(self, tile_key: str, **values: Any) -> None:
        def op() -> None:
            with self.sm() as s:
                s.execute(update(JobTile).execution_options(synchronize_session=False).where(JobTile.job_id == self.job_id, JobTile.tile_key == tile_key)
                          .values(**values, updated_at=utcnow()))
                s.commit()
        with_db_retry(op)

    def refresh_tile_counters(self, activity: str | None = None) -> None:
        def op() -> dict[str, int]:
            with self.sm() as s:
                rows = s.execute(select(JobTile.status, func.count()).where(JobTile.job_id == self.job_id).group_by(JobTile.status)).all()
                return {k: n for k, n in rows}
        counts = with_db_retry(op)
        total = sum(counts.values()) or 1
        done = counts.get(TileStatus.VERIFIED, 0)
        self.progress(Stage.DOWNLOADING_NASA_DATA, done / total, activity, tiles_completed=done,
                      tiles_retrying=counts.get(TileStatus.RETRYING, 0), tiles_failed=counts.get(TileStatus.FAILED, 0))


class Heartbeat(threading.Thread):
    def __init__(self, ctx: JobContext):
        super().__init__(daemon=True, name=f"heartbeat-{ctx.job_id[:8]}")
        self.ctx = ctx
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(self.ctx.settings.job_heartbeat_seconds):
            try:
                self.ctx.heartbeat()
            except Exception as exc:  # noqa: BLE001 - DB outage: keep trying; writes re-check the lease
                logger.warning("job=%s heartbeat failed: %s", self.ctx.job_id, type(exc).__name__)
            if self.ctx.lease_lost.is_set():
                return

    def stop(self) -> None:
        self.stop_event.set()


# --------------------------------------------------------------------------- #
# Tile retrieval
# --------------------------------------------------------------------------- #

def tile_request_hash(variable, tile: Tile, start: int, end: int, settings: Settings) -> str:
    """Identity of one exact NASA request."""
    ident: dict[str, Any] = {
        "parameter": variable.parameter, "community": variable.community,
        "lat_min": f"{tile.lat_min:.4f}", "lat_max": f"{tile.lat_max:.4f}",
        "lon_min": f"{tile.lon_min:.4f}", "lon_max": f"{tile.lon_max:.4f}", "start": start, "end": end,
        "endpoint": settings.nasa_power_regional_url,
    }
    return canonical_hash(ident)


def _backoff(settings: Settings, attempt: int, retry_after: float | None) -> float:
    base = min(settings.job_tile_backoff_max_seconds, settings.job_tile_backoff_seconds * (2 ** attempt))
    delay = base * (0.5 + random.random() / 2)       # "equal jitter"
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(delay, max(settings.job_tile_backoff_max_seconds, retry_after or 0))


def _sleep_interruptible(ctx: JobContext, seconds: float, abort: threading.Event) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if abort.is_set() or ctx.cancel_event.is_set():
            return
        time.sleep(min(0.5, end - time.monotonic()))


def download_tiles(ctx: JobContext, variable, tiles: list[Tile], start: int, end: int,
                   grid_spec: ag.GridSpec) -> dict[str, Any]:
    s = ctx.settings
    rows = {r.tile_key: r for r in ctx.tile_rows()}
    todo = [t for t in tiles if not (rows[t.key].status == TileStatus.VERIFIED
                                     and ctx.store.verify(ctx.store.blob_ref(rows[t.key].blob_sha256 or ""), rows[t.key].blob_sha256))]
    reused = len(tiles) - len(todo)
    if reused:
        ctx.event("info", f"{reused} of {len(tiles)} NASA tiles were already verified in an earlier attempt and are reused.",
                  Stage.DOWNLOADING_NASA_DATA)
    ctx.refresh_tile_counters(f"Downloading NASA POWER tiles ({reused} of {len(tiles)} already verified)")
    stats = {"downloaded": 0, "reused_checkpoint": reused, "reused_cache": 0, "retries": 0, "seconds": []}
    if not todo:
        return stats
    latest_partial = datetime.now(timezone.utc).year if end >= datetime.now(timezone.utc).year else None
    abort = threading.Event()
    fatal: list[BaseException] = []
    stat_lock = threading.Lock()

    def fetch(t: Tile) -> tuple[dict[str, Any], str | None, str]:
        assert ctx.limiter is not None and ctx.client is not None
        with ctx.limiter.slot(cancel=ctx.cancel_event):
            f = ctx.client.fetch_regional(variable, t.lat_min, t.lat_max, t.lon_min, t.lon_max, start, end)
        return f.payload, f.request_url, f.retrieved_at

    def one(t: Tile) -> None:
        row = rows[t.key]
        rh = row.request_hash
        for attempt in range(row.attempts, s.job_tile_max_attempts):
            if abort.is_set() or ctx.cancel_event.is_set():
                return
            entry = ctx.store.lookup_tile(rh)
            if entry is not None:
                age_h = (time.time() - entry.get("stored_epoch", 0)) / 3600
                if age_h <= s.job_tile_cache_hours:
                    ctx.update_tile(t.key, status=TileStatus.VERIFIED, blob_sha256=entry["sha256"], blob_bytes=entry.get("bytes"),
                                    request_url=entry.get("url"), retrieved_at=entry.get("retrieved_at"), from_cache=True,
                                    n_features=entry.get("n_features"), validation=entry.get("validation"), last_error=None)
                    with stat_lock:
                        stats["reused_cache"] += 1
                    ctx.refresh_tile_counters()
                    return
            ctx.update_tile(t.key, status=TileStatus.DOWNLOADING, attempts=attempt + 1)
            t0 = time.monotonic()
            try:
                payload, url, retrieved_at = fetch(t)
                summary = validate_tile_payload(payload, variable, t, start, end, grid_spec, latest_partial)
                sha, size = ctx.store.put_tile_blob(payload)
                del payload
                ctx.store.index_tile(rh, {"sha256": sha, "bytes": size, "url": url, "retrieved_at": retrieved_at,
                                          "stored_epoch": time.time(), "n_features": summary["n_features"], "validation": summary})
                ctx.update_tile(t.key, status=TileStatus.VERIFIED, blob_sha256=sha, blob_bytes=size, request_url=url,
                                retrieved_at=retrieved_at, from_cache=False, n_features=summary["n_features"],
                                validation=summary, last_error=None, last_error_code=None, retry_at=None)
                with stat_lock:
                    stats["downloaded"] += 1
                    stats["seconds"].append(time.monotonic() - t0)
                logger.info("job=%s tile=%s verified features=%s %.1fs", ctx.job_id, t.key, summary["n_features"], time.monotonic() - t0)
                ctx.refresh_tile_counters()
                return
            except LimiterCancelled:
                ctx.update_tile(t.key, status=TileStatus.PENDING, attempts=attempt)
                return
            except EarthScopeError as exc:
                if not exc.retryable:
                    ctx.update_tile(t.key, status=TileStatus.FAILED, last_error=exc.message, last_error_code=exc.error)
                    ctx.event("error", f"NASA tile {t.key} was rejected and will not be retried: {exc.message}",
                              Stage.DOWNLOADING_NASA_DATA, {"tile": t.key, "code": exc.error, "details": exc.details[:3]})
                    raise
                if attempt + 1 >= s.job_tile_max_attempts:
                    break
                delay = _backoff(s, attempt, getattr(exc, "retry_after", None))
                ctx.update_tile(t.key, status=TileStatus.RETRYING, last_error=exc.message, last_error_code=exc.error,
                                retry_at=utcnow() + timedelta(seconds=delay))
                with stat_lock:
                    stats["retries"] += 1
                ctx.event("warn", f"NASA tile {t.key} attempt {attempt + 1} failed ({exc.error}); retrying in {delay:.0f} s.",
                          Stage.DOWNLOADING_NASA_DATA, {"tile": t.key, "code": exc.error,
                                                        "http_status": getattr(exc, "http_status", None)})
                ctx.refresh_tile_counters()
                _sleep_interruptible(ctx, delay, abort)
        if not (abort.is_set() or ctx.cancel_event.is_set()):
            ctx.update_tile(t.key, status=TileStatus.FAILED)
            ctx.event("error", f"NASA tile {t.key} failed after {s.job_tile_max_attempts} attempts.", Stage.DOWNLOADING_NASA_DATA,
                      {"tile": t.key})
            ctx.refresh_tile_counters()

    workers = max(1, min(len(todo), s.nasa_global_max_concurrency))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"tiles-{ctx.job_id[:8]}") as pool:
        futures = [pool.submit(one, t) for t in todo]
        for fut in as_completed(futures):
            exc = fut.exception()
            if exc is not None:
                abort.set()
                fatal.append(exc)
    ctx.check()
    for exc in fatal:
        if isinstance(exc, (LeaseLost, JobCancelled)):
            raise exc
    for exc in fatal:
        if isinstance(exc, EarthScopeError) and not exc.retryable:
            raise exc
    if fatal:
        raise fatal[0]
    failed = [r for r in ctx.tile_rows() if r.status != TileStatus.VERIFIED]
    if failed:
        raise IncompleteTileRetrievalError(
            f"{len(failed)} of {len(tiles)} NASA POWER requests failed after {s.job_tile_max_attempts} attempt(s); "
            "verified tiles are kept and a retry will only fetch the missing ones.",
            [f"{r.tile_key} (lat {r.lat_min}…{r.lat_max}, lon {r.lon_min}…{r.lon_max}): {r.last_error or 'failed'}" for r in failed[:8]],
        )
    return stats


def stream_tile_results(ctx: JobContext, tiles: list[Tile]) -> Iterator[TileResult]:
    """Yield checkpointed tiles one at a time (each payload is released before the next is read)."""
    rows = {r.tile_key: r for r in ctx.tile_rows()}
    for t in tiles:
        r = rows[t.key]
        if r.status != TileStatus.VERIFIED or not r.blob_sha256:
            raise IncompleteTileRetrievalError(f"Tile {t.key} has no verified checkpoint; the area would be incomplete.")
        payload = ctx.store.get_tile_blob(r.blob_sha256)
        yield TileResult(t, payload, r.request_url, r.retrieved_at or "", bool(r.from_cache), r.attempts, r.n_features or 0)


# --------------------------------------------------------------------------- #
# Grid checkpoint (RegionalGrid <-> npz + json)
# --------------------------------------------------------------------------- #

_GRID_ARRAYS = ("lats", "lons", "values", "years", "months", "overlap_km2", "cell_km2", "excluded")


def grid_to_bytes(loaded: ran.LoadedGrid) -> tuple[bytes, dict[str, Any]]:
    g = loaded.grid
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: getattr(g, k) for k in _GRID_ARRAYS})
    meta = {k: getattr(g, k) for k in ("exclusion_reason", "box_km2", "units_raw", "sources", "fill_value", "dataset_title",
                                        "api_version", "time_standard", "long_name", "n_features", "n_duplicates",
                                        "n_outside", "n_invalid_values", "warnings", "clips")}
    meta["loaded"] = {"payload": loaded.payload, "retrieved_at": loaded.retrieved_at, "from_cache": loaded.from_cache,
                      "land_fraction": loaded.land_fraction, "manifest": loaded.manifest, "n_missing_cells": loaded.n_missing_cells}
    return buf.getvalue(), meta


def grid_from_bytes(data: bytes, meta: dict[str, Any]) -> ran.LoadedGrid:
    arrs = np.load(io.BytesIO(data), allow_pickle=False)
    kw = {k: arrs[k] for k in _GRID_ARRAYS}
    kw["excluded"] = kw["excluded"].astype(bool)
    lm = meta.pop("loaded")
    grid = ra.RegionalGrid(**kw, **meta)
    return ran.LoadedGrid(grid, lm["payload"], lm["retrieved_at"], None, lm["from_cache"], lm["land_fraction"],
                          lm["manifest"], lm["n_missing_cells"])


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #

def _execution_meta(job: AnalysisJob) -> dict[str, Any]:
    return {"execution_mode": "background", "job_id": job.id, "analysis_software_version": ANALYSIS_ENGINE_VERSION,
            "published_at": _iso_now()}


def run_pipeline(ctx: JobContext) -> None:
    job, s, store = ctx.job, ctx.settings, ctx.store
    t_start = time.monotonic()
    inp = json.loads(store.read_bytes(job.input_ref, job.input_sha256))

    # 1 ── geometry ────────────────────────────────────────────────────────────
    ctx.set_stage(Stage.PREPARING_GEOMETRY, f"Loading and validating {'the country boundary' if job.area_kind == 'country' else 'the polygon'}")
    area = aa.area_from_request(inp["iso3"], inp["geometry"], inp["name"], s)
    if job.area_kind == "country" and (area.boundary or {}).get("version") != job.boundary_version:
        raise BoundaryChangedError("The country boundary dataset changed after this job was submitted; it is not silently substituted.",
                                   [f"Recorded {job.boundary_version}, now {(area.boundary or {}).get('version')}."])
    if area.geometry_id != job.geometry_id:
        raise InputChangedError("The analysed geometry no longer matches the one recorded at submission.")
    var = resolve_variable(job.variable_id)
    if (var.parameter, var.community) != (job.parameter, job.community):
        raise InputChangedError("The variable definition changed after submission (parameter or community).")
    q = ran.RegionalQuery(var, area.bbox, job.start_year, job.end_year, job.coverage_threshold, area)
    grid_spec = ag.grid_for(var)

    # 2 ── polygon weights ────────────────────────────────────────────────────
    ctx.set_stage(Stage.CALCULATING_POLYGON_WEIGHTS, f"Exact overlap of ~{job.cells_total:,} grid cells with the area")
    ov_raw = ctx.load_checkpoint("overlaps")
    if ov_raw is None:
        t0 = time.monotonic()
        overlaps = ag.cell_overlaps(area.geometry, grid_spec)
        ctx.metrics["overlap_seconds"] = round(time.monotonic() - t0, 3)
        ctx.save_checkpoint("overlaps", ctx.work("overlaps.json.gz"), [asdict(c) for c in overlaps])
    else:
        overlaps = [ag.CellOverlap(**c) for c in ov_raw]
    if not overlaps:
        raise AnalysisTooLargeError("The area does not overlap any NASA grid cell with positive area.")

    # 3 ── tile manifest ─────────────────────────────────────────────────────
    ctx.set_stage(Stage.PREPARING_NASA_REQUESTS, "Planning NASA POWER regional requests")
    tiles = plan_tiles([(c.i, c.j) for c in overlaps], grid_spec)
    max_tiles = s.job_very_large_max_tiles if s.job_allow_very_large else s.job_large_max_tiles
    max_cells = s.job_very_large_max_cells if s.job_allow_very_large else s.job_large_max_cells
    if len(tiles) > max_tiles or len(overlaps) > max_cells:
        raise AnalysisTooLargeError(f"The area needs {len(tiles)} NASA requests and {len(overlaps)} cells, above this deployment's budget.")
    _ensure_manifest(ctx, tiles, var, job)
    # Each run gives unverified tiles a fresh, bounded attempt budget (verified tiles are untouched).
    def reset_tiles() -> None:
        with ctx.sm() as sess:
            sess.execute(update(JobTile).execution_options(synchronize_session=False).where(JobTile.job_id == job.id, JobTile.status != TileStatus.VERIFIED)
                         .values(status=TileStatus.PENDING, attempts=0, retry_at=None, updated_at=utcnow()))
            sess.commit()
    with_db_retry(reset_tiles)
    ctx._write({"tiles_total": len(tiles), "cells_total": len(overlaps)})

    # 4 ── download ───────────────────────────────────────────────────────────
    ctx.set_stage(Stage.DOWNLOADING_NASA_DATA, f"Downloading {len(tiles)} NASA POWER tiles")
    t0 = time.monotonic()
    dl = download_tiles(ctx, var, tiles, job.start_year, job.end_year, grid_spec)
    ctx.metrics["download"] = {k: v for k, v in dl.items() if k != "seconds"} | {
        "wall_seconds": round(time.monotonic() - t0, 2),
        "median_tile_seconds": round(float(np.median(dl["seconds"])), 2) if dl["seconds"] else None}
    if dl["seconds"] and dl["downloaded"] >= 2:
        rounds = math.ceil(dl["downloaded"] / max(1, s.nasa_global_max_concurrency))
        ctx.metrics["seconds_per_tile_round"] = round((time.monotonic() - t0) / rounds, 3)

    # 5 ── validation of completeness ─────────────────────────────────────────
    ctx.set_stage(Stage.VALIDATING_DATA, "Checking that every tile is present and verified")
    rows = ctx.tile_rows()
    bad = [r.tile_key for r in rows if r.status != TileStatus.VERIFIED or not store.verify(store.blob_ref(r.blob_sha256 or ""), r.blob_sha256)]
    if bad or len(rows) != len(tiles):
        raise IncompleteTileRetrievalError("Not every NASA tile has a verified checkpoint; no incomplete country result is produced.", bad[:8])
    units = {(r.validation or {}).get("units") for r in rows}
    if len(units) > 1:
        raise InputChangedError("NASA tiles reported different units for the same parameter; they are not mixed.", [str(sorted(map(str, units)))])

    # 6 ── merge ─────────────────────────────────────────────────────────────
    ctx.set_stage(Stage.MERGING_GRID_CELLS, f"Merging {len(tiles)} tiles into {len(overlaps):,} unique grid cells")
    loaded = None
    gb, gm = ctx.load_bytes_checkpoint("grid_arrays"), ctx.load_checkpoint("grid_meta")
    if gb is not None and gm is not None:
        loaded = grid_from_bytes(gb, gm)
    if loaded is None:
        merged = merge_tiles(stream_tile_results(ctx, tiles), var, overlaps, grid_spec, job.start_year, job.end_year, area.area_km2)
        total_overlap = float(np.sum(merged.grid.overlap_km2))
        if abs(total_overlap - area.area_km2) > 1e-6 * max(1.0, area.area_km2):   # identical rule to the synchronous path
            merged.grid.warnings.append(
                f"The grid cells cover {total_overlap / area.area_km2 * 100:.3f}% of the polygon area (sliver cells below 1e-6 km² are ignored).")
        land_fraction = ra.check_land_fraction(merged.grid, var, s.regional_min_land_fraction)
        retrieved = [m["retrieved_at"] for m in merged.manifest if m.get("retrieved_at")]
        loaded = ran.LoadedGrid(merged.grid, merged.header_payload, max(retrieved) if retrieved else _iso_now(), None,
                                all(m["from_cache"] for m in merged.manifest), land_fraction, merged.manifest, merged.n_missing_cells)
        data, meta = grid_to_bytes(loaded)
        ctx.save_bytes_checkpoint("grid_arrays", ctx.work("grid.npz"), data)
        ctx.save_checkpoint("grid_meta", ctx.work("grid_meta.json.gz"), meta)
        ctx.event("info", f"Merged {merged.n_returned:,} returned cells: {len(overlaps):,} used, {merged.n_duplicates} duplicates "
                          f"counted once, {merged.n_missing_cells} missing.", Stage.MERGING_GRID_CELLS)
    grid = loaded.grid   # duplicate cells were verified identical by merge_tiles (it raises on any conflict)

    # 7 ── regional series + regional statistics ─────────────────────────────
    ctx.set_stage(Stage.BUILDING_TIME_SERIES, "Polygon-weighted monthly and annual series, regional trend tests")
    regional = ctx.load_checkpoint("regional")
    if regional is None:
        regional = ran.build_regional_from_loaded(q, loaded, s, analyze=True)  # type: ignore[arg-type]
        ctx.save_checkpoint("regional", ctx.work("regional.json.gz"), regional)

    # 8 ── per-cell statistics in checkpointed chunks ───────────────────────
    n = len(grid.lats)
    size = max(1, s.job_cell_chunk_size)
    chunks = [(a, min(n, a + size)) for a in range(0, n, size)]
    ctx.set_stage(Stage.RUNNING_STATISTICS, f"Trend tests for {n:,} grid cells ({len(chunks)} chunks)", cells_total=n)
    table = ra.cell_annual_table(grid)
    done_cells = sum(b - a for k, (a, b) in enumerate(chunks) if f"chunk:{k}" in ctx.checkpoints)
    t0 = time.monotonic()
    computed = 0
    for k, (a, b) in enumerate(chunks):
        key = f"chunk:{k}"
        c = ctx.checkpoints.get(key)
        if c and c.get("range") == [a, b] and store.verify(c["ref"], c["sha256"]):
            continue
        ctx.check()
        cells, details, complete = sta.compute_cell_rows(grid, range(a, b), s, table)
        rel = ctx.work(f"cells/chunk-{k:05d}.json.gz")
        sha, nbytes = store.write_json_gz(rel, {"range": [a, b], "cells": cells, "details": details, "complete": complete})
        ctx.checkpoints[key] = {"ref": rel, "sha256": sha, "bytes": nbytes, "range": [a, b], "at": _iso_now()}
        computed += b - a
        done_cells = sum(bb - aa_ for kk, (aa_, bb) in enumerate(chunks) if f"chunk:{kk}" in ctx.checkpoints)
        ctx._write({"checkpoints": dict(ctx.checkpoints)})
        ctx.progress(Stage.RUNNING_STATISTICS, done_cells / n, f"Trend tests: {done_cells:,} of {n:,} cells", cells_processed=done_cells)
    if computed:
        ctx.metrics["seconds_per_cell_stats"] = round((time.monotonic() - t0) / computed, 5)
    ctx.progress(Stage.RUNNING_STATISTICS, 1.0, f"Trend tests: {n:,} of {n:,} cells", cells_processed=n)

    # 9 ── spatial FDR over the complete family ──────────────────────────────
    ctx.set_stage(Stage.CALCULATING_SPATIAL_FDR, "Multiple-testing correction over every eligible cell of the area")
    all_cells: list[dict[str, Any]] = []
    detail_index: dict[str, int] = {}
    complete_all = True
    for k, (a, b) in enumerate(chunks):
        c = ctx.checkpoints[f"chunk:{k}"]
        part = store.read_json_gz(c["ref"], c["sha256"])
        if part["range"] != [a, b] or len(part["cells"]) != b - a:
            raise ArtifactCorruptError("A statistics checkpoint does not match its cell range.")
        all_cells.extend(part["cells"])
        complete_all = complete_all and part["complete"]
        for cid in part["details"]:
            detail_index[cid] = k
        del part
    if len(all_cells) != n:
        raise ArtifactCorruptError("Per-cell results are incomplete; the significance map is not finalised.")
    years_axis = [int(y) for y in grid.years.reshape(len(grid.years) // 12, 12)[:, 0]]
    metadata = ran.regional_metadata(q, loaded, None)  # type: ignore[arg-type]
    cs = sta.CellTrendSet(all_cells, {}, years_axis, metadata, list(grid.warnings), complete_all)
    spatial = sta.spatial_response_from_set(var.name, cs, sta.regional_aggregate_from(regional), s, job.method, job.correction, job.alpha)

    # 10 ── publish ──────────────────────────────────────────────────────────
    ctx.set_stage(Stage.GENERATING_RESULTS, "Writing, verifying and publishing result files")
    ctx.check()   # last cancellation point: publication itself is never interrupted
    exec_meta = _execution_meta(job)
    regional = {**regional, "metadata": {**regional["metadata"], **exec_meta}}
    spatial = {**spatial, "metadata": {**spatial["metadata"], **exec_meta}}
    cellset = {"cells": all_cells, "years": years_axis, "metadata": {**metadata, **exec_meta}, "warnings": list(grid.warnings),
               "complete_records": complete_all, "detail_index": detail_index, "n_chunks": len(chunks)}
    manifest_sha, total_bytes = publish_results(ctx, regional, cellset, spatial, chunks, loaded, q)
    ctx.metrics["total_seconds"] = round(time.monotonic() - t_start, 2)
    ctx.metrics["n_cells"] = n
    ctx.metrics["n_tiles"] = len(tiles)
    complete_job(ctx, manifest_sha, total_bytes)


def _ensure_manifest(ctx: JobContext, tiles: list[Tile], var, job: AnalysisJob) -> None:
    existing = {r.tile_key: r for r in ctx.tile_rows()}
    if existing:
        same = len(existing) == len(tiles) and all(
            t.key in existing and (existing[t.key].lat_min, existing[t.key].lat_max, existing[t.key].lon_min, existing[t.key].lon_max)
            == (t.lat_min, t.lat_max, t.lon_min, t.lon_max) for t in tiles)
        if not same:
            raise InputChangedError("The NASA request plan differs from the stored manifest (software or boundary change); "
                                    "checkpoints are not mixed. Please start a new analysis.")
        return
    now = utcnow()

    def op() -> None:
        with ctx.sm() as s:
            for t in tiles:
                s.add(JobTile(job_id=job.id, tile_key=t.key, lat_min=t.lat_min, lat_max=t.lat_max, lon_min=t.lon_min,
                              lon_max=t.lon_max, n_needed=t.n_needed, status=TileStatus.PENDING, attempts=0,
                              request_hash=tile_request_hash(var, t, job.start_year, job.end_year, ctx.settings),
                              from_cache=False, updated_at=now))
            s.commit()
    with_db_retry(op)
    ctx.event("info", f"Tile manifest stored: {len(tiles)} NASA POWER regional requests.", Stage.PREPARING_NASA_REQUESTS)


# --------------------------------------------------------------------------- #
# Publication
# --------------------------------------------------------------------------- #

def _csv(rows: list[dict[str, Any]], fields: list[str], header_lines: list[str]) -> bytes:
    buf = io.StringIO()
    for line in header_lines:
        buf.write(f"# {line}\n")
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    return buf.getvalue().encode("utf-8")


def verify_published(store: ArtifactStore, result_rel: str, manifest_sha: str | None = None) -> dict[str, Any] | None:
    try:
        raw = store.read_bytes(f"{result_rel}/manifest.json", manifest_sha)
        manifest = json.loads(raw)
        for name, f in manifest["files"].items():
            store.read_bytes(f"{result_rel}/{name}", f["sha256"])
        manifest["_sha256"] = sha256_bytes(raw)
        return manifest
    except (ArtifactError, ValueError, KeyError):
        return None


def publish_results(ctx: JobContext, regional: dict, cellset: dict, spatial: dict, chunks: list[tuple[int, int]],
                    loaded: ran.LoadedGrid, q: ran.RegionalQuery) -> tuple[str, int]:
    store, job = ctx.store, ctx.job
    prefix = store.job_prefix(job.id)
    final = f"{prefix}/result"
    if store.exists(final):
        m = verify_published(store, final)
        if m is not None and m.get("config_hash") == job.config_hash:
            ctx.event("info", "Results had already been published by an earlier attempt; they were verified and reused.")
            return m["_sha256"], int(m.get("total_bytes", 0))
        aside = f"{prefix}/rejected-{int(time.time())}"
        store.path(final).rename(store.path(aside))
        ctx.event("warn", "An earlier, unverifiable result directory was set aside and the results are written again.")
    staging = f"{prefix}/staging-{uuid.uuid4().hex[:8]}"
    files: dict[str, dict[str, Any]] = {}

    def put(name: str, data: bytes, ctype: str) -> None:
        sha, size = store.write_bytes(f"{staging}/{name}", data)
        files[name] = {"sha256": sha, "bytes": size, "content_type": ctype}

    put("regional.json.gz", gz(dumps(regional)), "application/json+gzip")
    put("cells.json.gz", gz(dumps(cellset)), "application/json+gzip")
    put("spatial_default.json.gz", gz(dumps(spatial)), "application/json+gzip")
    for k, _ in enumerate(chunks):
        c = ctx.checkpoints[f"chunk:{k}"]
        part = store.read_json_gz(c["ref"], c["sha256"])
        put(f"details/chunk-{k:05d}.json.gz", gz(dumps(part["details"])), "application/json+gzip")
        del part
    m = regional["metadata"]
    label = "LIVE NASA POWER DATA"
    head = [label, f"{m['variable_name']} ({m['parameter']}, {m['unit_display']}) · {m['area_name']} · {m['start_year']}–{m['end_year']}",
            f"Earth Scope background job {job.id} · {ANALYSIS_ENGINE_VERSION}"]
    put("exports/monthly.csv", _csv(regional["monthly"], ["date", "year", "month", "value", "status", "computed_mean", "spatial_sd",
                                                           "min_value", "max_value", "valid_cells", "missing_cells", "valid_area_km2", "coverage"], head), "text/csv")
    put("exports/annual.csv", _csv(regional["annual"], ["year", "value", "valid_months", "total_months", "status", "used_in_trend", "spatial_sd"], head), "text/csv")
    cfg = spatial["config"]
    put("exports/spatial_cells.csv", _csv(spatial["cells"], [
        "id", "latitude", "longitude", "overlap_area_km2", "weight", "data_status", "availability", "valid_years", "period_mean",
        "ols_slope", "ols_p_value", "sen_slope", "sen_ci_lower", "sen_ci_upper", "mk_tau", "mk_p_value", "hr_canonical_p_value",
        "hr_conservative_p_value", "yw_canonical_p_value", "hac_p_value", "lag1_autocorrelation", "raw_p_value", "adjusted_p_value",
        "in_family", "status"], head + [f"Significance: {cfg['method_label']}, {cfg['correction_label']}, alpha={cfg['alpha']}, "
                                        f"family of {cfg['n_hypotheses']} cells (complete area)"]), "text/csv")
    provenance = strict_json({
        "job_id": job.id, "config": job.config, "config_hash": job.config_hash, "software_version": ANALYSIS_ENGINE_VERSION,
        "data_mode": m["data_mode"], "provider": m["provider"], "parameter": m["parameter"], "community": m["community"],
        "units": m["units_raw"], "sources": m["sources"], "api_version": m["api_version"], "grid": m["grid_resolution"],
        "boundary": m.get("boundary"), "geometry_id": m.get("geometry_id"), "n_cells_used": m["n_cells_used"],
        "n_tiles": m.get("n_tiles"), "request_manifest": m.get("request_manifest"), "aggregation_method": m["aggregation_method"],
        "missing_data": "NASA fill values and physically impossible values are missing (never zero, never interpolated); a month "
                        f"counts only if valid cells cover ≥ {q.coverage_threshold:.0%} of the area; a year needs ≥ "
                        f"{ctx.settings.min_valid_months_per_year} valid months.",
        "statistics": job.config.get("statistics"),
        "fdr": {"method": cfg["correction"], "alpha": cfg["alpha"], "n_hypotheses": cfg["n_hypotheses"],
                "family": "every analysed cell of the complete area with a valid p-value for the chosen test"},
        "retrieved_at": m["retrieved_at"], "published_at": m.get("published_at"),
    })
    put("exports/provenance.json", json.dumps(provenance, indent=2).encode(), "application/json")

    total = sum(f["bytes"] for f in files.values())
    tile_bytes = sum(r.blob_bytes or 0 for r in ctx.tile_rows())
    if (total + tile_bytes) / 1e6 > ctx.settings.job_max_storage_mb:
        store.remove_tree(staging)
        raise StorageBudgetError(f"The results need {(total + tile_bytes) / 1e6:.0f} MB; the per-job storage limit is "
                                 f"{ctx.settings.job_max_storage_mb} MB.")
    manifest = {"job_id": job.id, "config_hash": job.config_hash, "software_version": ANALYSIS_ENGINE_VERSION,
                "data_mode": m["data_mode"], "created_at": _iso_now(), "files": files, "total_bytes": total,
                "complete": True}
    raw = json.dumps(manifest, indent=2, sort_keys=True).encode()
    store.write_bytes(f"{staging}/manifest.json", raw)
    if verify_published(store, staging, sha256_bytes(raw)) is None:
        store.remove_tree(staging)
        raise ArtifactCorruptError("Result files failed verification after writing; nothing was published.")
    store.publish_dir(staging, final)
    logger.info("job=%s published %d files (%.1f MB)", job.id, len(files) + 1, total / 1e6)
    return sha256_bytes(raw), total


def complete_job(ctx: JobContext, manifest_sha: str, total_bytes: int) -> None:
    now = utcnow()
    try:
        ctx._write({"status": JobStatus.COMPLETED, "stage": Stage.COMPLETED, "activity": "Results are ready",
                    "progress_pct": 100.0, "completed_at": now, "result_ref": f"{ctx.store.job_prefix(ctx.job_id)}/result",
                    "result_sha256": manifest_sha, "result_bytes": total_bytes, "active_dedupe_key": None,
                    "lease_owner": None, "lease_expires_at": None, "metrics": ctx.metrics,
                    "expires_at": now + timedelta(days=ctx.settings.job_result_retention_days)},
                   statuses=(JobStatus.RUNNING,))
    except LeaseLost:
        status = _status(ctx)
        if status == JobStatus.CANCEL_REQUESTED:
            raise JobCancelled() from None
        raise
    ctx.event("info", "Results verified and published; the analysis is complete.", Stage.COMPLETED)
    ctx.store.remove_tree(f"{ctx.store.job_prefix(ctx.job_id)}/work")   # tiles stay in the shared cache


def _status(ctx: JobContext) -> str | None:
    with ctx.sm() as s:
        return s.scalar(select(AnalysisJob.status).where(AnalysisJob.id == ctx.job_id))


def finish_cancelled(ctx: JobContext) -> None:
    now = utcnow()
    try:
        ctx._write({"status": JobStatus.CANCELLED, "activity": "Cancelled by the user", "active_dedupe_key": None,
                    "lease_owner": None, "lease_expires_at": None, "metrics": ctx.metrics,
                    "expires_at": now + timedelta(days=ctx.settings.job_failed_retention_days)})
    except LeaseLost:
        return
    prefix = ctx.store.job_prefix(ctx.job_id)
    ctx.store.remove_tree(f"{prefix}/result")
    for p in ctx.store.path(prefix).glob("staging-*"):
        ctx.store.remove_tree(f"{prefix}/{p.name}")
    # Work checkpoints are kept until expiry so "Retry" can resume; shared NASA tiles are never deleted here.
    ctx.event("info", "The analysis was cancelled at a safe checkpoint. Verified NASA tiles are kept for a possible retry.")


def fail_job(ctx: JobContext, code: str, message: str, retryable: bool, details: list[str] | None = None,
             automatic: bool = True) -> str:
    """Record a failure: automatic RETRYING while attempts remain, otherwise FAILED (checkpoints kept)."""
    s = ctx.settings
    now = utcnow()
    with ctx.sm() as sess:
        job = sess.get(AnalysisJob, ctx.job_id)
        auto = job.auto_attempts if job else s.job_max_attempts
    retryable = retryable and code not in INPUT_ERROR_CODES
    if retryable and automatic and auto < s.job_max_attempts:
        delay = min(900.0, s.job_retry_backoff_seconds * (2 ** max(0, auto - 1)))
        values = {"status": JobStatus.RETRYING, "next_attempt_at": now + timedelta(seconds=delay), "lease_owner": None,
                  "lease_expires_at": None, "error_code": code, "error_message": message, "error_retryable": True,
                  "activity": f"Temporary problem ({code}); retrying automatically in {delay:.0f} s", "metrics": ctx.metrics}
        new_status = JobStatus.RETRYING
    else:
        values = {"status": JobStatus.FAILED, "lease_owner": None, "lease_expires_at": None, "error_code": code,
                  "error_message": message, "error_retryable": retryable, "active_dedupe_key": None, "metrics": ctx.metrics,
                  "activity": "Failed" + (" — verified checkpoints are kept for Retry" if retryable else ""),
                  "expires_at": now + timedelta(days=s.job_failed_retention_days)}
        new_status = JobStatus.FAILED
    try:
        ctx._write(values, statuses=(JobStatus.RUNNING,))
    except LeaseLost:
        if _status(ctx) == JobStatus.CANCEL_REQUESTED:
            finish_cancelled(ctx)
        return "lease_lost"
    ctx.event("error" if new_status == JobStatus.FAILED else "warn",
              f"{'Failed' if new_status == JobStatus.FAILED else 'Will retry automatically'}: {message}", ctx.current_stage,
              {"code": code, "details": (details or [])[:5]})
    logger.warning("job=%s %s code=%s attempt=%s", ctx.job_id, new_status, code, auto)
    return new_status.lower()


def execute(job_id: str, worker_id: str, settings: Settings, sm: sessionmaker[Session], store: ArtifactStore,
            limiter_factory: Callable[[], GlobalNasaLimiter | None], client_factory: Callable[[], NasaPowerClient]) -> str:
    """Claim and run one job. Returns a short outcome string (also the RQ result)."""
    if not claim(sm, job_id, worker_id, settings):
        logger.info("job=%s not claimable by %s (already running, finished or cancelled)", job_id, worker_id)
        return "not_claimable"
    try:
        limiter = limiter_factory()
        client = client_factory()
    except Exception as exc:  # noqa: BLE001
        ctx = JobContext(job_id, worker_id, settings, sm, store, None)
        return fail_job(ctx, "INFRASTRUCTURE_UNAVAILABLE", "The request coordinator (Redis) is unavailable.", True, [type(exc).__name__])
    ctx = JobContext(job_id, worker_id, settings, sm, store, limiter, client)
    hb = Heartbeat(ctx)
    hb.start()
    try:
        run_pipeline(ctx)
        return "completed"
    except JobCancelled:
        finish_cancelled(ctx)
        return "cancelled"
    except LeaseLost:
        logger.warning("job=%s lease lost by %s; stopping without further writes", job_id, worker_id)
        return "lease_lost"
    except EarthScopeError as exc:
        return fail_job(ctx, exc.error, exc.message, exc.retryable, exc.details)
    except redis.RedisError as exc:
        return fail_job(ctx, "INFRASTRUCTURE_UNAVAILABLE", "The request coordinator (Redis) was temporarily unavailable.", True,
                        [type(exc).__name__])
    except OSError as exc:
        return fail_job(ctx, "ARTIFACT_STORAGE_ERROR", "Durable storage was temporarily unavailable.", True, [type(exc).__name__])
    except Exception as exc:  # noqa: BLE001
        from app.jobs.db import is_transient_db_error

        if is_transient_db_error(exc):
            try:
                return fail_job(ctx, "INFRASTRUCTURE_UNAVAILABLE", "The job database was temporarily unavailable.", True)
            except Exception:  # noqa: BLE001 - DB still down: the lease expires and the reconciler recovers the job
                return "db_unavailable"
        logger.exception("job=%s unexpected error", job_id)
        return fail_job(ctx, "INTERNAL_ERROR", "An unexpected processing error occurred. Verified checkpoints are kept.", True,
                        automatic=False)
    finally:
        hb.stop()
