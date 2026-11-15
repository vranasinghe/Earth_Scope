"""Input validation shared by the API routes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.catalog import VariableDefinition, get_variable
from app.core.config import Settings
from app.utils.errors import InvalidCoordinatesError, TemporalRangeError, UnsupportedVariableError


@dataclass(frozen=True)
class AnalysisQuery:
    variable: VariableDefinition
    latitude: float
    longitude: float
    start_year: int
    end_year: int


def validate_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    errors: list[str] = []
    if latitude is None or not math.isfinite(latitude) or not -90 <= latitude <= 90:
        errors.append("Latitude must be a number between -90 and 90.")
    if longitude is None or not math.isfinite(longitude) or not -180 <= longitude <= 180:
        errors.append("Longitude must be a number between -180 and 180.")
    if errors:
        raise InvalidCoordinatesError("Invalid coordinates.", errors)
    # NASA POWER resolves points to its grid; 4 decimals (~11 m) is far finer
    # than the grid and keeps cache keys stable. -180 and 180 are the same
    # meridian; both are accepted (NASA POWER returns data for either).
    return round(latitude, 4), round(longitude, 4)


def validate_years(
    start_year: int, end_year: int, settings: Settings, coverage_start: int | None = None
) -> tuple[int, int]:
    errors: list[str] = []
    lo, hi = max(settings.data_min_year, coverage_start or 0), settings.max_year
    if not lo <= start_year <= hi:
        errors.append(f"Start year must be between {lo} and {hi}.")
    if not lo <= end_year <= hi:
        errors.append(f"End year must be between {lo} and {hi}.")
    if not errors and start_year >= end_year:
        errors.append("Start year must be earlier than end year.")
    span = end_year - start_year + 1
    if not errors and span < settings.min_year_span:
        errors.append(
            f"Please select at least {settings.min_year_span} years "
            f"(you selected {span}). Trend tests need a reasonably long record."
        )
    if errors:
        raise TemporalRangeError("Invalid time range.", errors)
    return start_year, end_year


def resolve_variable(key: str) -> VariableDefinition:
    variable = get_variable(key)
    if variable is None:
        raise UnsupportedVariableError(
            f"Unsupported variable '{key}'.",
            ["Use GET /api/variables to list the supported variables."],
        )
    return variable


def build_query(
    variable: str,
    latitude: float,
    longitude: float,
    start_year: int,
    end_year: int,
    settings: Settings,
) -> AnalysisQuery:
    var = resolve_variable(variable)
    lat, lon = validate_coordinates(latitude, longitude)
    start, end = validate_years(start_year, end_year, settings, var.coverage_start_year)
    return AnalysisQuery(var, lat, lon, start, end)
