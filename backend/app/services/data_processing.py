"""Parsing and cleaning of NASA POWER monthly responses, and annual aggregation.

Rules enforced here (see README "Scientific methods"):

* NASA's ``YYYY13`` keys are *annual* values and are never treated as months.
* NASA fill values (``-999``) and non-numeric values become missing (``None``).
* Physically impossible values (outside the catalogue's valid range) are
  marked ``invalid`` and excluded from statistics.
* Missing values are never replaced by zero and never interpolated.
* Every month of the requested range appears in the output, so gaps are
  explicit rather than silently dropped.
* Annual values are day-weighted means of the valid months; a year is used in
  trend tests only if it has at least ``min_valid_months`` valid months.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core.catalog import VariableDefinition
from app.utils.errors import DataUnavailableError, LocationNotSupportedError, NasaPowerResponseError

DEFAULT_FILL_VALUE = -999.0


@dataclass
class PowerMetadata:
    dataset_title: str | None = None
    api_version: str | None = None
    sources: list[str] = field(default_factory=list)
    fill_value: float = DEFAULT_FILL_VALUE
    time_standard: str | None = None
    units_raw: str | None = None
    long_name: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    elevation_m: float | None = None


@dataclass
class ParsedDataset:
    monthly: pd.DataFrame  # columns: date, year, month, value, status
    metadata: PowerMetadata
    warnings: list[str] = field(default_factory=list)


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def is_fill_value(value: float | None, fill_value: float = DEFAULT_FILL_VALUE) -> bool:
    """True if ``value`` is missing or equal to NASA's fill value."""
    if value is None:
        return True
    return math.isclose(value, fill_value, abs_tol=1e-6) or value <= DEFAULT_FILL_VALUE


def parse_period_key(key: str) -> tuple[int, int] | None:
    """Parse a NASA POWER monthly key ``YYYYMM``.

    Returns ``(year, month)`` for months 1–12, and ``None`` for the annual
    ``YYYY13`` key or any malformed key.
    """
    if not isinstance(key, str) or len(key) != 6 or not key.isdigit():
        return None
    year, month = int(key[:4]), int(key[4:])
    if 1 <= month <= 12:
        return year, month
    return None


def extract_metadata(payload: dict[str, Any], parameter: str) -> PowerMetadata:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    api = header.get("api") if isinstance(header.get("api"), dict) else {}
    params_meta = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    pmeta = params_meta.get(parameter) if isinstance(params_meta.get(parameter), dict) else {}
    coords = (payload.get("geometry") or {}).get("coordinates") or []

    fill = _to_float(header.get("fill_value"))
    sources = header.get("sources") if isinstance(header.get("sources"), list) else []

    def coord(i: int) -> float | None:
        return _to_float(coords[i]) if len(coords) > i else None

    units = pmeta.get("units")
    return PowerMetadata(
        dataset_title=header.get("title"),
        api_version=api.get("version"),
        sources=[str(s) for s in sources],
        fill_value=fill if fill is not None else DEFAULT_FILL_VALUE,
        time_standard=header.get("time_standard"),
        units_raw=str(units).strip() if units not in (None, "") else None,
        long_name=pmeta.get("longname"),
        longitude=coord(0),
        latitude=coord(1),
        elevation_m=coord(2),
    )


