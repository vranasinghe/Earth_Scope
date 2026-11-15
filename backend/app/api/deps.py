"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Query

from app.core.config import Settings, get_settings
from app.services.geocoding import Geocoder
from app.services.nasa_power import NasaPowerClient
from app.utils.validators import AnalysisQuery, build_query


@lru_cache
def get_nasa_client() -> NasaPowerClient:
    # One shared client so the in-memory cache is shared across requests.
    return NasaPowerClient(get_settings())


@lru_cache
def get_geocoder() -> Geocoder:
    # One shared geocoder so the cache and the 1 request/second throttle are process-wide.
    return Geocoder(get_settings())


SettingsDep = Annotated[Settings, Depends(get_settings)]
ClientDep = Annotated[NasaPowerClient, Depends(get_nasa_client)]
GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]


def analysis_query(
    settings: SettingsDep,
    variable: Annotated[str, Query(description="Catalogue id (e.g. air_temperature) or NASA parameter (e.g. T2M)")],
    latitude: Annotated[float, Query(description="Latitude in decimal degrees, -90 to 90")],
    longitude: Annotated[float, Query(description="Longitude in decimal degrees, -180 to 180")],
    start_year: Annotated[int | None, Query(description="First year (default 2001)")] = None,
    end_year: Annotated[int | None, Query(description="Last year (default: latest normally complete year)")] = None,
) -> AnalysisQuery:
    return build_query(
        variable,
        latitude,
        longitude,
        start_year if start_year is not None else settings.default_start_year,
        end_year if end_year is not None else settings.default_end_year,
        settings,
    )


QueryDep = Annotated[AnalysisQuery, Depends(analysis_query)]
