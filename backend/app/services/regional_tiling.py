"""Tiled NASA POWER regional retrieval for areas larger than one regional request.

Verified live (2026-11): a monthly regional request must span ≥ 2° and ≤ 10°
in both latitude and longitude, carries ONE parameter, and returns every
MERRA-2 centre inside the closed box. The grid has a centre at −180° but none
at +180°, so the cell straddling the date line is requested from the −180 side.

Plan
----
1. The geometry engine lists the exact cells the area needs (no NASA call).
2. Cells are grouped into fixed grid blocks of at most N_lat × N_lon cells
   (19 × 15 for MERRA-2 under the 10° limit). Each block that contains needed
   cells becomes one request whose edges lie halfway between cell centres, so
   no centre sits on a tile edge.
3. Tiles narrower than 2° are widened symmetrically (inside ±90° / ±180°); the
   extra cells they return are discarded because they are not needed.
4. Tiles are fetched with bounded concurrency, retries with exponential backoff
   and the client's timeout / cache. If any tile still fails, the whole
   analysis fails with INCOMPLETE_TILE_RETRIEVAL — never a partial result.
5. Returned centres are mapped to integer grid indices. A cell returned by
   several tiles must carry identical values (it is counted once); a conflict
   or an off-grid centre is an error.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np

from app.core.catalog import VariableDefinition
from app.services.area_geometry import CellOverlap, GridSpec
from app.services.data_processing import DEFAULT_FILL_VALUE, extract_metadata
from app.services.nasa_power import NasaPowerClient
from app.services.regional_aggregation import RegionalGrid, parse_series_row
from app.utils.errors import EarthScopeError, IncompleteTileRetrievalError, NasaPowerResponseError

logger = logging.getLogger(__name__)
NASA_MIN_SPAN = 2.0
NASA_MAX_SPAN = 10.0


@dataclass(frozen=True)
class Tile:
    key: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    n_needed: int


def cells_per_tile(grid: GridSpec, max_span: float = NASA_MAX_SPAN) -> tuple[int, int]:
    """Largest block whose half-cell-padded box stays strictly inside the NASA maximum span."""
    return int(math.floor(max_span / grid.lat_step + 1e-9)) - 1, int(math.floor(max_span / grid.lon_step + 1e-9)) - 1


def _expand(lo: float, hi: float, min_span: float, floor_: float, ceil_: float) -> tuple[float, float]:
    span = hi - lo
    if span >= min_span:
        return lo, hi
    pad = (min_span - span) / 2
    lo, hi = lo - pad, hi + pad
    if lo < floor_:
        hi, lo = hi + (floor_ - lo), floor_
    if hi > ceil_:
        lo, hi = lo - (hi - ceil_), ceil_
    return max(lo, floor_), min(hi, ceil_)


def plan_tiles(cells: list[tuple[int, int]], grid: GridSpec, max_span: float = NASA_MAX_SPAN,
               min_span: float = NASA_MIN_SPAN) -> list[Tile]:
    n_lat, n_lon = cells_per_tile(grid, max_span)
    if not cells:
        return []
    # Blocks are anchored at the area's first cell (not a global grid) so a small area is not split by block edges.
    i_ref = min(i for i, _ in cells)
    j_ref = min(j for _, j in cells)
    blocks: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for i, j in cells:
        blocks[((i - i_ref) // n_lat, (j - j_ref) // n_lon)].append((i, j))
    tiles = []
    for (bi, bj), members in sorted(blocks.items()):
        ii = [i for i, _ in members]
        jj = [j for _, j in members]
        la_lo = grid.lat0 + min(ii) * grid.lat_step - grid.lat_step / 2
        la_hi = grid.lat0 + max(ii) * grid.lat_step + grid.lat_step / 2
        lo_lo = grid.lon0 + min(jj) * grid.lon_step - grid.lon_step / 2
        lo_hi = grid.lon0 + max(jj) * grid.lon_step + grid.lon_step / 2
        la_lo, la_hi = max(-90.0, la_lo), min(90.0, la_hi)
        lo_lo, lo_hi = max(-180.0, lo_lo), min(180.0, lo_hi)
        la_lo, la_hi = _expand(la_lo, la_hi, min_span, -90.0, 90.0)
        lo_lo, lo_hi = _expand(lo_lo, lo_hi, min_span, -180.0, 180.0)
        assert la_hi - la_lo <= max_span + 1e-9 and lo_hi - lo_lo <= max_span + 1e-9
        tiles.append(Tile(f"T{len(tiles) + 1:02d}", round(la_lo, 4), round(la_hi, 4), round(lo_lo, 4), round(lo_hi, 4), len(members)))
    return tiles


@dataclass
class TileResult:
    tile: Tile
    payload: dict[str, Any]
    url: str | None
    retrieved_at: str
    from_cache: bool
    attempts: int
    n_features: int = 0


def fetch_tiles(
    client: NasaPowerClient, variable: VariableDefinition, tiles: list[Tile], start: int, end: int, *,
    concurrency: int, retries: int, backoff: float,
    sleep: Callable[[float], None] = time.sleep,
) -> list[TileResult]:
    def one(t: Tile) -> TileResult | EarthScopeError:
        last: EarthScopeError | None = None
        for attempt in range(retries + 1):
            try:
                f = client.fetch_regional(variable, t.lat_min, t.lat_max, t.lon_min, t.lon_max, start, end)
                feats = f.payload.get("features")
                if not isinstance(feats, list):
                    raise NasaPowerResponseError("NASA POWER returned a regional response without grid data.")
                return TileResult(t, f.payload, f.request_url, f.retrieved_at, f.from_cache, attempt + 1, len(feats))
            except EarthScopeError as exc:
                last = exc
                if not exc.retryable or attempt == retries:
                    break
                sleep(backoff * (2 ** attempt))
        return last  # type: ignore[return-value]

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, tiles))
    failed = [(t, r) for t, r in zip(tiles, results) if isinstance(r, EarthScopeError)]
    if failed:
        non_retryable = [r for _, r in failed if not r.retryable]
        if non_retryable:
            raise non_retryable[0]
        raise IncompleteTileRetrievalError(
            f"{len(failed)} of {len(tiles)} NASA POWER requests failed after {retries + 1} attempt(s); "
            "no result is shown because part of the area would be missing.",
            [f"{t.key} (lat {t.lat_min}…{t.lat_max}, lon {t.lon_min}…{t.lon_max}): {r.message}" for t, r in failed[:8]],
        )
    return [r for r in results if isinstance(r, TileResult)]


@dataclass
class MergedTiles:
    grid: RegionalGrid
    n_returned: int
    n_duplicates: int
    n_outside: int
    n_missing_cells: int
    manifest: list[dict[str, Any]] = field(default_factory=list)
    header_payload: dict[str, Any] = field(default_factory=dict)


def merge_tiles(results: Iterable[TileResult], variable: VariableDefinition, overlaps: list[CellOverlap], grid_spec: GridSpec,
                start: int, end: int, area_km2: float) -> MergedTiles:
    """Merge tile responses into one RegionalGrid holding exactly the needed cells, each once.

    ``results`` is consumed once, in order, and no payload is retained after its
    tile has been parsed, so a background worker can stream tile checkpoints from
    disk one at a time (bounded memory) and get exactly the synchronous result.
    """
    needed = {(c.i, c.j): k for k, c in enumerate(overlaps)}
    years = np.repeat(np.arange(start, end + 1), 12)
    months = np.tile(np.arange(1, 13), end - start + 1)
    rows: list[np.ndarray | None] = [None] * len(overlaps)
    n_returned = n_dup = n_out = n_invalid = 0
    units_seen: set[str | None] = set()
    meta = None
    manifest = []
    header: dict[str, Any] | None = None
    ext = [math.inf, -math.inf, math.inf, -math.inf]   # returned centre extent: lat min/max, lon min/max
    for r in results:
        m = extract_metadata({**r.payload, "geometry": {}}, variable.parameter)
        meta = meta or m
        if header is None:
            header = {"header": r.payload.get("header", {}), "parameters": r.payload.get("parameters", {})}
        units_seen.add(m.units_raw)
        fill = m.fill_value if m.fill_value is not None else DEFAULT_FILL_VALUE
        check_range = m.units_raw in (None, variable.expected_unit)
        n_in_tile = 0
        for f in r.payload.get("features", []):
            try:
                lon, lat = float(f["geometry"]["coordinates"][0]), float(f["geometry"]["coordinates"][1])
                series = f["properties"]["parameter"][variable.parameter]
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            n_returned += 1
            ext = [min(ext[0], lat), max(ext[1], lat), min(ext[2], lon), max(ext[3], lon)]
            idx = grid_spec.index(lat, lon)
            if idx is None:
                raise NasaPowerResponseError(
                    "NASA POWER returned a grid cell that is not on the expected grid.",
                    [f"Centre {lat}, {lon} does not match {grid_spec.name}."],
                )
            k = needed.get(idx)
            if k is None:
                n_out += 1
                continue
            row, bad = parse_series_row(series if isinstance(series, dict) else {}, years, months, fill, check_range, variable)
            n_invalid += bad
            if rows[k] is not None:
                same = np.array_equal(np.isnan(rows[k]), np.isnan(row)) and np.allclose(rows[k], row, equal_nan=True, atol=1e-9)
                if not same:
                    raise NasaPowerResponseError(
                        "Two NASA POWER tiles returned different values for the same grid cell.",
                        [f"Cell {grid_spec.centre(*idx)} differs between tiles; the data cannot be merged safely."],
                    )
                n_dup += 1
                continue
            rows[k] = row
            n_in_tile += 1
        manifest.append({
            "tile": r.tile.key, "lat_min": r.tile.lat_min, "lat_max": r.tile.lat_max, "lon_min": r.tile.lon_min,
            "lon_max": r.tile.lon_max, "url": r.url, "retrieved_at": r.retrieved_at, "from_cache": r.from_cache,
            "attempts": r.attempts, "cells_returned": r.n_features, "cells_used": n_in_tile,
        })
    if len(units_seen) > 1:
        raise NasaPowerResponseError("NASA POWER tiles reported different units for the same parameter.", [str(sorted(map(str, units_seen)))])
    missing = [k for k, row in enumerate(rows) if row is None]
    values = np.vstack([row if row is not None else np.full(len(years), np.nan) for row in rows])

    excluded = np.zeros(len(overlaps), dtype=bool)
    reasons: list[str | None] = [None] * len(overlaps)
    if variable.land_only:
        for k, row in enumerate(values):
            valid = row[~np.isnan(row)]
            if valid.size and np.allclose(valid, 1.0):
                excluded[k], reasons[k] = True, "water_or_ice"

    assert meta is not None
    grid = RegionalGrid(
        lats=np.array([c.lat for c in overlaps]), lons=np.array([c.lon for c in overlaps]), values=values, years=years, months=months,
        overlap_km2=np.array([c.overlap_km2 for c in overlaps]), cell_km2=np.array([c.cell_km2 for c in overlaps]),
        excluded=excluded, exclusion_reason=reasons, box_km2=area_km2, units_raw=meta.units_raw, sources=meta.sources,
        fill_value=meta.fill_value if meta.fill_value is not None else DEFAULT_FILL_VALUE, dataset_title=meta.dataset_title,
        api_version=meta.api_version, time_standard=meta.time_standard, long_name=meta.long_name,
        n_features=n_returned, n_duplicates=n_dup, n_outside=n_out, n_invalid_values=n_invalid,
        clips=[c.clip for c in overlaps],
    )
    if n_dup:
        grid.warnings.append(f"{n_dup} grid cell(s) were returned by more than one NASA tile; each was counted once (values were identical).")
    if missing:
        grid.warnings.append(
            f"{len(missing)} grid cell(s) inside the area were not returned by NASA POWER; they are treated as missing data and lower the coverage."
        )
    if n_invalid:
        grid.warnings.append(f"{n_invalid} cell-month value(s) outside the physically valid range were excluded.")
    if meta.units_raw is not None and meta.units_raw != variable.expected_unit:
        grid.warnings.append(f"NASA POWER reported units '{meta.units_raw}' (expected '{variable.expected_unit}'); values are shown as reported.")
    # Provenance header of the first tile plus the returned extent (the raw features are not kept in memory).
    header_payload = {**(header or {}), "features": [],
                      "returned_extent": {"lat_min": ext[0], "lat_max": ext[1], "lon_min": ext[2], "lon_max": ext[3]} if n_returned else None}
    return MergedTiles(grid, n_returned, n_dup, n_out, len(missing), manifest, header_payload)


def validate_tile_payload(payload: Any, variable: VariableDefinition, tile: Tile, start: int, end: int,
                          grid_spec: GridSpec, latest_partial_year: int | None = None) -> dict[str, Any]:
    """Verify one regional tile before it is checkpointed (background jobs).

    Checks the response format, parameter identity (exactly the requested
    parameter, nothing else), that every centre lies on the source grid inside
    the requested box, and the temporal coverage: every month of every
    requested year must be present as a key, except in ``latest_partial_year``
    (the current year, which NASA publishes with a lag). Missing *values*
    (fill values) are allowed and counted — they become NaN exactly as in the
    synchronous path. An HTML error page or truncated JSON never gets here
    (the client rejects it), and anything malformed raises
    ``NasaPowerResponseError`` instead of being stored.
    """
    def bad(msg: str) -> NasaPowerResponseError:
        return NasaPowerResponseError(f"NASA POWER returned an invalid regional tile ({msg}).", [f"Tile {tile.key}"])

    if not isinstance(payload, dict):
        raise bad("not a JSON object")
    feats = payload.get("features")
    if not isinstance(feats, list) or not feats:
        raise bad("no grid cells")
    params = payload.get("parameters")
    if isinstance(params, dict) and params and set(params) != {variable.parameter}:
        raise bad(f"parameters {sorted(params)} instead of {variable.parameter}")
    meta = extract_metadata({**payload, "geometry": {}}, variable.parameter)
    fill = meta.fill_value if meta.fill_value is not None else DEFAULT_FILL_VALUE
    expected = {f"{y}{m:02d}" for y in range(start, end + 1) for m in range(1, 13)
                if latest_partial_year is None or y < latest_partial_year}
    tol = 1e-6
    n_missing = n_values = 0
    for f in feats:
        try:
            lon, lat = float(f["geometry"]["coordinates"][0]), float(f["geometry"]["coordinates"][1])
            series_all = f["properties"]["parameter"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise bad("a grid cell without coordinates or values") from None
        if not isinstance(series_all, dict) or set(series_all) != {variable.parameter}:
            raise bad("a grid cell with the wrong parameter")
        series = series_all[variable.parameter]
        if not isinstance(series, dict):
            raise bad("a grid cell without a monthly series")
        if grid_spec.index(lat, lon) is None:
            raise bad(f"centre {lat}, {lon} is not on the {grid_spec.name}")
        if not (tile.lat_min - tol <= lat <= tile.lat_max + tol and tile.lon_min - tol <= lon <= tile.lon_max + tol):
            raise bad(f"centre {lat}, {lon} lies outside the requested box")
        missing_keys = expected - set(series)
        if missing_keys:
            raise bad(f"{len(missing_keys)} requested month(s) absent, e.g. {min(missing_keys)}")
        for k in expected:
            v = series.get(k)
            n_values += 1
            if v is None or (isinstance(v, (int, float)) and math.isclose(float(v), fill, abs_tol=1e-6)):
                n_missing += 1
    return {
        "n_features": len(feats), "n_values_checked": n_values, "n_missing_values": n_missing,
        "units": meta.units_raw, "api_version": meta.api_version, "sources": meta.sources,
        "dataset_title": meta.dataset_title, "fill_value": fill, "parameter": variable.parameter,
    }