def parse_power_response(
    payload: dict[str, Any],
    variable: VariableDefinition,
    start_year: int,
    end_year: int,
) -> ParsedDataset:
    """Convert a NASA POWER monthly point JSON payload into a clean monthly table."""
    if not isinstance(payload, dict):
        raise NasaPowerResponseError("NASA POWER returned an unexpected response structure.")

    properties = payload.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("parameter"), dict):
        messages = payload.get("messages")
        details = [str(m) for m in messages] if isinstance(messages, list) else []
        raise NasaPowerResponseError(
            "NASA POWER returned a response without time-series data.", details
        )

    series = properties["parameter"].get(variable.parameter)
    if not isinstance(series, dict) or not series:
        raise DataUnavailableError(
            f"NASA POWER did not return {variable.name} ({variable.parameter}) for this location and period.",
        )

    meta = extract_metadata(payload, variable.parameter)
    warnings: list[str] = []

    raw_by_month: dict[tuple[int, int], Any] = {}
    for key, raw in series.items():
        ym = parse_period_key(key)
        if ym is not None:
            raw_by_month[ym] = raw

    rows: list[dict[str, Any]] = []
    n_invalid = 0
    # The physical range is defined in the expected unit; if NASA reports other
    # units (e.g. K instead of C) the range would wrongly reject every value.
    check_range = meta.units_raw in (None, variable.expected_unit)
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            value = _to_float(raw_by_month.get((year, month)))
            if is_fill_value(value, meta.fill_value):
                status, value = "missing", None
            elif check_range and (
                (variable.valid_min is not None and value < variable.valid_min)
                or (variable.valid_max is not None and value > variable.valid_max)
            ):
                status, value = "invalid", None
                n_invalid += 1
            else:
                status = "valid"
            rows.append(
                {
                    "date": f"{year:04d}-{month:02d}",
                    "year": year,
                    "month": month,
                    "value": value,
                    "status": status,
                }
            )

    monthly = pd.DataFrame(rows, columns=["date", "year", "month", "value", "status"])

    n_valid = int((monthly["status"] == "valid").sum())
    if n_valid == 0:
        raise DataUnavailableError(
            f"NASA POWER returned only missing values for {variable.name} ({variable.parameter}) "
            "at this location and period.",
        )

    if n_invalid:
        warnings.append(
            f"{n_invalid} monthly value(s) were outside the physically valid range for "
            f"{variable.name} and were excluded."
        )

    # Unit checks: always prefer what NASA says, but tell the user if it differs.
    if meta.units_raw is None:
        warnings.append(
            f"NASA POWER did not report units for {variable.parameter}; the documented unit "
            f"'{variable.expected_unit}' is assumed."
        )
    elif meta.units_raw != variable.expected_unit:
        warnings.append(
            f"NASA POWER reported units '{meta.units_raw}' for {variable.parameter}, which differs "
            f"from the expected '{variable.expected_unit}'. Values are shown in NASA's reported units."
        )

    valid_values = monthly.loc[monthly["status"] == "valid", "value"].astype(float)
    if variable.land_only and np.allclose(valid_values, 1.0):
        # Verified live: GWETTOP is a constant 1.0 over oceans, large lakes (e.g. Lake
        # Victoria) and ice sheets (Antarctica, Greenland). Such a series is not soil
        # information, so the analysis is refused rather than shown.
        raise LocationNotSupportedError(
            f"{variable.name} is not meaningful at this location.",
            [
                f"Every {variable.parameter} value here equals 1.0, which NASA POWER reports over "
                "oceans, large lakes and permanent ice sheets — not over ice-free land.",
                "Choose a land location, or analyse a different variable for this point.",
            ],
            suggested_variables=list(variable.alternatives),
        )

    return ParsedDataset(monthly=monthly, metadata=meta, warnings=warnings)


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def aggregate_annual(monthly: pd.DataFrame, min_valid_months: int = 10) -> pd.DataFrame:
    """Aggregate monthly means into day-weighted annual means.

    ``annual = Σ(value_m × days_m) / Σ(days_m)`` over the *valid* months of each
    year. Monthly means are never summed. Each row records how many valid months
    contributed; years with fewer than ``min_valid_months`` are marked
    ``incomplete`` and excluded from trend tests (their mean is still reported
    for transparency). Years with no valid months have value ``None``.
    """
    records: list[dict[str, Any]] = []
    for year, group in monthly.groupby("year", sort=True):
        valid = group[group["status"] == "valid"]
        n_valid = int(len(valid))
        if n_valid == 0:
            records.append(
                {"year": int(year), "value": None, "valid_months": 0, "status": "missing", "used_in_trend": False}
            )
            continue
        weights = np.array([days_in_month(int(year), int(m)) for m in valid["month"]], dtype=float)
        values = valid["value"].astype(float).to_numpy()
        mean = float(np.sum(values * weights) / np.sum(weights))
        complete = n_valid >= min_valid_months
        records.append(
            {
                "year": int(year),
                "value": mean,
                "valid_months": n_valid,
                "status": "complete" if complete else "incomplete",
                "used_in_trend": complete,
            }
        )
    return pd.DataFrame(records, columns=["year", "value", "valid_months", "status", "used_in_trend"])


def latest_complete_year(monthly: pd.DataFrame) -> int | None:
    """Latest year in which all 12 months are valid."""
    counts = monthly[monthly["status"] == "valid"].groupby("year").size()
    full = counts[counts == 12]
    return int(full.index.max()) if len(full) else None
