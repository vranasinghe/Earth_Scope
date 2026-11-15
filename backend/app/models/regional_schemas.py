"""Pydantic response models for regional (bounding-box) analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.schemas import DataMode, Interpretation, StatisticsResult, VariableInfo

RegionalMonthlyStatus = Literal["valid", "insufficient_coverage", "missing"]
CellStatus = Literal["valid", "partial", "missing", "excluded"]


class BBoxModel(BaseModel):
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class BoundaryInfo(BaseModel):
    source: str
    dataset: str
    version: str
    boundary_id: str
    year_represented: str | None = None
    license: str | None = None
    license_source: str | None = None
    upstream_source: str | None = None
    build_date: str | None = None
    attribution: str
    status: str | None = None
    reported_area_km2: float | None = None
    geometry_url: str | None = None


class TileRequest(BaseModel):
    tile: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    url: str | None
    retrieved_at: str
    from_cache: bool
    attempts: int
    cells_returned: int
    cells_used: int


class RegionalMetadata(BaseModel):
    data_mode: DataMode
    provider: str
    dataset_title: str | None
    api_version: str | None
    variable_id: str
    variable_name: str
    parameter: str
    long_name: str | None
    community: str
    sources: list[str]
    units_raw: str | None
    unit_display: str
    rate_unit: str
    temporal_resolution: Literal["monthly"] = "monthly"
    time_standard: str | None
    start_year: int
    end_year: int
    latest_complete_year: int | None
    bbox: BBoxModel = Field(..., description="Region requested by the user")
    request_bbox: BBoxModel = Field(..., description="Box sent to NASA (expanded by half a cell per side)")
    returned_extent: BBoxModel | None = Field(None, description="Extent of cell centres NASA returned")
    region_area_km2: float = Field(..., description="Exact spherical area of the user's box")
    analysed_area_km2: float = Field(..., description="Area used as the coverage denominator")
    land_fraction: float | None = Field(None, description="Ice-free land share of the box (land-only variables)")
    grid_resolution: str
    n_cells_returned: int
    n_cells_used: int
    n_cells_excluded: int
    n_cells_outside: int
    n_duplicates: int
    aggregation_method: str
    partial_cell_rule: str
    coverage_threshold: float
    fill_value: float | None
    retrieved_at: str
    served_from_cache: bool
    request_url: str | None
    documentation_url: str
    parameter_docs_url: str
    source_note: str
    # --- Country / custom polygon (absent or default for rectangles) ---
    area_mode: Literal["rectangle", "country", "polygon"] = "rectangle"
    area_name: str | None = None
    iso3: str | None = None
    geometry_id: str | None = Field(None, description="SHA-256 based id of the geometry used for the calculation")
    geometry: dict[str, Any] | None = Field(None, description="Display copy of the boundary (GeoJSON, lightly simplified)")
    boundary: BoundaryInfo | None = None
    geometry_notes: list[str] = []
    polygon_area_km2: float | None = None
    geodesic_area_km2: float | None = Field(None, description="WGS84 ellipsoidal area (pyproj) for reference")
    n_components: int | None = None
    n_vertices: int | None = None
    request_manifest: list[TileRequest] | None = None
    n_tiles: int | None = None
    n_cells_missing_from_response: int | None = None
    grid_representability: float | None = Field(None, description="Σ cell overlap areas / polygon area")
    # --- Execution pathway (Phase 6). Results are scientifically identical either way. ---
    execution_mode: Literal["synchronous", "background"] = "synchronous"
    job_id: str | None = Field(None, description="Background job that produced this result")
    analysis_software_version: str | None = None
    published_at: str | None = Field(None, description="When a background result was verified and published")


class RegionalMonthlyRecord(BaseModel):
    date: str
    year: int
    month: int
    value: float | None = Field(None, description="Regional mean, only when the month passes the coverage threshold")
    computed_mean: float | None = Field(None, description="Weighted mean of whatever cells were valid (for transparency)")
    status: RegionalMonthlyStatus
    spatial_sd: float | None = Field(None, description="Area-weighted SD across valid cells")
    min_value: float | None
    max_value: float | None
    valid_cells: int
    missing_cells: int
    valid_area_km2: float
    coverage: float = Field(..., description="Valid area / analysed area (0–1)")


class RegionalAnnualRecord(BaseModel):
    year: int
    value: float | None
    valid_months: int
    total_months: int = 12
    status: Literal["complete", "incomplete", "missing"]
    used_in_trend: bool
    spatial_sd: float | None = Field(None, description="Area-weighted SD across cells of their annual means")


class RegionalSummary(BaseModel):
    n_monthly_total: int
    n_monthly_valid: int
    n_monthly_missing: int
    n_monthly_insufficient: int
    n_annual_total: int
    n_annual_complete: int
    n_annual_used: int
    min_valid_months_per_year: int
    mean_coverage: float


class GridCell(BaseModel):
    latitude: float
    longitude: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    cell_area_km2: float
    overlap_area_km2: float
    overlap_fraction: float
    weight: float = Field(..., description="Normalised area weight in the regional mean (0 if excluded)")
    status: CellStatus
    exclusion_reason: str | None
    valid_months: int
    total_months: int
    period_mean: float | None
    annual: list[float | None] = Field(..., description="Day-weighted annual means, aligned with cell_years")
    clip: dict[str, Any] | None = Field(None, description="Polygon mode: GeoJSON of the part of the cell inside the area")


class RegionalDataResponse(BaseModel):
    metadata: RegionalMetadata
    monthly: list[RegionalMonthlyRecord]
    annual: list[RegionalAnnualRecord]
    summary: RegionalSummary
    cells: list[GridCell]
    cell_years: list[int]
    warnings: list[str]


class RegionalAnalysisResponse(RegionalDataResponse):
    statistics: StatisticsResult | None
    analysis_message: str | None
    analysis_error: str | None
    interpretation: Interpretation


class RegionPreset(BaseModel):
    name: str
    description: str
    bbox: BBoxModel


class RegionalConfigResponse(BaseModel):
    variables: list[VariableInfo]
    min_span_deg: float
    max_span_deg: float
    nasa_min_span_deg: float = 2.0
    nasa_max_span_deg: float = 10.0
    default_coverage_threshold: float
    min_land_fraction: float
    grid_lat_step: float
    grid_lon_step: float
    min_year: int
    max_year: int
    default_start_year: int
    default_end_year: int
    min_year_span: int
    presets: list[RegionPreset]
