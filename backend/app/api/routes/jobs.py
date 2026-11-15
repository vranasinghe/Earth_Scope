"""Background analysis jobs: preflight, submission, status, results, cancel, retry.

Every job endpoint requires the anonymous session cookie of the browser that
submitted the job; state-changing endpoints also require the CSRF header.
Results use the same response models as the synchronous country / polygon
endpoints, so the existing dashboards render them unchanged.
"""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SettingsDep
from app.api.routes.areas import BodyLimit, _describe
from app.jobs import results as jr
from app.jobs import service as js
from app.jobs.artifacts import get_store
from app.jobs.db import get_sessionmaker
from app.jobs.models import AnalysisJob, JobStatus, JobTile
from app.jobs.security import client_ip, ensure_session, ip_hash, require_csrf, require_owner
from app.models.job_schemas import (
    ArtifactListResponse,
    JobCreateRequest,
    JobListResponse,
    JobPreflightResponse,
    JobProgress,
    JobResponse,
    JobSubmitResponse,
    RetryResponse,
    SessionResponse,
)
from app.models.area_schemas import AreaSpatialRequest
from app.models.regional_schemas import RegionalAnalysisResponse
from app.models.schemas import ErrorResponse
from app.models.spatial_trend_schemas import SpatialCellDetailResponse, SpatialTrendResponse
from app.utils.errors import EarthScopeError, InvalidRequestError

router = APIRouter(prefix="/analysis", tags=["background analysis jobs"])
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 410, 422, 429, 503)}


def get_db() -> Iterator[Session]:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


DbDep = Annotated[Session, Depends(get_db)]


def _owner(request: Request, settings: SettingsDep) -> str:
    return require_owner(request, settings)


def _csrf(request: Request, settings: SettingsDep) -> None:
    require_csrf(request, settings)


OwnerDep = Annotated[str, Depends(_owner)]
CsrfDep = Annotated[None, Depends(_csrf)]


def _job_request(req: AreaSpatialRequest) -> js.JobRequest:
    return js.JobRequest(req.iso3, req.geometry, req.name, req.variable, req.start_year, req.end_year, req.coverage_threshold,
                         req.method, req.correction, req.alpha)


def _job_out(db: Session, job: AnalysisJob, settings, with_events: bool = True) -> dict:
    return js.job_dict(job, settings, js.recent_events(db, job.id) if with_events else None)


# --------------------------------------------------------------------------- #

@router.get("/session", response_model=SessionResponse, summary="Start or resume this browser's anonymous analysis session")
def session(request: Request, response: Response, settings: SettingsDep) -> SessionResponse:
    _, csrf = ensure_session(request, response, settings)
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(active=True, csrf_token=csrf)


@router.post("/preflight", response_model=JobPreflightResponse, responses=ERRORS,
             summary="Cells, NASA requests, resource tier, estimates and eligibility — no NASA call")
def preflight(settings: SettingsDep, db: DbDep, req: AreaSpatialRequest, _: BodyLimit) -> dict:
    plan = js.build_plan(_job_request(req), settings, db)
    return {"area": _describe(plan.area), **js.preflight_payload(plan, settings)}


@router.post("/jobs", response_model=JobSubmitResponse, status_code=202, responses=ERRORS,
             summary="Submit a background country / polygon analysis (returns immediately)")
def create_job(request: Request, response: Response, settings: SettingsDep, db: DbDep, owner: OwnerDep, _c: CsrfDep,
               req: JobCreateRequest, _: BodyLimit,
               idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None) -> dict:
    if idempotency_key is not None and not idempotency_key.strip():
        raise InvalidRequestError("Idempotency-Key must not be empty.")
    plan = js.build_plan(_job_request(req), settings, db)
    job, created, reason = js.submit(db, plan, owner, ip_hash(client_ip(request)), idempotency_key, req.force_new, settings, get_store())
    if not created:
        response.status_code = 200
    out = _job_out(db, job, settings)
    return {"job_id": job.id, "status": job.status, "created": created, "duplicate_of_reason": reason,
            "status_url": out["links"]["self"], "created_at": out["created_at"], "accepted_configuration": job.config, "job": out}


