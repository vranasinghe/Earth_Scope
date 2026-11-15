from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import GeocoderDep
from app.models.schemas import ErrorResponse, GeocodeSearchResponse, Place, ReverseGeocodeResponse
from app.utils.validators import validate_coordinates

router = APIRouter(prefix="/geocode", tags=["location search"])

ERRORS = {code: {"model": ErrorResponse} for code in (422, 503)}


@router.get(
    "/search",
    response_model=GeocodeSearchResponse,
    responses=ERRORS,
    summary="Find places worldwide by name, or parse 'lat, lon' text",
)
def search(
    geocoder: GeocoderDep,
    q: Annotated[str, Query(description="Place name (city, country, region, landmark) or 'lat, lon'")],
    limit: Annotated[int, Query(ge=1, le=10)] = 8,
) -> GeocodeSearchResponse:
    results = geocoder.search(q, limit=limit)
    return GeocodeSearchResponse(query=q, results=[Place.model_validate(r) for r in results])


@router.get(
    "/reverse",
    response_model=ReverseGeocodeResponse,
    responses=ERRORS,
    summary="Readable place name for coordinates (null over open ocean)",
)
def reverse(
    geocoder: GeocoderDep,
    latitude: Annotated[float, Query()],
    longitude: Annotated[float, Query()],
) -> ReverseGeocodeResponse:
    lat, lon = validate_coordinates(latitude, longitude)
    place = geocoder.reverse(lat, lon)
    return ReverseGeocodeResponse(latitude=lat, longitude=lon, place=Place.model_validate(place) if place else None)
