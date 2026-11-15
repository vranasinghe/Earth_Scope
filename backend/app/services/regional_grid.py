"""Bounding-box geometry for regional analysis on the MERRA-2 grid.

Verified against the live NASA POWER monthly regional endpoint (v2.10.0):

* Each request must span at least 2° and at most 10° in BOTH latitude and
  longitude; boxes with longitude-min > longitude-max (antimeridian
  crossing) are rejected by NASA.
* The response contains one feature per MERRA-2 cell whose CENTRE lies inside
  the closed request box (centres on the edge are included). Centres sit at
  latitudes k·0.5° and longitudes −180° + k·0.625°.
* Values for a cell are identical to the point endpoint at that cell centre.

Area weighting
--------------
A lat/lon rectangle on a sphere of radius R has the exact area
``R² · Δλ · (sin φ₂ − sin φ₁)`` (λ in radians). Each grid cell is weighted by
the area of its overlap with the user's box, so cells cut by the box edge
count only for the part inside it. To make that possible the NASA request is
expanded by half a cell on every side, which returns every cell that overlaps
the box (and only those, after filtering). Nothing outside the box contributes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.utils.errors import EarthScopeError
from app.utils.grid import LAT_STEP, LON_STEP

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius


class RegionError(EarthScopeError):
    status_code = 422
    error = "INVALID_REGION"


class RegionTooLargeError(RegionError):
    error = "REGION_TOO_LARGE"


class RegionTooSmallError(RegionError):
    error = "REGION_TOO_SMALL"


class AntimeridianError(RegionError):
    error = "ANTIMERIDIAN_NOT_SUPPORTED"


@dataclass(frozen=True)
class BBox:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    @property
    def height(self) -> float:
        return self.lat_max - self.lat_min

    @property
    def width(self) -> float:
        return self.lon_max - self.lon_min


def spherical_rect_area_km2(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> float:
    """Exact area of a latitude/longitude rectangle on a sphere."""
    if lat_max <= lat_min or lon_max <= lon_min:
        return 0.0
    dlon = math.radians(lon_max - lon_min)
    return EARTH_RADIUS_KM**2 * dlon * (math.sin(math.radians(lat_max)) - math.sin(math.radians(lat_min)))


def validate_bbox(
    lat_min: float, lat_max: float, lon_min: float, lon_max: float, min_span: float, max_span: float
) -> BBox:
    vals = (lat_min, lat_max, lon_min, lon_max)
    if any(v is None or not math.isfinite(v) for v in vals):
        raise RegionError("All four bounding-box values must be numbers.")
    errors: list[str] = []
    for name, v in (("Minimum latitude", lat_min), ("Maximum latitude", lat_max)):
        if not -90 <= v <= 90:
            errors.append(f"{name} must be between -90 and 90.")
    for name, v in (("Minimum longitude", lon_min), ("Maximum longitude", lon_max)):
        if not -180 <= v <= 180:
            errors.append(f"{name} must be between -180 and 180.")
    if errors:
        raise RegionError("Invalid bounding box.", errors)
    if lat_min >= lat_max:
        raise RegionError("Invalid bounding box.", ["Minimum latitude must be smaller than maximum latitude."])
    if lon_min >= lon_max:
        raise AntimeridianError(
            "Regions crossing the antimeridian (±180° longitude) are not supported yet.",
            [
                "Minimum longitude must be smaller than maximum longitude (west to east, −180 to 180).",
                "NASA POWER rejects regional requests that cross ±180°; analyse each side separately.",
            ],
        )
    bbox = BBox(round(lat_min, 4), round(lat_max, 4), round(lon_min, 4), round(lon_max, 4))
    small = [f"{n} span is {s:g}°" for n, s in (("Latitude", bbox.height), ("Longitude", bbox.width)) if s < min_span]
    if small:
        raise RegionTooSmallError(
            f"The region must span at least {min_span:g}° in latitude and longitude.",
            small + ["NASA POWER's regional service requires ≥ 2°; for smaller areas use Point Analysis."],
        )
    large = [f"{n} span is {s:g}°" for n, s in (("Latitude", bbox.height), ("Longitude", bbox.width)) if s > max_span]
    if large:
        raise RegionTooLargeError(
            f"The region is too large: each side may span at most {max_span:g}°.",
            large + [
                "NASA POWER's regional service accepts at most 10° per side; Earth Scope expands the request by "
                "half a grid cell on each side to capture cells cut by the box edge.",
                "Draw a smaller rectangle, or analyse several neighbouring regions separately.",
            ],
        )
    return bbox


def request_box(b: BBox) -> BBox:
    """User box expanded by half a cell per side (clipped to the globe)."""
    return BBox(
        max(-90.0, b.lat_min - LAT_STEP / 2),
        min(90.0, b.lat_max + LAT_STEP / 2),
        max(-180.0, b.lon_min - LON_STEP / 2),
        min(180.0, b.lon_max + LON_STEP / 2),
    )


def cell_bounds(lat_c: float, lon_c: float) -> tuple[float, float, float, float]:
    return (
        max(-90.0, lat_c - LAT_STEP / 2),
        min(90.0, lat_c + LAT_STEP / 2),
        lon_c - LON_STEP / 2,
        lon_c + LON_STEP / 2,
    )


def overlap_area_km2(lat_c: float, lon_c: float, b: BBox) -> tuple[float, float]:
    """(overlap area with the box, full cell area), both in km²."""
    la0, la1, lo0, lo1 = cell_bounds(lat_c, lon_c)
    full = spherical_rect_area_km2(la0, la1, lo0, lo1)
    ov = spherical_rect_area_km2(max(la0, b.lat_min), min(la1, b.lat_max), max(lo0, b.lon_min), min(lo1, b.lon_max))
    return ov, full


def expected_cells(b: BBox) -> list[tuple[float, float]]:
    """Centres of every MERRA-2 cell that overlaps the box (positive area)."""
    i0 = math.ceil((b.lat_min - LAT_STEP / 2) / LAT_STEP - 1e-9)
    i1 = math.floor((b.lat_max + LAT_STEP / 2) / LAT_STEP + 1e-9)
    j0 = math.ceil((b.lon_min + 180 - LON_STEP / 2) / LON_STEP - 1e-9)
    j1 = math.floor((b.lon_max + 180 + LON_STEP / 2) / LON_STEP + 1e-9)
    out = []
    for i in range(i0, i1 + 1):
        lat = i * LAT_STEP
        if not -90 <= lat <= 90:
            continue
        for j in range(j0, j1 + 1):
            lon = -180 + j * LON_STEP
            if lon >= 180:  # +180 is the same meridian as −180
                continue
            if overlap_area_km2(lat, lon, b)[0] > 0:
                out.append((round(lat, 4), round(lon, 4)))
    return out


def region_summary(b: BBox) -> dict:
    cells = expected_cells(b)
    return {
        "lat_min": b.lat_min,
        "lat_max": b.lat_max,
        "lon_min": b.lon_min,
        "lon_max": b.lon_max,
        "height_deg": b.height,
        "width_deg": b.width,
        "area_km2": spherical_rect_area_km2(b.lat_min, b.lat_max, b.lon_min, b.lon_max),
        "expected_cells": len(cells),
    }