@router.get("/jobs", response_model=JobListResponse, responses=ERRORS, summary="This session's jobs (newest first)")
def list_jobs(settings: SettingsDep, db: DbDep, owner: OwnerDep, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict:
    return {"jobs": [_job_out(db, j, settings, with_events=False) for j in js.list_owned(db, owner, limit)]}


@router.get("/jobs/{job_id}", response_model=JobResponse, responses=ERRORS, summary="Job status, configuration and history")
def get_job(job_id: str, settings: SettingsDep, db: DbDep, owner: OwnerDep, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return _job_out(db, js.get_owned(db, job_id, owner), settings)


@router.get("/jobs/{job_id}/progress", response_model=JobProgress, responses=ERRORS, summary="Lightweight progress for polling")
def get_progress(job_id: str, db: DbDep, owner: OwnerDep, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return js.progress_dict(js.get_owned(db, job_id, owner))


def _completed(db: Session, job_id: str, owner: str) -> AnalysisJob:
    job = js.get_owned(db, job_id, owner)
    if job.status == JobStatus.EXPIRED:
        raise js.JobExpiredError("The results of this job were deleted after the retention period. Please run the analysis again.")
    if job.status != JobStatus.COMPLETED:
        raise js.JobNotReadyError(f"The results are not ready yet (job status: {job.status}).",
                                  [f"Current stage: {job.stage}."] if job.status in JobStatus.ACTIVE else
                                  ([f"{job.error_code}: {job.error_message}"] if job.error_code else []))
    return job


@router.get("/jobs/{job_id}/results", response_model=RegionalAnalysisResponse, responses=ERRORS,
            summary="Completed result in the standard country / polygon analysis schema")
def get_results(job_id: str, db: DbDep, owner: OwnerDep) -> dict:
    return jr.regional(get_store(), _completed(db, job_id, owner))


@router.get("/jobs/{job_id}/spatial", response_model=SpatialTrendResponse, responses=ERRORS,
            summary="Spatial trend map; FDR always over the complete cell family (viewport only filters returned cells)")
def get_spatial(job_id: str, settings: SettingsDep, db: DbDep, owner: OwnerDep,
                method: str = "mann_kendall", correction: str = "fdr_bh", alpha: float = 0.05,
                lat_min: float | None = None, lat_max: float | None = None, lon_min: float | None = None, lon_max: float | None = None) -> dict:
    vals = (lat_min, lat_max, lon_min, lon_max)
    if any(v is not None for v in vals) and not all(v is not None for v in vals):
        raise InvalidRequestError("A viewport needs all four of lat_min, lat_max, lon_min and lon_max.")
    bbox = vals if all(v is not None for v in vals) else None
    return jr.spatial(get_store(), _completed(db, job_id, owner), settings, method, correction, alpha, bbox)  # type: ignore[arg-type]


@router.get("/jobs/{job_id}/spatial/cell", response_model=SpatialCellDetailResponse, responses=ERRORS,
            summary="Full statistics and annual series of one cell of a completed job")
def get_spatial_cell(job_id: str, settings: SettingsDep, db: DbDep, owner: OwnerDep, cell_id: str,
                     method: str = "mann_kendall", correction: str = "fdr_bh", alpha: float = 0.05) -> dict:
    return jr.cell_detail(get_store(), _completed(db, job_id, owner), settings, cell_id, method, correction, alpha)


@router.get("/jobs/{job_id}/artifacts", response_model=ArtifactListResponse, responses=ERRORS, summary="Published result files")
def list_artifacts(job_id: str, db: DbDep, owner: OwnerDep) -> dict:
    job = _completed(db, job_id, owner)
    return {"job_id": job.id, "manifest_sha256": job.result_sha256, "files": jr.artifact_list(get_store(), job)}


@router.get("/jobs/{job_id}/artifacts/{name:path}", responses=ERRORS, summary="Download one published export file")
def download_artifact(job_id: str, name: str, db: DbDep, owner: OwnerDep) -> Response:
    job = _completed(db, job_id, owner)
    files = {f["name"]: f for f in jr.artifact_list(get_store(), job)}
    if name not in files or not files[name]["downloadable"]:
        raise js.JobNotFoundError("No downloadable result file with this name.")
    data, ctype = jr.artifact_bytes(get_store(), job, name)
    fname = f"earthscope-{job.id[:8]}-{name.replace('/', '-')}"
    media = "application/gzip" if name.endswith(".gz") else ctype
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{fname}"',
                                                             "Cache-Control": "private, no-store"})


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, responses=ERRORS, summary="Cancel a queued or running job")
def cancel_job(job_id: str, settings: SettingsDep, db: DbDep, owner: OwnerDep, _c: CsrfDep) -> dict:
    job = js.cancel(db, js.get_owned(db, job_id, owner))
    try:   # best effort: drop the queued RQ message too (claim would refuse it anyway)
        if job.rq_job_id and job.status == JobStatus.CANCELLED:
            from rq.job import Job

            from app.jobs.queue import get_redis

            Job.fetch(job.rq_job_id, connection=get_redis()).cancel()
    except Exception:  # noqa: BLE001
        pass
    return _job_out(db, job, settings)


