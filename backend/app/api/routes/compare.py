from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ClientDep, SettingsDep
from app.models.schemas import CompareResponse, ErrorResponse
from app.services.analysis_service import build_comparison_response
from app.utils.errors import InvalidCoordinatesError, InvalidRequestError
from app.utils.validators import resolve_variable, validate_coordinates, validate_years

router = APIRouter(tags=["comparison"])

ERRORS = {code: {"model": ErrorResponse} for code in (404, 422)}


def parse_locations(raw: str, labels_raw: str | None, max_n: int) -> list[tuple[float, float, str]]:
    """Parse ``"lat,lon;lat,lon"`` (and optional ``"label;label"``)."""
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if not 2 <= len(parts) <= max_n:
        raise InvalidRequestError(f"Provide between 2 and {max_n} locations to compare.")
    labels = [x.strip() for x in labels_raw.split(";")] if labels_raw else []
    out: list[tuple[float, float, str]] = []
    errors: list[str] = []
    for i, part in enumerate(parts):
        try:
            lat_s, lon_s = part.split(",")
            lat, lon = validate_coordinates(float(lat_s), float(lon_s))
        except (ValueError, InvalidCoordinatesError):
            errors.append(f"Location {i + 1} ('{part}') must be 'latitude,longitude' within -90..90 and -180..180.")
            continue
        label = labels[i] if i < len(labels) and labels[i] else f"{lat:.4f}, {lon:.4f}"
        out.append((lat, lon, label[:80]))
    if errors:
        raise InvalidCoordinatesError("Invalid comparison locations.", errors)
    if len({(lat, lon) for lat, lon, _ in out}) != len(out):
        raise InvalidRequestError("Each comparison location must be different.")
    return out


@router.get(
    "/compare",
    response_model=CompareResponse,
    responses=ERRORS,
    summary="Compare the trend of one variable at 2–3 locations worldwide",
)
def compare(
    client: ClientDep,
    settings: SettingsDep,
    variable: Annotated[str, Query(description="Catalogue id or NASA parameter")],
    locations: Annotated[str, Query(description="'lat,lon;lat,lon[;lat,lon]' — 2 to 3 points")],
    labels: Annotated[str | None, Query(description="Optional 'label;label;label'")] = None,
    start_year: Annotated[int | None, Query()] = None,
    end_year: Annotated[int | None, Query()] = None,
) -> CompareResponse:
    var = resolve_variable(variable)
    start, end = validate_years(
        start_year if start_year is not None else settings.default_start_year,
        end_year if end_year is not None else settings.default_end_year,
        settings,
        var.coverage_start_year,
    )
    points = parse_locations(locations, labels, settings.max_compare_locations)
    return CompareResponse.model_validate(build_comparison_response(var, points, start, end, client, settings))
