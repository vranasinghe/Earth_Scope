"""Country boundaries and country / custom-polygon analysis.

Boundaries are GET (selected by ISO code from the bundled catalogue). Polygon
endpoints are POST because the geometry travels in the request body; the body
size is capped before parsing. The analyses reuse the regional pipeline and
return the same response models as rectangle analysis, with extra area metadata.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import ClientDep, SettingsDep
from app.core.config import Settings
from app.models.area_schemas import (
    AreaCellRequest,
    AreaDescription,
    AreaPreviewResponse,
    AreaRequest,
    AreaSpatialRequest,
    CountryListItem,
    CountryListResponse,
)
from app.models.regional_schemas import RegionalAnalysisResponse
from app.models.schemas import ErrorResponse
from app.models.spatial_trend_schemas import SpatialCellDetailResponse, SpatialTrendResponse
from app.services import area_analysis as aa
from app.services import boundaries
from app.services import spatial_trend_analysis as sta
from app.services.regional_analysis import RegionalQuery, build_regional_response
from app.utils.errors import GeometryTooComplexError, InvalidRequestError
from app.utils.validators import resolve_variable, validate_years

boundary_router = APIRouter(prefix="/boundaries", tags=["country boundaries"])
polygon_router = APIRouter(prefix="/polygon", tags=["country & polygon analysis"])
ERRORS = {code: {"model": ErrorResponse} for code in (404, 422, 502, 503)}


def _body_limit(request: Request) -> None:
    from app.core.config import get_settings

    size = request.headers.get("content-length")
    if size is not None and size.isdigit() and int(size) > get_settings().polygon_max_body_bytes:
        raise GeometryTooComplexError(
            f"The request is larger than {get_settings().polygon_max_body_bytes // 1_000_000} MB.",
            ["Simplify the geometry or upload a smaller area."],
        )


BodyLimit = Annotated[None, Depends(_body_limit)]


def _describe(a: aa.AreaSpec) -> AreaDescription:
    b = a.bbox
    return AreaDescription(
        kind=a.kind, name=a.name, iso3=a.iso3, geometry_id=a.geometry_id, geometry=a.display,
        bbox={"lat_min": b.lat_min, "lat_max": b.lat_max, "lon_min": b.lon_min, "lon_max": b.lon_max},
        area_km2=a.area_km2, geodesic_area_km2=a.geodesic_area_km2, n_components=a.n_components, n_vertices=a.n_vertices,
        boundary=a.boundary, notes=list(a.notes),
    )


def _years(settings: Settings, var, start: int | None, end: int | None) -> tuple[int, int]:
    return validate_years(start if start is not None else settings.default_start_year,
                          end if end is not None else settings.default_end_year, settings, var.coverage_start_year)


def _query(req: AreaRequest, settings: Settings) -> RegionalQuery:
    var = resolve_variable(req.variable)
    start, end = _years(settings, var, req.start_year, req.end_year)
    thr = settings.regional_coverage_threshold if req.coverage_threshold is None else req.coverage_threshold
    if not 0.5 <= thr <= 1.0:
        raise InvalidRequestError("coverage_threshold must be between 0.5 and 1.0.")
    area = aa.area_from_request(req.iso3, req.geometry, req.name, settings)
    return RegionalQuery(var, area.bbox, start, end, thr, area)


# --------------------------------------------------------------------------- #
# Boundaries
# --------------------------------------------------------------------------- #

@boundary_router.get("/countries", response_model=CountryListResponse, summary="Countries with an available boundary")
def countries() -> CountryListResponse:
    return CountryListResponse(countries=[CountryListItem(iso3=c["iso3"], name=c["name"], source=c["source"], status=c.get("status"))
                                          for c in boundaries.list_countries()])


@boundary_router.get("/countries/{iso3}", response_model=AreaPreviewResponse, responses=ERRORS,
                     summary="Country boundary, metadata and analysis preflight")
def country(settings: SettingsDep, iso3: str, variable: Annotated[str, Query()] = "T2M",
            start_year: int | None = None, end_year: int | None = None) -> AreaPreviewResponse:
    var = resolve_variable(variable)
    start, end = _years(settings, var, start_year, end_year)
    area = aa.area_from_request(iso3, None, None, settings)
    return AreaPreviewResponse(area=_describe(area), preflight=aa.preflight(area, var, start, end, settings),
                               variable=var.id, start_year=start, end_year=end)


# --------------------------------------------------------------------------- #
# Polygon / country analysis
# --------------------------------------------------------------------------- #

@polygon_router.post("/preview", response_model=AreaPreviewResponse, responses=ERRORS,
                     summary="Validate an area and estimate cells, NASA requests and budgets (no NASA call)")
def preview(settings: SettingsDep, req: AreaRequest, _: BodyLimit) -> AreaPreviewResponse:
    var = resolve_variable(req.variable)
    start, end = _years(settings, var, req.start_year, req.end_year)
    area = aa.area_from_request(req.iso3, req.geometry, req.name, settings)
    return AreaPreviewResponse(area=_describe(area), preflight=aa.preflight(area, var, start, end, settings),
                               variable=var.id, start_year=start, end_year=end)


@polygon_router.post("/analyze", response_model=RegionalAnalysisResponse, responses=ERRORS,
                     summary="Polygon-weighted monthly/annual series + full trend statistics")
def analyze(client: ClientDep, settings: SettingsDep, req: AreaRequest, _: BodyLimit) -> RegionalAnalysisResponse:
    q = _query(req, settings)
    return RegionalAnalysisResponse.model_validate(build_regional_response(q, client, settings, analyze=True))


@polygon_router.post("/spatial-trends", response_model=SpatialTrendResponse, responses=ERRORS,
                     summary="Per-cell trends inside the area with multiple-testing-corrected significance")
def spatial_trends(client: ClientDep, settings: SettingsDep, req: AreaSpatialRequest, _: BodyLimit) -> SpatialTrendResponse:
    sta.validate_settings(req.method, req.correction, req.alpha)
    q = _query(req, settings)
    return SpatialTrendResponse.model_validate(sta.build_spatial_response(q, client, settings, req.method, req.correction, req.alpha))


@polygon_router.post("/spatial-trends/cell", response_model=SpatialCellDetailResponse, responses=ERRORS,
                     summary="Full statistics and annual series of one cell inside the area")
def spatial_trend_cell(client: ClientDep, settings: SettingsDep, req: AreaCellRequest, _: BodyLimit) -> SpatialCellDetailResponse:
    sta.validate_settings(req.method, req.correction, req.alpha)
    q = _query(req, settings)
    return SpatialCellDetailResponse.model_validate(
        sta.build_cell_detail(q, client, settings, req.cell_id, req.method, req.correction, req.alpha))