@router.post("/jobs/{job_id}/retry", response_model=RetryResponse, responses=ERRORS,
             summary="Retry a failed / cancelled job from its verified checkpoints")
def retry_job(job_id: str, settings: SettingsDep, db: DbDep, owner: OwnerDep, _c: CsrfDep) -> dict:
    job = js.retry(db, js.get_owned(db, job_id, owner), settings, get_store())
    return {"job": _job_out(db, job, settings), "resumable": js.resumable_summary(db, job)}


# --------------------------------------------------------------------------- #
# Health and operations
# --------------------------------------------------------------------------- #

@router.get("/health", summary="Job system availability (database, queue, workers) — no internal details")
def jobs_health(db: DbDep) -> dict:
    from app.jobs.queue import queue_health

    try:
        db.execute(select(1))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    q = queue_health()
    ok = db_ok and q["redis"] and q["workers"] > 0
    return {"status": "ok" if ok else "degraded", "database": db_ok, "queue": q["redis"], "workers_available": q["workers"] > 0,
            "accepting_jobs": db_ok}


class OpsTokenError(EarthScopeError):
    status_code = 403
    error = "FORBIDDEN"


@router.get("/ops", summary="Internal operational summary (requires X-Ops-Token; disabled when no token is configured)")
def ops(settings: SettingsDep, db: DbDep, x_ops_token: Annotated[str | None, Header()] = None) -> dict:
    import hmac

    from app.jobs.models import utcnow
    from app.jobs.queue import queue_health

    if not settings.ops_token or not x_ops_token or not hmac.compare_digest(settings.ops_token, x_ops_token):
        raise OpsTokenError("Operational information requires a valid operator token.")
    counts = dict(db.execute(select(AnalysisJob.status, func.count()).group_by(AnalysisJob.status)).all())
    durations = [m.get("total_seconds") for m in db.scalars(select(AnalysisJob.metrics).where(
        AnalysisJob.status == JobStatus.COMPLETED).order_by(AnalysisJob.completed_at.desc()).limit(100)) if m and m.get("total_seconds")]
    from datetime import timedelta

    tile_failures = db.scalar(select(func.count()).select_from(JobTile).where(
        JobTile.last_error_code.is_not(None), JobTile.updated_at >= utcnow() - timedelta(days=1)))
    q = queue_health()
    return {"jobs_by_status": counts, "queued": counts.get("QUEUED", 0) + counts.get("PENDING", 0),
            "active": sum(counts.get(s, 0) for s in (JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)),
            "failed": counts.get("FAILED", 0),
            "average_completed_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "nasa_tile_errors_24h": tile_failures, "workers": q.get("workers"), "rq_queue_length": q.get("queued"),
            "nasa_global_max_concurrency": settings.nasa_global_max_concurrency}
