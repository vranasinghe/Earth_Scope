"""Pydantic models for the per-grid-cell spatial trend analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.regional_schemas import RegionalMetadata
from app.models.schemas import StatisticsResult

CellDataStatus = Literal["analysed", "insufficient_data", "no_variation", "calculation_failed", "excluded"]
Availability = Literal["complete", "partial", "insufficient", "missing", "excluded"]
SignificanceStatus = Literal[
    "significant_increasing", "significant_decreasing", "not_significant", "insufficient_data", "not_testable", "excluded"
]
Direction = Literal["increasing", "decreasing", "near_zero"]


class SpatialTrendCell(BaseModel):
    id: str = Field(..., description="Stable cell id from the MERRA-2 cell centre: '<lat>_<lon>'")
    latitude: float
    longitude: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    cell_area_km2: float
    overlap_area_km2: float
    overlap_fraction: float
    clip: dict[str, Any] | None = Field(None, description="Polygon mode: GeoJSON of the part of the cell inside the area")
    weight: float = Field(..., description="Overlap area / included area (0 for excluded cells)")
    valid_months: int
    total_months: int
    valid_years: int = Field(..., description="Years with enough valid months to enter the trend tests")
    total_years: int
    period_mean: float | None
    data_status: CellDataStatus
    availability: Availability
    reason: str | None
    first_year: int | None
    last_year: int | None
    ols_slope: float | None
    ols_intercept: float | None
    ols_p_value: float | None
    ols_r_squared: float | None
    ols_std_err: float | None
    ols_ci_lower: float | None
    ols_ci_upper: float | None
    hac_p_value: float | None
    sen_slope: float | None
    sen_ci_lower: float | None
    sen_ci_upper: float | None
    mk_s: float | None
    mk_tau: float | None
    mk_z: float | None
    mk_p_value: float | None
    hr_canonical_p_value: float | None
    hr_conservative_p_value: float | None
    yw_canonical_p_value: float | None
    lag1_autocorrelation: float | None
    ljung_box_p_value: float | None
    direction_sen: Direction | None
    direction_ols: Direction | None
    raw_p_value: float | None = Field(None, description="p-value of the selected test (None if not in the family)")
    adjusted_p_value: float | None = Field(None, description="FDR-adjusted p-value (q); None when no correction is applied")
    in_family: bool
    raw_status: SignificanceStatus
    adjusted_status: SignificanceStatus
    status: SignificanceStatus = Field(..., description="Active classification (adjusted if a correction is selected)")
    status_reason: str | None


class MethodOption(BaseModel):
    id: str
    label: str
    short: str
    description: str


class CorrectionOption(BaseModel):
    id: str
    label: str


class SpatialTrendConfig(BaseModel):
    method: str
    method_label: str
    method_description: str
    correction: str
    correction_label: str
    alpha: float
    n_hypotheses: int
    min_valid_months_per_year: int
    min_years: int
    screening_alpha: float
    confidence_level: float
    raw_rule: str
    adjusted_rule: str
    direction_basis: str
    near_zero_rule: str
    methods: list[MethodOption]
    corrections: list[CorrectionOption]
    alphas: list[float]


class CategorySummary(BaseModel):
    count: int
    area_km2: float
    pct_of_included_cells: float | None
    pct_of_included_area: float | None
    pct_of_tested_cells: float | None
    pct_of_tested_area: float | None


class SpatialSummary(BaseModel):
    n_cells_total: int
    n_cells_included: int
    n_cells_excluded: int
    n_cells_analysed: int
    n_hypotheses: int
    n_raw_significant: int
    n_fdr_discoveries: int | None
    included_area_km2: float
    tested_area_km2: float
    categories: dict[SignificanceStatus, CategorySummary]
    n_positive_slope: int
    n_negative_slope: int
    n_near_zero_slope: int
    area_weighted_mean_ols_slope: float | None
    slope_identity_exact: bool = Field(
        ..., description="True when every included cell is complete in every month, so the regional OLS slope equals "
        "the area-weighted mean of cell OLS slopes exactly"
    )
    alpha: float


class AnnualPoint(BaseModel):
    year: int
    value: float | None
    used_in_trend: bool


class CellAnnualPoint(AnnualPoint):
    valid_months: int


class RegionalAggregate(BaseModel):
    annual: list[AnnualPoint]
    ols_slope: float | None
    ols_p_value: float | None
    sen_slope: float | None
    mk_p_value: float | None
    evidence_label: str | None
    n_years: int
    analysis_message: str | None


class SpatialTrendResponse(BaseModel):
    metadata: RegionalMetadata
    config: SpatialTrendConfig
    summary: SpatialSummary
    regional_aggregate: RegionalAggregate | None
    cells: list[SpatialTrendCell]
    years: list[int]
    available: bool
    unavailable_reason: str | None
    interpretation: list[str]
    warnings: list[str]


class SpatialCellDetailResponse(BaseModel):
    metadata: RegionalMetadata
    config: SpatialTrendConfig
    cell: SpatialTrendCell
    annual: list[CellAnnualPoint]
    statistics: StatisticsResult | None
    regional_annual: list[AnnualPoint] | None
