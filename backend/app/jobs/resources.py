"""Resource tiers and background-analysis preflight.

Tiers (thresholds are settings, measured on the development machine — README
"Large-country resource budgets"):

SMALL       within the synchronous polygon limits; runs synchronously or as a job.
MEDIUM      background job.
LARGE       background job; chunked statistics with checkpoints (all jobs are chunked).
VERY_LARGE  only when the deployment explicitly enables it (``job_allow_very_large``)
            and the request fits that budget; otherwise rejected before any NASA call.

Estimates are labelled as such. Durations come from completed jobs on this
deployment when there are enough of them, otherwise from static benchmarks.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.config import Settings
from app.services.area_analysis import SECONDS_PER_CELL_TRENDS, SECONDS_PER_TILE

# Static benchmarks (development machine, 2026-11; see README). Used only when the
# deployment has no measured history yet.
SECONDS_PER_CELL_OVERLAP = 0.001       # exact polygon/cell intersection, per cell ...
SECONDS_PER_VERTEX_OVERLAP = 0.00022   # ... plus per boundary vertex (Canada, 297,180 vertices / 8,145 parts: 73 s)
MB_PER_VERTEX = 0.0006                 # shapely geometry + clipped cell parts (Canada peak 589 MB vs 413 MB without this term)
TILE_STORAGE_MB = 1.2                  # gzip JSON payload of a full 285-cell, 25-year tile
CELL_STORAGE_MB = 0.006                # cell row + statistics detail, gzip
BASE_MEMORY_MB = 250.0                 # Python, NumPy, SciPy, Shapely, pandas loaded

STAGE_DESCRIPTIONS = [
    ("PREPARING_GEOMETRY", "Load and validate the boundary or polygon (the exact version recorded at submission)."),
    ("CALCULATING_POLYGON_WEIGHTS", "Exact equal-area overlap of every NASA grid cell with the area."),
    ("PREPARING_NASA_REQUESTS", "Plan the NASA POWER regional tiles (2°–10° each) and store the manifest."),
    ("DOWNLOADING_NASA_DATA", "Fetch every tile (application-wide concurrency limit, retries with backoff)."),
    ("VALIDATING_DATA", "Check format, parameter, period, grid coordinates and units of every tile."),
    ("MERGING_GRID_CELLS", "Merge tiles; cells returned twice must agree and are counted once."),
    ("BUILDING_TIME_SERIES", "Polygon-weighted monthly means, day-weighted annual means, regional trend tests."),
    ("RUNNING_STATISTICS", "Trend tests for every grid cell, in checkpointed chunks."),
    ("CALCULATING_SPATIAL_FDR", "Benjamini–Hochberg / –Yekutieli over the complete eligible cell family."),
    ("GENERATING_RESULTS", "Write, verify and atomically publish result files and exports."),
]


def estimate_resources(pf: dict[str, Any], history: dict[str, Any] | None, settings: Settings, n_vertices: int = 0) -> dict[str, Any]:
    cells, tiles, values, months = pf["n_cells"], pf["n_tiles"], pf["n_values"], pf["n_months"]
    h = history or {}
    per_tile = h.get("seconds_per_tile") or SECONDS_PER_TILE
    per_cell_stats = h.get("seconds_per_cell_stats") or SECONDS_PER_CELL_TRENDS * months / 300
    rounds = math.ceil(tiles / max(1, settings.nasa_global_max_concurrency))
    download_s = rounds * per_tile
    stats_s = cells * per_cell_stats
    overlap_s = cells * SECONDS_PER_CELL_OVERLAP + n_vertices * SECONDS_PER_VERTEX_OVERLAP
    return {
        "basis": f"measured on this deployment ({h['n_jobs']} completed jobs)" if h.get("n_jobs") else
        "static benchmark from the development machine (no completed jobs measured here yet)",
        "download_seconds": round(download_s, 1),
        "processing_seconds": round(stats_s + overlap_s + cells * 0.002, 1),
        "total_seconds": round(download_s + stats_s + overlap_s + cells * 0.002, 1),
        "memory_mb": round(BASE_MEMORY_MB + values * 8 * 4 / 1e6 + cells * 0.006 + 60 + n_vertices * MB_PER_VERTEX, 0),
        "storage_mb": round(tiles * TILE_STORAGE_MB + cells * CELL_STORAGE_MB + 2, 1),
        "note": "Estimates, not guarantees: NASA POWER response times vary widely and other jobs share the request slots.",
    }


def classify(pf: dict[str, Any], est: dict[str, Any], settings: Settings) -> dict[str, Any]:
    cells, tiles, values = pf["n_cells"], pf["n_tiles"], pf["n_values"]
    reasons: list[str] = []
    if cells == 0:
        return {"tier": "BLOCKED", "eligible": False, "synchronous_available": False,
                "reasons": ["The area does not overlap any NASA grid cell."]}
    sync_ok = (cells <= settings.polygon_max_cells and tiles <= settings.polygon_max_tiles
               and values <= settings.polygon_max_values)
    if sync_ok:
        tier = "SMALL"
    elif cells <= settings.job_medium_max_cells and tiles <= settings.job_medium_max_tiles:
        tier = "MEDIUM"
    elif cells <= settings.job_large_max_cells and tiles <= settings.job_large_max_tiles and values <= settings.job_large_max_values:
        tier = "LARGE"
    else:
        tier = "VERY_LARGE"
    eligible = True
    if est["memory_mb"] > settings.job_max_memory_mb and tier != "VERY_LARGE":
        tier = "VERY_LARGE"
    if tier == "VERY_LARGE":
        if not settings.job_allow_very_large:
            eligible = False
            reasons.append("This analysis exceeds the LARGE background tier of this deployment "
                           f"(≤ {settings.job_large_max_cells:,} cells, ≤ {settings.job_large_max_tiles} NASA requests, "
                           f"≤ {settings.job_large_max_values:,} cell-months, ≤ {settings.job_max_memory_mb} MB estimated memory).")
        elif cells > settings.job_very_large_max_cells or tiles > settings.job_very_large_max_tiles:
            eligible = False
            reasons.append(f"It exceeds the VERY_LARGE budget ({settings.job_very_large_max_cells:,} cells, "
                           f"{settings.job_very_large_max_tiles} NASA requests).")
    if est["storage_mb"] > settings.job_max_storage_mb:
        eligible = False
        reasons.append(f"It needs about {est['storage_mb']:.0f} MB of result storage; the per-job limit is {settings.job_max_storage_mb} MB.")
    if tiles > settings.job_daily_tile_budget_per_session:
        eligible = False
        reasons.append(f"It needs {tiles} NASA requests; one session may use at most {settings.job_daily_tile_budget_per_session} per day.")
    return {"tier": tier, "eligible": eligible, "synchronous_available": sync_ok, "reasons": reasons}


def background_limits(settings: Settings) -> dict[str, Any]:
    return {
        "synchronous": {"max_cells": settings.polygon_max_cells, "max_tiles": settings.polygon_max_tiles,
                        "max_values": settings.polygon_max_values},
        "medium": {"max_cells": settings.job_medium_max_cells, "max_tiles": settings.job_medium_max_tiles},
        "large": {"max_cells": settings.job_large_max_cells, "max_tiles": settings.job_large_max_tiles,
                  "max_values": settings.job_large_max_values, "max_memory_mb": settings.job_max_memory_mb},
        "very_large_enabled": settings.job_allow_very_large,
        "max_storage_mb_per_job": settings.job_max_storage_mb,
        "nasa_global_max_concurrency": settings.nasa_global_max_concurrency,
        "nasa_min_request_interval_seconds": settings.nasa_min_request_interval_seconds,
        "max_active_jobs_per_session": settings.job_max_active_per_session,
        "max_submissions_per_hour": settings.job_max_submissions_per_hour,
        "daily_tile_budget_per_session": settings.job_daily_tile_budget_per_session,
    }
