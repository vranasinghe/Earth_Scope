"""Pydantic response schemas shared by the API routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DataMode = Literal["LIVE"]
MonthlyStatus = Literal["valid", "missing", "invalid"]
AnnualStatus = Literal["complete", "incomplete", "missing"]
Direction = Literal["increasing", "decreasing", "no change"]
EvidenceCategory = Literal[
    "significant_increasing",
    "significant_decreasing",
    "not_significant",
    "mixed",
]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    timestamp: str


class VariableInfo(BaseModel):
    id: str
    name: str
    parameter: str
    community: str
    category: str
    description: str
    purpose: str
    expected_unit: str
    unit_display: str
    rate_unit: str
    source_note: str
    spatial_resolution: str
    notes: list[str]
    temporal_resolution: Literal["monthly"] = "monthly"
    data_source: str
    supported_communities: list[str]
    available_temporal_resolutions: list[str]
    coverage_start_year: int
    geographic_coverage: str
    land_only: bool
    alternatives: list[str]


class VariablesResponse(BaseModel):
    variables: list[VariableInfo]
    min_year: int
    max_year: int
    default_start_year: int
    default_end_year: int
    min_year_span: int
    min_valid_months_per_year: int
    min_annual_records: int
    significance_alpha: float
    documentation_url: str
    parameter_docs_url: str


class GridCell(BaseModel):
    """MERRA-2 cell (0.5 deg x 0.625 deg) whose values NASA POWER returns for the point."""

    center_latitude: float
    center_longitude: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    lat_step: float
    lon_step: float


class DatasetMetadata(BaseModel):
    data_mode: DataMode
    provider: str
    dataset_title: str | None = None
    api_version: str | None = None
    variable_id: str
    variable_name: str
    parameter: str
    long_name: str | None = None
    community: str
    sources: list[str] = Field(default_factory=list)
    units_raw: str | None = Field(None, description="Unit string exactly as returned by NASA POWER")
    unit_display: str
    rate_unit: str
    latitude_requested: float
    longitude_requested: float
    latitude_returned: float | None = Field(None, description="Point echoed in NASA's response geometry")
    longitude_returned: float | None = Field(None, description="Point echoed in NASA's response geometry")
    elevation_m: float | None = Field(None, description="Elevation of the grid cell reported by NASA")
    grid_cell: GridCell | None = None
    spatial_resolution: str
    temporal_resolution: Literal["monthly"] = "monthly"
    time_standard: str | None = None
    start_year: int
    end_year: int
    fill_value: float | None = None
    latest_complete_year: int | None = None
    retrieved_at: str
    served_from_cache: bool = False
    request_url: str | None = None
    documentation_url: str
    parameter_docs_url: str
    source_note: str


class MonthlyRecord(BaseModel):
    date: str = Field(..., description="Month in YYYY-MM format")
    year: int
    month: int
    value: float | None
    status: MonthlyStatus


class AnnualRecord(BaseModel):
    year: int
    value: float | None = Field(None, description="Day-weighted mean of the valid monthly values")
    valid_months: int
    total_months: int = 12
    status: AnnualStatus
    used_in_trend: bool


class DataSummary(BaseModel):
    n_monthly_total: int
    n_monthly_valid: int
    n_monthly_missing: int
    n_annual_total: int
    n_annual_complete: int
    n_annual_used: int
    min_valid_months_per_year: int


class TrendPoint(BaseModel):
    year: int
    value: float


class RegressionResult(BaseModel):
    slope: float
    intercept: float
    p_value: float
    r_squared: float
    r: float
    std_err: float
    ci_lower: float
    ci_upper: float
    confidence_level: float
    n: int
    degrees_of_freedom: int
    significant: bool
    direction: Direction
    slope_per_decade: float
    trend_line: list[TrendPoint]


class MannKendallResult(BaseModel):
    trend: Direction
    significant: bool
    p_value: float
    z: float
    tau: float
    s: float
    var_s: float
    n: int


class SensSlopeResult(BaseModel):
    slope: float
    intercept: float
    slope_per_decade: float
    direction: Direction
    n_pairs: int
    ci_lower: float | None = Field(None, description="Lower bound of Sen's non-parametric CI (per year)")
    ci_upper: float | None = Field(None, description="Upper bound of Sen's non-parametric CI (per year)")
    confidence_level: float | None = None
    ci_method: str | None = None


class EvidenceSummary(BaseModel):
    category: EvidenceCategory
    label: str
    explanation: str


class AcfPoint(BaseModel):
    lag: int
    value: float
    outside_bound: bool


class LjungBox(BaseModel):
    q: float
    lags: int
    p_value: float
    significant: bool


class AutocorrelationDiagnostics(BaseModel):
    basis: str
    n: int
    lag1: float
    lag1_assessment: Literal["not_significant", "significant_positive", "significant_negative"]
    bound: float
    acf: list[AcfPoint]
    ljung_box: LjungBox
    has_gaps: bool
    notes: list[str]


class ModifiedMannKendallResult(BaseModel):
    method: str
    available: bool
    s: float
    var_s_original: float
    var_s: float | None
    raw_correction_factor: float = Field(..., description="Estimated factor before the floor at 1")
    correction_factor: float = Field(..., description="Applied factor (never below 1)")
    reduction_suppressed: bool = Field(..., description="True if a variance reduction was estimated but not applied")
    canonical_var_s: float | None = Field(None, description="Var(S) of the unmodified published method (no floor)")
    canonical_z: float | None = None
    canonical_p_value: float | None = Field(None, description="p-value of the unmodified published method (no floor)")
    canonical_significant: bool | None = None
    effective_n: float | None
    z: float | None
    p_value: float | None
    significant: bool | None
    trend: Direction | None
    n: int
    lags_considered: int
    rank_acf: list[AcfPoint]
    significant_lags: list[int]
    correction_applied: bool
    reliable: bool
    reliability_note: str | None
    unavailable_reason: str | None


class HacRegressionResult(BaseModel):
    method: str
    slope: float
    std_err: float
    t_statistic: float
    p_value: float
    ci_lower: float
    ci_upper: float
    confidence_level: float
    max_lags: int
    kernel: str
    significant: bool
    degrees_of_freedom: int


class RobustEvidence(BaseModel):
    category: EvidenceCategory
    label: str
    explanation: str


class AdvancedStatistics(BaseModel):
    autocorrelation: AutocorrelationDiagnostics
    modified_mann_kendall: ModifiedMannKendallResult
    yue_wang_sensitivity: ModifiedMannKendallResult
    regression_hac: HacRegressionResult
    robust_evidence: RobustEvidence


class StatisticsResult(BaseModel):
    alpha: float
    n_years: int
    first_year: int
    last_year: int
    regression: RegressionResult
    mann_kendall: MannKendallResult
    sens_slope: SensSlopeResult
    evidence: EvidenceSummary
    advanced: AdvancedStatistics | None = None


class Interpretation(BaseModel):
    headline: str
    paragraphs: list[str]
    caveats: list[str]
    advanced: list[str] = Field(default_factory=list, description="Rule-based text for the advanced statistics")


class DataResponse(BaseModel):
    metadata: DatasetMetadata
    monthly: list[MonthlyRecord]
    annual: list[AnnualRecord]
    summary: DataSummary
    warnings: list[str]


class AnalysisResponse(DataResponse):
    statistics: StatisticsResult | None
    analysis_message: str | None = Field(
        None, description="Why statistics could not be computed, if they are null"
    )
    analysis_error: str | None = Field(
        None, description="Machine-readable reason, e.g. INSUFFICIENT_DATA_FOR_ANALYSIS"
    )
    interpretation: Interpretation


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[str] = Field(default_factory=list)
    retryable: bool = False
    suggested_variables: list[str] = Field(default_factory=list)


# --- Location search ---------------------------------------------------------

class Place(BaseModel):
    name: str
    display_name: str
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    place_type: str | None = None
    latitude: float
    longitude: float
    source: str


class GeocodeSearchResponse(BaseModel):
    query: str
    results: list[Place]
    attribution: str = "Search data © OpenStreetMap contributors (Nominatim)"


class ReverseGeocodeResponse(BaseModel):
    latitude: float
    longitude: float
    place: Place | None
    attribution: str = "Search data © OpenStreetMap contributors (Nominatim)"


# --- Multi-location comparison ----------------------------------------------

class CompareLocationResult(BaseModel):
    label: str
    latitude: float
    longitude: float
    ok: bool
    error: ErrorResponse | None
    metadata: DatasetMetadata | None
    annual: list[AnnualRecord]
    summary: DataSummary | None
    statistics: StatisticsResult | None
    analysis_message: str | None
    analysis_error: str | None
    warnings: list[str]


class CompareSummary(BaseModel):
    lines: list[str]
    caveats: list[str]


class CompareResponse(BaseModel):
    data_mode: DataMode
    variable_id: str
    variable_name: str
    parameter: str
    unit_display: str
    rate_unit: str
    start_year: int
    end_year: int
    alpha: float
    locations: list[CompareLocationResult]
    summary: CompareSummary
