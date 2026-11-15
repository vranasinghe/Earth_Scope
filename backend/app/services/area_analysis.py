"""Country and custom-polygon areas: specification, preflight budgets, tiled grid loading.

An ``AreaSpec`` plugs into the existing regional pipeline (``RegionalQuery.area``):
once the tiled grid is loaded with polygon overlap weights, the unchanged
area-weighted monthly aggregation, day-weighted annual aggregation, statistics
engine and per-cell spatial trend analysis run exactly as for rectangles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.catalog import VariableDefinition
from app.core.config import Settings
from app.services import area_geometry as ag
from app.services import boundaries
from app.services.nasa_power import NasaPowerClient
from app.services.regional_grid import BBox
from app.services.regional_tiling import Tile, fetch_tiles, merge_tiles, plan_tiles
from app.utils.errors import AnalysisTooLargeError, InvalidRequestError

SECONDS_PER_TILE = 3.0            # measured: one full-size tile, 25 years (1–4 s)
SECONDS_PER_CELL_TRENDS = 0.0065  # measured: per-cell statistics, 25 years (300 months)


@dataclass(frozen=True)
class AreaSpec:
    kind: str                       # "country" | "polygon"
    name: str
    geometry: Any                   # shapely Polygon / MultiPolygon (WGS84 lon/lat), used for all calculations
    geometry_id: str
    display: dict[str, Any]         # lightly simplified GeoJSON for drawing only
    area_km2: float                 # equal-area (spherical, consistent with the cell weights)
    geodesic_area_km2: float        # WGS84 ellipsoid (pyproj.Geod), for reference
    n_components: int
    n_vertices: int
    bbox: BBox
    iso3: str | None = None
    boundary: dict[str, Any] | None = None
    notes: tuple[str, ...] = ()


def area_from_request(iso3: str | None, geometry: dict[str, Any] | None, name: str | None, settings: Settings) -> AreaSpec:
    if bool(iso3) == bool(geometry):
        raise InvalidRequestError("Provide either a country code (iso3) or a polygon geometry, not both.")
    if iso3:
        c = boundaries.country_summary(iso3)
        m = c["meta"]
        boundary = {k: m.get(k) for k in ("source", "dataset", "version", "boundary_id", "year_represented", "license",
                                           "license_source", "upstream_source", "build_date", "attribution", "status",
                                           "reported_area_km2", "geometry_url")}
        return AreaSpec("country", m["name"], c["geometry"], c["geometry_id"], c["display"], c["area_km2"], c["geodesic_area_km2"],
                        c["n_components"], c["n_vertices"], ag.bbox_of(c["geometry"]), m["iso3"], boundary, tuple(c["notes"]))
    geom, notes = ag.parse_geometry(geometry, ag.GeometryLimits(settings.polygon_max_vertices, settings.polygon_max_parts))
    label = (name or "").strip()[:80] or "Custom polygon"
    return AreaSpec("polygon", label, geom, ag.geometry_id(geom), ag.display_geojson(geom, tolerance=0.0005, digits=5),
                    float(ag.equal_area_km2(geom)), ag.geodesic_area_km2(geom), ag.n_components(geom), ag.n_vertices(geom),
                    ag.bbox_of(geom), None, None, tuple(notes))


def preflight(area: AreaSpec, variable: VariableDefinition, start: int, end: int, settings: Settings) -> dict[str, Any]:
    """Everything that can be known before any NASA request: cells, tiles, data volume, budgets."""
    grid = ag.grid_for(variable)
    cells = ag.intersecting_cells(area.geometry, grid)
    tiles = plan_tiles(cells, grid)
    months = (end - start + 1) * 12
    values = len(cells) * months
    reasons = []
    if not cells:
        reasons.append("The area does not overlap any NASA grid cell.")
    if len(cells) > settings.polygon_max_cells:
        reasons.append(f"It intersects {len(cells)} NASA grid cells; the limit is {settings.polygon_max_cells}.")
    if len(tiles) > settings.polygon_max_tiles:
        reasons.append(f"It needs {len(tiles)} NASA regional requests; the limit is {settings.polygon_max_tiles}.")
    if values > settings.polygon_max_values:
        reasons.append(f"It needs {values:,} cell-month values; the limit is {settings.polygon_max_values:,}.")
    rounds = math.ceil(len(tiles) / max(1, settings.polygon_max_concurrency))
    mean_cell = area.area_km2 / len(cells) if cells else 0.0
    return {
        "valid": True,
        "available": not reasons,
        "reasons": reasons,
        "suggestions": [
            "Draw a custom polygon around a smaller part of the country.",
            "Use rectangle analysis for a 2°–9° sub-region.",
        ] + (["Shorten the time range (only if a shorter period still answers your question)."] if values > settings.polygon_max_values else [])
        if reasons else [],
        "n_cells": len(cells),
        "n_tiles": len(tiles),
        "n_months": months,
        "n_values": values,
        "estimated_seconds": round(rounds * SECONDS_PER_TILE + len(cells) * 0.002, 1),
        "estimated_spatial_seconds": round(len(cells) * SECONDS_PER_CELL_TRENDS * months / 300, 1),
        "estimated_memory_mb": round(values * 8 * 3 / 1e6 + len(tiles) * 12, 1),
        "mean_cell_overlap_km2": mean_cell,
        "small_area_warning": (
            "The area is smaller than a few NASA grid cells (≈ 55 × 69 km each); results describe the coarse cells it touches, "
            "weighted by the part inside the area, and cannot resolve detail within a cell."
        ) if cells and area.area_km2 < 3 * grid.cell_area_km2(0, 0) else None,
        "tiles": [{"tile": t.key, "lat_min": t.lat_min, "lat_max": t.lat_max, "lon_min": t.lon_min, "lon_max": t.lon_max,
                   "cells": t.n_needed} for t in tiles],
        "limits": {"max_cells": settings.polygon_max_cells, "max_tiles": settings.polygon_max_tiles,
                   "max_values": settings.polygon_max_values, "max_concurrency": settings.polygon_max_concurrency,
                   "max_vertices": settings.polygon_max_vertices},
        "grid": grid.name,
    }


def enforce_budget(pf: dict[str, Any]) -> None:
    if not pf["available"]:
        raise AnalysisTooLargeError(
            "This region requires more data than the current analysis limit supports." if pf["n_cells"] else pf["reasons"][0],
            pf["reasons"] + pf["suggestions"],
        )


@dataclass
class AreaGridResult:
    grid: Any
    payload: dict[str, Any]
    retrieved_at: str
    from_cache: bool
    manifest: list[dict[str, Any]]
    tiles: list[Tile]
    n_missing_cells: int


def load_area_grid(area: AreaSpec, variable: VariableDefinition, start: int, end: int, client: NasaPowerClient,
                   settings: Settings) -> AreaGridResult:
    pf = preflight(area, variable, start, end, settings)
    enforce_budget(pf)
    grid_spec = ag.grid_for(variable)
    overlaps = ag.cell_overlaps(area.geometry, grid_spec)
    if not overlaps:
        raise AnalysisTooLargeError("The area does not overlap any NASA grid cell with positive area.")
    tiles = plan_tiles([(c.i, c.j) for c in overlaps], grid_spec)
    results = fetch_tiles(client, variable, tiles, start, end, concurrency=settings.polygon_max_concurrency,
                          retries=settings.polygon_tile_retries, backoff=settings.polygon_retry_backoff_seconds)
    merged = merge_tiles(results, variable, overlaps, grid_spec, start, end, area.area_km2)
    total_overlap = float(np.sum(merged.grid.overlap_km2))
    if abs(total_overlap - area.area_km2) > 1e-6 * max(1.0, area.area_km2):
        merged.grid.warnings.append(
            f"The grid cells cover {total_overlap / area.area_km2 * 100:.3f}% of the polygon area (sliver cells below 1e-6 km² are ignored)."
        )
    return AreaGridResult(merged.grid, merged.header_payload, max(r.retrieved_at for r in results),
                          all(r.from_cache for r in results), merged.manifest, tiles, merged.n_missing_cells)
