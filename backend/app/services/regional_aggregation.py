"""Parse NASA POWER regional responses and compute area-weighted regional series.

Rules (see README "Regional Trend Analysis"):

* Every cell is a MERRA-2 grid cell (0.5° × 0.625°) identified by its centre.
  Duplicate centres are kept once (and counted); cells that do not overlap
  the user's box are discarded.
* NASA fill values (−999), non-numeric and physically impossible values are
  missing (NaN) — never zero, never interpolated.
* Weights are the exact spherical area of each cell's overlap with the box,
  so cells cut by the box edge count only for their inside part.
* For each month: regional mean = Σ(vᵢ·wᵢ)/Σwᵢ over VALID cells only, plus
  valid/missing counts, valid weighted area, coverage of the analysed area,
  area-weighted standard deviation across cells, min and max.
* A month is "valid" only if coverage ≥ the threshold; otherwise it is
  flagged "insufficient_coverage" and excluded from annual means.
* Land-only variables (soil wetness): cells constant at 1.0 for the whole
  record (oceans, large lakes, ice sheets — verified live) are excluded and
  coverage is measured against the LAND part of the box.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.catalog import VariableDefinition
from app.services.data_processing import DEFAULT_FILL_VALUE, _to_float, extract_metadata, parse_period_key
from app.services.regional_grid import BBox, overlap_area_km2, spherical_rect_area_km2
from app.utils.errors import DataUnavailableError, LocationNotSupportedError, NasaPowerResponseError


@dataclass
class RegionalGrid:
    lats: np.ndarray            # (C,)
    lons: np.ndarray            # (C,)
    values: np.ndarray          # (C, T) float, NaN = missing
    years: np.ndarray           # (T,)
    months: np.ndarray          # (T,)
    overlap_km2: np.ndarray     # (C,) area of cell ∩ box
    cell_km2: np.ndarray        # (C,) full cell area
    excluded: np.ndarray        # (C,) bool — excluded from the regional mean
    exclusion_reason: list[str | None]
    box_km2: float
    units_raw: str | None
    sources: list[str]
    fill_value: float
    dataset_title: str | None
    api_version: str | None
    time_standard: str | None
    long_name: str | None
    n_features: int
    n_duplicates: int
    n_outside: int
    n_invalid_values: int
    warnings: list[str] = field(default_factory=list)
    clips: list[dict[str, Any] | None] | None = None   # polygon mode: lon/lat GeoJSON of each cell's part inside the area


def parse_series_row(
    series: dict[str, Any], years: np.ndarray, months: np.ndarray, fill: float, check_range: bool, variable: VariableDefinition
) -> tuple[np.ndarray, int]:
    """One cell's monthly values (NaN = missing) and the number of out-of-range values rejected.

    Shared by the single-request rectangle parser and the tiled polygon merger so
    both apply identical fill-value and physical-range rules.
    """
    monthly = {parse_period_key(k): v for k, v in series.items() if parse_period_key(k)}
    row = np.full(len(years), np.nan)
    n_invalid = 0
    for t, (y, m) in enumerate(zip(years, months)):
        v = _to_float(monthly.get((int(y), int(m))))
        if v is None or math.isclose(v, fill, abs_tol=1e-6) or v <= DEFAULT_FILL_VALUE:
            continue
        if check_range and (
            (variable.valid_min is not None and v < variable.valid_min)
            or (variable.valid_max is not None and v > variable.valid_max)
        ):
            n_invalid += 1
            continue
        row[t] = v
    return row, n_invalid


def parse_regional_response(
    payload: dict[str, Any], variable: VariableDefinition, bbox: BBox, start_year: int, end_year: int
) -> RegionalGrid:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        messages = payload.get("messages") if isinstance(payload, dict) else None
        raise NasaPowerResponseError(
            "NASA POWER returned a regional response without grid data.",
            [str(m) for m in messages] if isinstance(messages, list) else [],
        )
    features = payload["features"]
    if not features:
        raise DataUnavailableError("NASA POWER returned no grid cells for this region.")

    meta = extract_metadata({**payload, "geometry": {}}, variable.parameter)
    fill = meta.fill_value if meta.fill_value is not None else DEFAULT_FILL_VALUE
    check_range = meta.units_raw in (None, variable.expected_unit)

    years = np.repeat(np.arange(start_year, end_year + 1), 12)
    months = np.tile(np.arange(1, 13), end_year - start_year + 1)
    keys = [f"{y}{m:02d}" for y, m in zip(years, months)]

    seen: set[tuple[float, float]] = set()
    lats, lons, rows, ov, full = [], [], [], [], []
    n_dup = n_out = n_invalid = 0
    for f in features:
        try:
            lon, lat = float(f["geometry"]["coordinates"][0]), float(f["geometry"]["coordinates"][1])
            series = f["properties"]["parameter"][variable.parameter]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        key = (round(lat, 4), round(lon, 4))
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)
        o, c = overlap_area_km2(key[0], key[1], bbox)
        if o <= 0:
            n_out += 1
            continue
        row, bad = parse_series_row(series if isinstance(series, dict) else {}, years, months, fill, check_range, variable)
        n_invalid += bad
        lats.append(key[0])
        lons.append(key[1])
        rows.append(row)
        ov.append(o)
        full.append(c)

    if not rows:
        raise DataUnavailableError("None of the returned grid cells overlaps the selected region.")

    values = np.vstack(rows)
    excluded = np.zeros(len(rows), dtype=bool)
    reasons: list[str | None] = [None] * len(rows)
    if variable.land_only:
        for i, r in enumerate(values):
            valid = r[~np.isnan(r)]
            if valid.size and np.allclose(valid, 1.0):
                excluded[i] = True
                reasons[i] = "water_or_ice"

    grid = RegionalGrid(
        lats=np.array(lats), lons=np.array(lons), values=values, years=years, months=months,
        overlap_km2=np.array(ov), cell_km2=np.array(full), excluded=excluded, exclusion_reason=reasons,
        box_km2=spherical_rect_area_km2(bbox.lat_min, bbox.lat_max, bbox.lon_min, bbox.lon_max),
        units_raw=meta.units_raw, sources=meta.sources, fill_value=fill, dataset_title=meta.dataset_title,
        api_version=meta.api_version, time_standard=meta.time_standard, long_name=meta.long_name,
        n_features=len(features), n_duplicates=n_dup, n_outside=n_out, n_invalid_values=n_invalid,
    )
    if n_dup:
        grid.warnings.append(f"{n_dup} duplicate grid cell(s) in the NASA response were counted once.")
    if n_invalid:
        grid.warnings.append(f"{n_invalid} cell-month value(s) outside the physically valid range were excluded.")
    if meta.units_raw is not None and meta.units_raw != variable.expected_unit:
        grid.warnings.append(
            f"NASA POWER reported units '{meta.units_raw}' (expected '{variable.expected_unit}'); values are shown as reported."
        )
    return grid


def analysed_area_km2(grid: RegionalGrid) -> float:
    """Denominator for coverage: the box, or its land part for land-only variables."""
    included = ~grid.excluded
    if grid.excluded.any():
        return float(grid.overlap_km2[included].sum())
    return grid.box_km2


def weighted_monthly(grid: RegionalGrid, coverage_threshold: float) -> dict[str, np.ndarray]:
    """Area-weighted regional statistics for every month (vectorised over cells)."""
    inc = ~grid.excluded
    v = grid.values[inc]                       # (C', T)
    w = grid.overlap_km2[inc][:, None]         # (C', 1)
    valid = ~np.isnan(v)
    wv = np.where(valid, w, 0.0)
    valid_w = wv.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(valid_w > 0, np.nansum(np.where(valid, v, 0.0) * wv, axis=0) / valid_w, np.nan)
        var = np.where(valid_w > 0, np.sum(np.where(valid, (v - mean) ** 2, 0.0) * wv, axis=0) / valid_w, np.nan)
    denom = analysed_area_km2(grid)
    # Clamp floating-point excess (polygon areas are summed per cell vs. computed whole): coverage ≤ 1.
    coverage = np.minimum(1.0, valid_w / denom) if denom > 0 else np.zeros_like(valid_w)
    n_valid = valid.sum(axis=0)
    status = np.where(n_valid == 0, "missing", np.where(coverage + 1e-12 >= coverage_threshold, "valid", "insufficient_coverage"))
    vmin = np.where(n_valid > 0, np.nanmin(np.where(valid, v, np.inf), axis=0), np.nan)
    vmax = np.where(n_valid > 0, np.nanmax(np.where(valid, v, -np.inf), axis=0), np.nan)
    return {
        "mean": mean, "sd": np.sqrt(var), "min": vmin, "max": vmax,
        "n_valid": n_valid, "n_missing": inc.sum() - n_valid,
        "valid_area_km2": valid_w, "coverage": coverage, "status": status,
    }


def _day_weights(years: np.ndarray, months: np.ndarray) -> np.ndarray:
    return np.array([calendar.monthrange(int(y), int(m))[1] for y, m in zip(years, months)], dtype=float)


def cell_annual_means(grid: RegionalGrid, min_valid_months: int) -> tuple[np.ndarray, np.ndarray]:
    """Day-weighted annual mean per cell, NaN where a year has < min_valid_months. Returns (years, C×Y)."""
    n_years = len(grid.years) // 12
    d = _day_weights(grid.years, grid.months).reshape(n_years, 12)
    v = grid.values.reshape(len(grid.lats), n_years, 12)
    valid = ~np.isnan(v)
    wsum = np.where(valid, d, 0.0).sum(axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        ann = (np.where(valid, v, 0.0) * d).sum(axis=2) / wsum
    ann[valid.sum(axis=2) < min_valid_months] = np.nan
    return grid.years.reshape(n_years, 12)[:, 0], ann


def cell_annual_table(grid: RegionalGrid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For every cell and year: day-weighted mean of the valid months (also for incomplete years) and the
    number of valid months. Returns (years, means C×Y with NaN where no valid month, valid_months C×Y).

    Same rule as ``data_processing.aggregate_annual`` (Σ value·days / Σ days over valid months), vectorised
    for all cells at once; tests check the two agree exactly for every cell.
    """
    n_years = len(grid.years) // 12
    d = _day_weights(grid.years, grid.months).reshape(n_years, 12)
    v = grid.values.reshape(len(grid.lats), n_years, 12)
    valid = ~np.isnan(v)
    wsum = np.where(valid, d, 0.0).sum(axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        ann = (np.where(valid, v, 0.0) * d).sum(axis=2) / wsum
    ann[wsum == 0] = np.nan
    return grid.years.reshape(n_years, 12)[:, 0], ann, valid.sum(axis=2)


def annual_spatial_sd(grid: RegionalGrid, annual: np.ndarray) -> np.ndarray:
    """Area-weighted SD across included cells of their annual means (per year)."""
    inc = ~grid.excluded
    a = annual[inc]
    w = grid.overlap_km2[inc][:, None]
    valid = ~np.isnan(a)
    wv = np.where(valid, w, 0.0)
    ws = wv.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.where(ws > 0, np.sum(np.where(valid, a, 0.0) * wv, axis=0) / ws, np.nan)
        return np.sqrt(np.where(ws > 0, np.sum(np.where(valid, (a - m) ** 2, 0.0) * wv, axis=0) / ws, np.nan))


def check_land_fraction(grid: RegionalGrid, variable: VariableDefinition, min_land_fraction: float) -> float | None:
    """For land-only variables: land fraction of the box; raises if too little land."""
    if not variable.land_only:
        return None
    land = float(grid.overlap_km2[~grid.excluded].sum()) / grid.box_km2 if grid.box_km2 > 0 else 0.0
    if land < min_land_fraction:
        raise LocationNotSupportedError(
            f"{variable.name} is not meaningful for this region.",
            [
                f"Only {land * 100:.0f}% of the box is ice-free land; soil wetness is constant (1.0) over oceans, "
                "large lakes and ice sheets.",
                "Select a region containing more land, or analyse a different variable.",
            ],
            suggested_variables=list(variable.alternatives),
        )
    return land

