"""MERRA-2 grid-cell geometry for NASA POWER point requests.

NASA POWER serves monthly meteorology at the source's native resolution
(MERRA-2: 0.5° latitude × 0.625° longitude). The ``geometry`` in a POWER
response merely echoes the requested point; it is NOT the grid-cell centre.

Verified live (2026-11): points inside one cell return identical values,
while points just across a cell edge differ. Cell centres sit at latitudes
k·0.5° and longitudes −180° + k·0.625°, e.g.

* (40.26, −74.00) and (40.74, −73.70) → same cell, centre (40.5, −73.75)
* (40.24, −74.00) → different cell (centre 40.0) — latitude edge at 40.25°
* (40.74, −74.30) → different cell (centre −74.375) — longitude edge at −74.0625°
"""

from __future__ import annotations

import math

LAT_STEP = 0.5
LON_STEP = 0.625


def _round_half_up(x: float) -> int:
    # Same convention as JavaScript Math.round, so backend and map agree.
    return math.floor(x + 0.5)


def merra2_cell(latitude: float, longitude: float) -> dict[str, float]:
    """Centre and bounds of the MERRA-2 cell containing the point."""
    lat_c = max(-90.0, min(90.0, _round_half_up(latitude / LAT_STEP) * LAT_STEP))
    lon_c = _round_half_up((longitude + 180.0) / LON_STEP) * LON_STEP - 180.0
    if lon_c >= 180.0:  # +180 and −180 are the same meridian
        lon_c -= 360.0
    return {
        "center_latitude": round(lat_c, 4),
        "center_longitude": round(lon_c, 4),
        "lat_min": round(max(-90.0, lat_c - LAT_STEP / 2), 4),
        "lat_max": round(min(90.0, lat_c + LAT_STEP / 2), 4),
        "lon_min": round(lon_c - LON_STEP / 2, 4),
        "lon_max": round(lon_c + LON_STEP / 2, 4),
        "lat_step": LAT_STEP,
        "lon_step": LON_STEP,
    }
