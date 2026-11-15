"""SQLAlchemy models for durable analysis jobs.

The database is the authoritative source of job state. RQ only carries "run job
X" messages; a lost or duplicated message cannot change a job's outcome because
every state transition is a compare-and-set UPDATE on these rows.

Large data (tile payloads, grids, per-cell results) never goes into PostgreSQL:
rows hold references and SHA-256 checksums of artifacts on durable storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; every stored value is UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class JobStatus:
    PENDING = "PENDING"                    # recorded, not yet handed to the queue (outbox)
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"                  # waiting for an automatic retry (transient failure / lost worker)
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

    ACTIVE = (PENDING, QUEUED, RUNNING, RETRYING, CANCEL_REQUESTED)
    TERMINAL = (CANCELLED, COMPLETED, FAILED, EXPIRED)
    CLAIMABLE = (PENDING, QUEUED, RETRYING)


class Stage:
    QUEUED = "QUEUED"
    PREPARING_GEOMETRY = "PREPARING_GEOMETRY"
    CALCULATING_POLYGON_WEIGHTS = "CALCULATING_POLYGON_WEIGHTS"
    PREPARING_NASA_REQUESTS = "PREPARING_NASA_REQUESTS"
    DOWNLOADING_NASA_DATA = "DOWNLOADING_NASA_DATA"
    VALIDATING_DATA = "VALIDATING_DATA"
    MERGING_GRID_CELLS = "MERGING_GRID_CELLS"
    BUILDING_TIME_SERIES = "BUILDING_TIME_SERIES"
    RUNNING_STATISTICS = "RUNNING_STATISTICS"
    CALCULATING_SPATIAL_FDR = "CALCULATING_SPATIAL_FDR"
    GENERATING_RESULTS = "GENERATING_RESULTS"
    COMPLETED = "COMPLETED"

    # Processing order and the share of the overall progress bar each stage represents.
    # Downloads and per-cell statistics dominate measured run time.
    ORDER: tuple[tuple[str, float], ...] = (
        (PREPARING_GEOMETRY, 2.0),
        (CALCULATING_POLYGON_WEIGHTS, 6.0),
        (PREPARING_NASA_REQUESTS, 1.0),
        (DOWNLOADING_NASA_DATA, 45.0),
        (VALIDATING_DATA, 1.0),
        (MERGING_GRID_CELLS, 5.0),
        (BUILDING_TIME_SERIES, 4.0),
        (RUNNING_STATISTICS, 30.0),
        (CALCULATING_SPATIAL_FDR, 2.0),
        (GENERATING_RESULTS, 4.0),
    )
    LABELS = {
        QUEUED: "Queued",
        PREPARING_GEOMETRY: "Preparing geometry",
        CALCULATING_POLYGON_WEIGHTS: "Calculating polygon weights",
        PREPARING_NASA_REQUESTS: "Preparing NASA requests",
        DOWNLOADING_NASA_DATA: "Downloading NASA data",
        VALIDATING_DATA: "Validating data",
        MERGING_GRID_CELLS: "Merging grid cells",
        BUILDING_TIME_SERIES: "Building time series",
        RUNNING_STATISTICS: "Running statistics",
        CALCULATING_SPATIAL_FDR: "Calculating spatial FDR",
        GENERATING_RESULTS: "Generating results",
        COMPLETED: "Completed",
    }


class TileStatus:
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    RETRYING = "RETRYING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    client_ip_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    job_type: Mapped[str] = mapped_column(String(32), default="area_analysis")

    # --- What is analysed (the polygon itself lives in the input artifact, never in a public field) ---
    area_kind: Mapped[str] = mapped_column(String(16))           # country | polygon
    area_name: Mapped[str] = mapped_column(String(120))
    iso3: Mapped[str | None] = mapped_column(String(3))
    geometry_id: Mapped[str] = mapped_column(String(64))
    boundary_source: Mapped[str | None] = mapped_column(String(64))
    boundary_version: Mapped[str | None] = mapped_column(String(128))
    variable_id: Mapped[str] = mapped_column(String(64))
    parameter: Mapped[str] = mapped_column(String(32))
    community: Mapped[str] = mapped_column(String(8))
    start_year: Mapped[int] = mapped_column(Integer)
    end_year: Mapped[int] = mapped_column(Integer)
    coverage_threshold: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(40))
    correction: Mapped[str] = mapped_column(String(16))
    alpha: Mapped[float] = mapped_column(Float)
    data_mode: Mapped[str] = mapped_column(String(8))           # always LIVE
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)    # accepted configuration (no polygon coordinates)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Equals config_hash while the job is active, NULL otherwise: a unique index on
    # (owner_hash, active_dedupe_key) makes a double-click unable to start two runs.
    active_dedupe_key: Mapped[str | None] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16))
    preflight: Mapped[dict[str, Any]] = mapped_column(JSONType)
    input_ref: Mapped[str] = mapped_column(String(255))
    input_sha256: Mapped[str] = mapped_column(String(64))
    software_version: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(128))

    # --- Lifecycle ---
    status: Mapped[str] = mapped_column(String(24), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    activity: Mapped[str | None] = mapped_column(String(300))
    tiles_total: Mapped[int] = mapped_column(Integer, default=0)
    tiles_completed: Mapped[int] = mapped_column(Integer, default=0)
    tiles_retrying: Mapped[int] = mapped_column(Integer, default=0)
    tiles_failed: Mapped[int] = mapped_column(Integer, default=0)
    cells_total: Mapped[int] = mapped_column(Integer, default=0)
    cells_processed: Mapped[int] = mapped_column(Integer, default=0)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)      # every worker start, ever
    auto_attempts: Mapped[int] = mapped_column(Integer, default=0)      # starts since submission / last manual retry
    manual_retries: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(80))

    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_retryable: Mapped[bool | None] = mapped_column(Boolean)

    checkpoints: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)   # stage -> {ref, sha256, bytes}
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)       # measured stage durations etc.
    result_ref: Mapped[str | None] = mapped_column(String(255))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    result_bytes: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("owner_hash", "active_dedupe_key", name="uq_jobs_owner_active_config"),
        UniqueConstraint("owner_hash", "idempotency_key", name="uq_jobs_owner_idempotency_key"),
        Index("ix_jobs_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_jobs_owner_created", "owner_hash", "created_at"),
    )


class JobTile(Base):
    """One NASA POWER regional request of a job's tile manifest, with its checkpoint."""

    __tablename__ = "job_tiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    tile_key: Mapped[str] = mapped_column(String(16))
    lat_min: Mapped[float] = mapped_column(Float)
    lat_max: Mapped[float] = mapped_column(Float)
    lon_min: Mapped[float] = mapped_column(Float)
    lon_max: Mapped[float] = mapped_column(Float)
    n_needed: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(48))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blob_sha256: Mapped[str | None] = mapped_column(String(64))
    blob_bytes: Mapped[int | None] = mapped_column(Integer)
    request_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[str | None] = mapped_column(String(40))
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    n_features: Mapped[int | None] = mapped_column(Integer)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("job_id", "tile_key", name="uq_job_tiles_job_tile"),)


class JobEvent(Base):
    """Append-only, sanitised audit trail (retries, failures, recoveries) shown on the job page."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(String(8))
    stage: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
