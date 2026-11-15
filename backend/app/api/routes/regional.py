"""Regional (bounding-box) analysis endpoints.

GET, query-parameter based, consistent with the rest of the Earth Scope API.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ClientDep, SettingsDep
from app.api.routes.variables import list_variables
from app.models.regional_schemas import (
    BBoxModel,
    RegionalAnalysisResponse,
    RegionalConfigResponse,
    RegionalDataResponse,
    RegionPreset,
)
from app.models.schemas import ErrorResponse
from app.models.spatial_trend_schemas import SpatialCellDetailResponse, SpatialTrendResponse
from app.services import spatial_trend_analysis as sta
from app.services.regional_analysis import RegionalQuery, build_regional_response
from app.services.regional_grid import region_summary, validate_bbox
from app.utils.errors import InvalidRequestError
from app.utils.grid import LAT_STEP, LON_STEP
from app.utils.validators import resolve_variable, validate_years

router = APIRouter(prefix="/regional", tags=["regional analysis"])
ERRORS = {code: {"model": ErrorResponse} for code in (404, 422, 502, 503)}

# Example boxes (convenience only — any valid rectangle can be analysed).
PRESETS = [
    RegionPreset(name="Sri Lanka (central)", description="Most of the island of Sri Lanka", bbox=BBoxModel(lat_min=6, lat_max=9.5, lon_min=79.5, lon_max=82)),
    RegionPreset(name="Indo-Gangetic Plain", description="Agricultural plain, northern India", bbox=BBoxModel(lat_min=25, lat_max=29, lon_min=77, lon_max=83)),
    RegionPreset(name="Central Amazon", description="Amazon rainforest, Brazil", bbox=BBoxModel(lat_min=-6, lat_max=-2, lon_min=-64, lon_max=-58)),
    RegionPreset(name="Kenya highlands", description="Central Kenya around Nairobi", bbox=BBoxModel(lat_min=-3, lat_max=1, lon_min=35, lon_max=39)),
    RegionPreset(name="Murray–Darling (south)", description="Agricultural south-east Australia", bbox=BBoxModel(lat_min=-36, lat_max=-32, lon_min=142, lon_max=148)),
    RegionPreset(name="Central Europe", description="Germany, Czechia, Austria area", bbox=BBoxModel(lat_min=47, lat_max=52, lon_min=8, lon_max=16)),
    RegionPreset(name="US Corn Belt", description="Iowa / Illinois, United States", bbox=BBoxModel(lat_min=40, lat_max=43, lon_min=-95, lon_max=-88)),
    RegionPreset(name="Central Sahara", description="Desert, southern Algeria / Niger", bbox=BBoxModel(lat_min=20, lat_max=25, lon_min=5, lon_max=12)),
]


@router.get("/config", response_model=RegionalConfigResponse, summary="Limits, defaults and presets for regional analysis")
def config(settings: SettingsDep) -> RegionalConfigResponse:
    v = list_variables(settings)
    return RegionalConfigResponse(
        variables=v.variables,
        min_span_deg=settings.regional_min_span_deg,
        max_span_deg=settings.regional_max_span_deg,
        default_coverage_threshold=settings.regional_coverage_threshold,
        min_land_fraction=settings.regional_min_land_fraction,
        grid_lat_step=LAT_STEP,
        grid_lon_step=LON_STEP,
        min_year=v.min_year,
        max_year=v.max_year,
        default_start_year=v.default_start_year,
        default_end_year=v.default_end_year,
        min_year_span=v.min_year_span,
        presets=PRESETS,
    )


def _query(
    settings,
    variable: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    start_year: int | None,
    end_year: int | None,
    coverage_threshold: float | None,
) -> RegionalQuery:
    var = resolve_variable(variable)
    bbox = validate_bbox(lat_min, lat_max, lon_min, lon_max, settings.regional_min_span_deg, settings.regional_max_span_deg)
    start, end = validate_years(
        start_year if start_year is not None else settings.default_start_year,
        end_year if end_year is not None else settings.default_end_year,
        settings,
        var.coverage_start_year,
    )
    thr = settings.regional_coverage_threshold if coverage_threshold is None else coverage_threshold
    if not 0.5 <= thr <= 1.0:
        raise InvalidRequestError("coverage_threshold must be between 0.5 and 1.0.")
    return RegionalQuery(var, bbox, start, end, thr)


Lat = Annotated[float, Query(description="Latitude, -90..90")]
Lon = Annotated[float, Query(description="Longitude, -180..180 (west to east; antimeridian crossing not supported)")]


@router.get("/preview", summary="Area and expected grid cells for a box (no NASA request)")
def preview(settings: SettingsDep, lat_min: Lat, lat_max: Lat, lon_min: Lon, lon_max: Lon) -> dict:
    b = validate_bbox(lat_min, lat_max, lon_min, lon_max, settings.regional_min_span_deg, settings.regional_max_span_deg)
    return region_summary(b)


@router.get("/data", response_model=RegionalDataResponse, responses=ERRORS, summary="Area-weighted regional monthly and annual series")
def regional_data(
    client: ClientDep, settings: SettingsDep, variable: str, lat_min: Lat, lat_max: Lat, lon_min: Lon, lon_max: Lon,
    start_year: int | None = None, end_year: int | None = None, coverage_threshold: float | None = None,
) -> RegionalDataResponse:
    q = _query(settings, variable, lat_min, lat_max, lon_min, lon_max, start_year, end_year, coverage_threshold)
    return RegionalDataResponse.model_validate(build_regional_response(q, client, settings, analyze=False))


@router.get("/analyze", response_model=RegionalAnalysisResponse, responses=ERRORS, summary="Regional series + full trend statistics")
def regional_analyze(
    client: ClientDep, settings: SettingsDep, variable: str, lat_min: Lat, lat_max: Lat, lon_min: Lon, lon_max: Lon,
    start_year: int | None = None, end_year: int | None = None, coverage_threshold: float | None = None,
) -> RegionalAnalysisResponse:
    q = _query(settings, variable, lat_min, lat_max, lon_min, lon_max, start_year, end_year, coverage_threshold)
    return RegionalAnalysisResponse.model_validate(build_regional_response(q, client, settings, analyze=True))


Method = Annotated[str, Query(description="Test used for the significance map: " + ", ".join(sta.METHODS))]
Correction = Annotated[str, Query(description="none | fdr_bh (Benjamini–Hochberg) | fdr_by (Benjamini–Yekutieli)")]
Alpha = Annotated[float, Query(description="Significance threshold: 0.01, 0.05 or 0.10")]


@router.get("/spatial-trends", response_model=SpatialTrendResponse, responses=ERRORS,
            summary="Per-grid-cell trends with multiple-testing-corrected significance")
def spatial_trends(
    client: ClientDep, settings: SettingsDep, variable: str, lat_min: Lat, lat_max: Lat, lon_min: Lon, lon_max: Lon,
    start_year: int | None = None, end_year: int | None = None, coverage_threshold: float | None = None,
    method: Method = sta.DEFAULT_METHOD, correction: Correction = sta.DEFAULT_CORRECTION, alpha: Alpha = 0.05,
) -> SpatialTrendResponse:
    sta.validate_settings(method, correction, alpha)
    q = _query(settings, variable, lat_min, lat_max, lon_min, lon_max, start_year, end_year, coverage_threshold)
    return SpatialTrendResponse.model_validate(sta.build_spatial_response(q, client, settings, method, correction, alpha))


@router.get("/spatial-trends/cell", response_model=SpatialCellDetailResponse, responses=ERRORS,
            summary="Full statistics and annual series of one grid cell")
def spatial_trend_cell(
    client: ClientDep, settings: SettingsDep, variable: str, lat_min: Lat, lat_max: Lat, lon_min: Lon, lon_max: Lon,
    cell_id: str, start_year: int | None = None, end_year: int | None = None, coverage_threshold: float | None = None,
    method: Method = sta.DEFAULT_METHOD, correction: Correction = sta.DEFAULT_CORRECTION, alpha: Alpha = 0.05,
) -> SpatialCellDetailResponse:
    sta.validate_settings(method, correction, alpha)
    q = _query(settings, variable, lat_min, lat_max, lon_min, lon_max, start_year, end_year, coverage_threshold)
    return SpatialCellDetailResponse.model_validate(sta.build_cell_detail(q, client, settings, cell_id, method, correction, alpha))
