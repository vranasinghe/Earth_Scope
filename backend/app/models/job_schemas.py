"""Pydantic models for background analysis jobs (/api/analysis/...)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.area_schemas import AreaDescription, AreaSpatialRequest, Preflight

JobStatusName = Literal["PENDING", "QUEUED", "RUNNING", "RETRYING", "CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED", "EXPIRED"]


class JobCreateRequest(AreaSpatialRequest):
    """Country (iso3) or polygon (geometry), variable, period, statistics and data mode."""

    force_new: bool = Field(False, description="Start a new run even if an identical completed job of this session exists")


class SessionResponse(BaseModel):
    active: bool
    csrf_token: str
    csrf_header: str = "X-CSRF-Token"


class BackgroundEstimate(BaseModel):
    basis: str
    download_seconds: float
    processing_seconds: float
    total_seconds: float
    memory_mb: float
    storage_mb: float
    note: str


class StageInfo(BaseModel):
    id: str
    label: str
    description: str | None = None
    state: str | None = None


class BackgroundPreflight(BaseModel):
    tier: Literal["SMALL", "MEDIUM", "LARGE", "VERY_LARGE", "BLOCKED"]
    eligible: bool
    synchronous_available: bool
    reasons: list[str]
    estimates: BackgroundEstimate | None = None
    stages: list[StageInfo] = []
    limits: dict[str, Any] = {}
    config_hash: str | None = None


class JobPreflightResponse(BaseModel):
    area: AreaDescription
    preflight: Preflight
    background: BackgroundPreflight
    variable: str
    start_year: int
    end_year: int
    data_mode: Literal["LIVE"]


class JobProgress(BaseModel):
    job_id: str
    status: JobStatusName
    stage: str
    stage_label: str
    activity: str | None
    progress_pct: float = Field(..., description="Weighted by documented stage weights from real work counters; 100 only when results are published")
    is_active: bool
    download: dict[str, int]
    processing: dict[str, int]
    attempts: dict[str, int | None]
    updated_at: str | None
    heartbeat_at: str | None
    stages: list[StageInfo]


class JobError(BaseModel):
    code: str
    message: str | None
    retryable: bool


class JobEventOut(BaseModel):
    at: str | None
    level: str
    stage: str | None
    message: str


class JobAreaInfo(BaseModel):
    kind: str
    name: str
    iso3: str | None
    geometry_id: str
    boundary_source: str | None
    boundary_version: str | None


class JobResponse(BaseModel):
    job_id: str
    job_type: str
    status: JobStatusName
    tier: str
    data_mode: Literal["LIVE"]
    area: JobAreaInfo
    variable_id: str
    parameter: str
    community: str
    start_year: int
    end_year: int
    config: dict[str, Any]
    config_hash: str
    preflight: dict[str, Any]
    progress: JobProgress
    error: JobError | None
    created_at: str | None
    queued_at: str | None
    started_at: str | None
    updated_at: str | None
    completed_at: str | None
    expires_at: str | None
    software_version: str
    dataset_version: str
    can_cancel: bool
    can_retry: bool
    has_results: bool
    links: dict[str, str]
    events: list[JobEventOut] = []


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatusName
    created: bool = Field(..., description="False when an existing job was returned instead of starting a duplicate")
    duplicate_of_reason: Literal["idempotency_key", "active_duplicate", "completed_duplicate"] | None = None
    status_url: str
    created_at: str | None
    accepted_configuration: dict[str, Any]
    job: JobResponse


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class ArtifactInfo(BaseModel):
    name: str
    bytes: int
    sha256: str
    content_type: str
    downloadable: bool


class ArtifactListResponse(BaseModel):
    job_id: str
    manifest_sha256: str
    files: list[ArtifactInfo]


class RetryResponse(BaseModel):
    job: JobResponse
    resumable: dict[str, Any]
