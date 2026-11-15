"""Regional trend analysis: NASA regional grid → area-weighted series → existing statistics.

The statistics are NOT re-implemented: the area-weighted monthly regional series
is aggregated to annual values with ``data_processing.aggregate_annual`` (the same
day-weighting and ≥10-valid-month rule as point analysis) and passed to
``trend_analysis.run_trend_analysis`` (OLS, Mann-Kendall, modified tests, Sen's
slope + CI, autocorrelation diagnostics, HAC). The trend is that of the
REGIONAL MEAN SERIES, not an average of per-cell slopes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.catalog import POWER_MONTHLY_DOCS, POWER_PARAMETER_DOCS, VariableDefinition
from app.core.config import Settings
from app.services import data_processing as dp
from app.services import regional_aggregation as ra
from app.services.interpretation import build_interpretation
from app.services.nasa_power import NasaPowerClient, TTLCache
from app.services.regional_grid import BBox, cell_bounds, request_box
from app.services.trend_analysis import run_trend_analysis
from app.utils.errors import DataUnavailableError, StatisticsError

logger = logging.getLogger(__name__)

AGGREGATION_METHOD = (
    "Area-weighted mean over the bounding box: each MERRA-2 cell (0.5° × 0.625°) is weighted by the exact "
    "spherical area of its overlap with the box (partial cells count only for the part inside). Only valid "
    "cell values are used each month."
)

_results_cache = TTLCache(ttl_seconds=6 * 3600, max_entries=64)


@dataclass(frozen=True)
class RegionalQuery:
    variable: VariableDefinition
    bbox: BBox
    start_year: int
    end_year: int
    coverage_threshold: float
    # Country / custom polygon (area_analysis.AreaSpec). None = the rectangle ``bbox`` itself.
    area: Any = None

    @property
    def area_key(self) -> str | None:
        return self.area.geometry_id if self.area is not None else None


def _none(v: float) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


@dataclass
class LoadedGrid:
    """A parsed regional grid plus the provenance of the payload it came from."""

    grid: ra.RegionalGrid
    payload: dict[str, Any]
    retrieved_at: str
    request_url: str | None
    from_cache: bool
    land_fraction: float | None
    manifest: list[dict[str, Any]] | None = None   # tiled (country / polygon) requests
    n_missing_cells: int = 0


def load_regional_grid(q: RegionalQuery, client: NasaPowerClient, settings: Settings) -> LoadedGrid:
    """Fetch live NASA data (using the client's raw-response cache) and parse the grid.

    Shared by the regional-mean analysis and the per-cell spatial trend analysis,
    so both use exactly the same request, parsing, fill-value and land-only rules.
    Country / polygon areas are fetched as NASA tiles and weighted by polygon overlap.
    """
    var = q.variable
    if q.area is not None:
        from app.services.area_analysis import load_area_grid  # local import avoids a cycle

        r = load_area_grid(q.area, var, q.start_year, q.end_year, client, settings)
        land_fraction = ra.check_land_fraction(r.grid, var, settings.regional_min_land_fraction)
        return LoadedGrid(r.grid, r.payload, r.retrieved_at, None, r.from_cache, land_fraction, r.manifest, r.n_missing_cells)
    req = request_box(q.bbox)
    fetched = client.fetch_regional(var, req.lat_min, req.lat_max, req.lon_min, req.lon_max, q.start_year, q.end_year)
    payload, retrieved_at, request_url, from_cache = fetched.payload, fetched.retrieved_at, fetched.request_url, fetched.from_cache
    grid = ra.parse_regional_response(payload, var, q.bbox, q.start_year, q.end_year)
    land_fraction = ra.check_land_fraction(grid, var, settings.regional_min_land_fraction)
    return LoadedGrid(grid, payload, retrieved_at, request_url, from_cache, land_fraction)


def build_regional_response(
    q: RegionalQuery, client: NasaPowerClient, settings: Settings, analyze: bool = True
) -> dict[str, Any]:
    cache_key = (q.variable.id, q.bbox, q.area_key, q.start_year, q.end_year, round(q.coverage_threshold, 4), analyze,
                 settings.min_valid_months_per_year, settings.min_annual_records)
    cached = _results_cache.get(cache_key)
    if cached is not None:
        return {**cached, "metadata": {**cached["metadata"], "served_from_cache": True}}

    loaded = load_regional_grid(q, client, settings)
    result = build_regional_from_loaded(q, loaded, settings, analyze)
    _results_cache.set(cache_key, result)
    return result


def build_regional_from_loaded(q: RegionalQuery, loaded: LoadedGrid, settings: Settings,
                               analyze: bool = True) -> dict[str, Any]:
    """Regional-mean response from an already loaded grid (no NASA call, no caching).

    Used by the synchronous endpoint (after ``load_regional_grid``) and by the
    background worker (after merging checkpointed tiles), so both execution paths
    run the identical aggregation and statistics code.
    """
    var = q.variable
    grid, land_fraction = loaded.grid, loaded.land_fraction
    monthly_stats = ra.weighted_monthly(grid, q.coverage_threshold)
    if not np.any(monthly_stats["status"] == "valid"):
        raise DataUnavailableError(
            "No month has enough valid grid cells to compute a reliable regional mean.",
            [f"At least {q.coverage_threshold * 100:.0f}% of the analysed area must have valid data each month."],
        )

    # --- Monthly regional series (records + frame for the existing annual aggregation) ---
    rows = []
    for t in range(len(grid.years)):
        st = str(monthly_stats["status"][t])
        rows.append({
            "date": f"{int(grid.years[t]):04d}-{int(grid.months[t]):02d}",
            "year": int(grid.years[t]),
            "month": int(grid.months[t]),
            "value": _none(monthly_stats["mean"][t]) if st == "valid" else None,
            "computed_mean": _none(monthly_stats["mean"][t]),
            "status": st,
            "spatial_sd": _none(monthly_stats["sd"][t]),
            "min_value": _none(monthly_stats["min"][t]),
            "max_value": _none(monthly_stats["max"][t]),
            "valid_cells": int(monthly_stats["n_valid"][t]),
            "missing_cells": int(monthly_stats["n_missing"][t]),
            "valid_area_km2": float(monthly_stats["valid_area_km2"][t]),
            "coverage": float(monthly_stats["coverage"][t]),
        })
    monthly_df = pd.DataFrame(
        [{"year": r["year"], "month": r["month"], "value": r["value"], "status": "valid" if r["status"] == "valid" else "missing"} for r in rows]
    )
    annual_df = dp.aggregate_annual(monthly_df, settings.min_valid_months_per_year)

    cell_years, cell_annual = ra.cell_annual_means(grid, settings.min_valid_months_per_year)
    annual_sd = ra.annual_spatial_sd(grid, cell_annual)
    annual = [
        {
            "year": int(r.year),
            "value": _none(r.value),
            "valid_months": int(r.valid_months),
            "total_months": 12,
            "status": r.status,
            "used_in_trend": bool(r.used_in_trend),
            "spatial_sd": _none(annual_sd[i]),
        }
        for i, r in enumerate(annual_df.itertuples(index=False))
    ]

    # --- Grid-cell metadata (compact; no raw monthly matrix sent to the browser) ---
    weights = grid.overlap_km2 / grid.overlap_km2[~grid.excluded].sum() if (~grid.excluded).any() else grid.overlap_km2 * 0
    cells = []
    for i in range(len(grid.lats)):
        row = grid.values[i]
        n_valid = int(np.sum(~np.isnan(row)))
        la0, la1, lo0, lo1 = cell_bounds(grid.lats[i], grid.lons[i])
        if grid.excluded[i]:
            status = "excluded"
        elif n_valid == 0:
            status = "missing"
        elif n_valid < row.size:
            status = "partial"
        else:
            status = "valid"
        valid_years = cell_annual[i][~np.isnan(cell_annual[i])]
        cells.append({
            "latitude": float(grid.lats[i]),
            "longitude": float(grid.lons[i]),
            "lat_min": la0, "lat_max": la1, "lon_min": lo0, "lon_max": lo1,
            "cell_area_km2": float(grid.cell_km2[i]),
            "overlap_area_km2": float(grid.overlap_km2[i]),
            "overlap_fraction": float(grid.overlap_km2[i] / grid.cell_km2[i]) if grid.cell_km2[i] > 0 else 0.0,
            "weight": float(weights[i]) if not grid.excluded[i] else 0.0,
            "status": status,
            "exclusion_reason": grid.exclusion_reason[i],
            "valid_months": n_valid,
            "total_months": int(row.size),
            "period_mean": float(valid_years.mean()) if valid_years.size else None,
            "annual": [_none(v) for v in cell_annual[i]],
            # Polygon mode: the part of the cell inside the area (None = whole cell / rectangle mode).
            "clip": grid.clips[i] if grid.clips is not None else None,
        })

    n_valid_months = int(np.sum(monthly_stats["status"] == "valid"))
    n_insufficient = int(np.sum(monthly_stats["status"] == "insufficient_coverage"))
    latest_full = None
    full_years = [a["year"] for a in annual if a["valid_months"] == 12]
    if full_years:
        latest_full = max(full_years)

    warnings = list(grid.warnings)
    incomplete = [a["year"] for a in annual if not a["used_in_trend"]]
    if n_insufficient:
        warnings.append(
            f"{n_insufficient} month(s) had valid data for less than {q.coverage_threshold * 100:.0f}% of the analysed "
            "area and were excluded from the regional series."
        )
    if incomplete:
        warnings.append(
            f"{len(incomplete)} year(s) have fewer than {settings.min_valid_months_per_year} valid regional months and "
            f"are excluded from the trend tests: {', '.join(map(str, incomplete[:8]))}{'…' if len(incomplete) > 8 else ''}."
        )
    if land_fraction is not None and grid.excluded.any():
        warnings.append(
            f"{int(grid.excluded.sum())} water or ice cell(s) were excluded; {var.name} is averaged over the "
            f"{land_fraction * 100:.0f}% of the {'box' if q.area is None else 'area'} that is ice-free land."
        )

    metadata = regional_metadata(q, loaded, latest_full)
    summary = {
        "n_monthly_total": len(rows),
        "n_monthly_valid": n_valid_months,
        "n_monthly_missing": len(rows) - n_valid_months,
        "n_monthly_insufficient": n_insufficient,
        "n_annual_total": len(annual),
        "n_annual_complete": sum(1 for a in annual if a["status"] == "complete"),
        "n_annual_used": sum(1 for a in annual if a["used_in_trend"]),
        "min_valid_months_per_year": settings.min_valid_months_per_year,
        "mean_coverage": float(np.mean(monthly_stats["coverage"])),
    }
    return _finish_regional(q, settings, analyze, metadata, rows, annual, annual_df, summary, cells, cell_years, warnings)


def regional_metadata(q: RegionalQuery, loaded: LoadedGrid, latest_full: int | None) -> dict[str, Any]:
    """Provenance block shared by the regional-mean and spatial-trend responses."""
    var, req, grid, payload = q.variable, request_box(q.bbox), loaded.grid, loaded.payload
    land_fraction, retrieved_at, request_url, from_cache = loaded.land_fraction, loaded.retrieved_at, loaded.request_url, loaded.from_cache
    returned_lats = [float(f["geometry"]["coordinates"][1]) for f in payload.get("features", []) if f.get("geometry")]
    returned_lons = [float(f["geometry"]["coordinates"][0]) for f in payload.get("features", []) if f.get("geometry")]
    if not returned_lats and payload.get("returned_extent"):   # tiled areas: extent computed while merging
        e = payload["returned_extent"]
        returned_lats, returned_lons = [e["lat_min"], e["lat_max"]], [e["lon_min"], e["lon_max"]]
    meta = {
        "data_mode": "LIVE",
        "provider": "NASA POWER (Prediction Of Worldwide Energy Resources), NASA Langley Research Center",
        "dataset_title": grid.dataset_title,
        "api_version": grid.api_version,
        "variable_id": var.id,
        "variable_name": var.name,
        "parameter": var.parameter,
        "long_name": grid.long_name,
        "community": var.community,
        "sources": grid.sources,
        "units_raw": grid.units_raw,
        "unit_display": var.unit_display if grid.units_raw in (None, var.expected_unit) else grid.units_raw,
        "rate_unit": var.rate_unit if grid.units_raw in (None, var.expected_unit) else f"{grid.units_raw}/year",
        "temporal_resolution": "monthly",
        "time_standard": grid.time_standard,
        "start_year": q.start_year,
        "end_year": q.end_year,
        "latest_complete_year": latest_full,
        "bbox": {"lat_min": q.bbox.lat_min, "lat_max": q.bbox.lat_max, "lon_min": q.bbox.lon_min, "lon_max": q.bbox.lon_max},
        "request_bbox": {"lat_min": req.lat_min, "lat_max": req.lat_max, "lon_min": req.lon_min, "lon_max": req.lon_max},
        "returned_extent": {
            "lat_min": min(returned_lats), "lat_max": max(returned_lats),
            "lon_min": min(returned_lons), "lon_max": max(returned_lons),
        } if returned_lats else None,
        "region_area_km2": grid.box_km2,
        "analysed_area_km2": ra.analysed_area_km2(grid),
        "land_fraction": land_fraction,
        "grid_resolution": "MERRA-2 native grid: 0.5° latitude × 0.625° longitude",
        "n_cells_returned": grid.n_features,
        "n_cells_used": int((~grid.excluded).sum()),
        "n_cells_excluded": int(grid.excluded.sum()),
        "n_cells_outside": grid.n_outside,
        "n_duplicates": grid.n_duplicates,
        "aggregation_method": AGGREGATION_METHOD,
        "partial_cell_rule": "Overlap-area weighting: cells cut by the box edge are weighted by their area inside the box. "
        "The NASA request is expanded by half a cell per side so these edge cells are retrieved.",
        "coverage_threshold": q.coverage_threshold,
        "fill_value": grid.fill_value,
        "retrieved_at": retrieved_at,
        "served_from_cache": from_cache,
        "request_url": request_url,
        "documentation_url": POWER_MONTHLY_DOCS,
        "parameter_docs_url": POWER_PARAMETER_DOCS,
        "source_note": var.source_note,
        "area_mode": "rectangle",
    }
    a = q.area
    if a is None:
        return meta
    manifest = loaded.manifest or []
    tile_boxes = [(t["lat_min"], t["lat_max"], t["lon_min"], t["lon_max"]) for t in manifest]
    total_overlap = float(np.sum(grid.overlap_km2))
    meta.update({
        "area_mode": a.kind,
        "area_name": a.name,
        "iso3": a.iso3,
        "geometry_id": a.geometry_id,
        "geometry": a.display,
        "boundary": a.boundary,
        "geometry_notes": list(a.notes),
        "polygon_area_km2": a.area_km2,
        "geodesic_area_km2": a.geodesic_area_km2,
        "n_components": a.n_components,
        "n_vertices": a.n_vertices,
        "request_manifest": manifest,
        "n_tiles": len(manifest),
        "n_cells_missing_from_response": loaded.n_missing_cells,
        "grid_representability": total_overlap / a.area_km2 if a.area_km2 > 0 else None,
        "request_bbox": {
            "lat_min": min(b[0] for b in tile_boxes), "lat_max": max(b[1] for b in tile_boxes),
            "lon_min": min(b[2] for b in tile_boxes), "lon_max": max(b[3] for b in tile_boxes),
        } if tile_boxes else meta["request_bbox"],
        "aggregation_method": (
            "Polygon-weighted mean: each MERRA-2 cell (0.5° × 0.625°) is weighted by the equal-area (spherical) size of its "
            "intersection with the " + ("country boundary" if a.kind == "country" else "polygon") +
            " — holes and separate parts respected. Only valid cell values are used each month."
        ),
        "partial_cell_rule": "Cells cut by the boundary count only for their area inside it (exact polygon–cell intersection). "
        "The area is fetched as NASA regional tiles (2°–10° each); cells returned by several tiles are counted once.",
    })
    return meta


def _finish_regional(
    q: RegionalQuery, settings: Settings, analyze: bool, metadata: dict[str, Any],
    rows: list, annual: list, annual_df: pd.DataFrame, summary: dict[str, Any], cells: list, cell_years: np.ndarray,
    warnings: list[str],
) -> dict[str, Any]:
    var = q.variable
    result: dict[str, Any] = {
        "metadata": metadata,
        "monthly": rows,
        "annual": annual,
        "summary": summary,
        "cells": cells,
        "cell_years": [int(y) for y in cell_years],
        "warnings": warnings,
    }

    if analyze:
        statistics, message, error = None, None, None
        try:
            statistics = run_trend_analysis(
                annual_df, alpha=settings.significance_alpha, confidence_level=settings.confidence_level,
                min_records=settings.min_annual_records,
            )
        except StatisticsError as exc:
            message, error = str(exc), exc.code
        b = q.bbox
        box_text = f"{b.lat_min:g}° to {b.lat_max:g}° latitude, {b.lon_min:g}° to {b.lon_max:g}° longitude"
        result["statistics"] = statistics
        result["analysis_message"] = message
        result["analysis_error"] = error
        a = q.area
        if a is None:
            phrase = f"the selected region ({box_text}; area-weighted mean of {metadata['n_cells_used']} grid cells)"
            caveat = ("This is an area-weighted average over the selected rectangle, not over a country, city, administrative "
                      "or ecological boundary. Conditions within the rectangle can differ from the regional mean.")
        elif a.kind == "country":
            src = (a.boundary or {}).get("source", "boundary dataset")
            phrase = (f"the selected country boundary of {a.name} ({src}; polygon-weighted mean of "
                      f"{metadata['n_cells_used']} NASA grid cells)")
            caveat = (f"This is an area-weighted average within the {src} boundary of {a.name} "
                      f"({(a.boundary or {}).get('version', '')}). Another boundary dataset (or another treatment of disputed or "
                      "overseas territories) can give slightly different results, and the ~55 km NASA grid cannot resolve "
                      "features smaller than a cell. Conditions inside the country can differ from this mean.")
        else:
            phrase = f"the selected polygon '{a.name}' (polygon-weighted mean of {metadata['n_cells_used']} NASA grid cells)"
            caveat = ("This is an area-weighted average within the drawn polygon. Cells cut by its edge count only for the part "
                      "inside; the ~55 km NASA grid cannot resolve details smaller than a cell.")
        result["interpretation"] = build_interpretation(
            var, statistics, (b.lat_min + b.lat_max) / 2, (b.lon_min + b.lon_max) / 2, q.start_year, q.end_year,
            summary["n_annual_total"] - summary["n_annual_used"], message,
            location_phrase=phrase,
            scope_caveat=caveat,
        )

    return result
