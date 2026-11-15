"""Geometry engine for country and custom-polygon analysis.

Coordinate reference system
---------------------------
Input geometries are GeoJSON Polygon / MultiPolygon in WGS84 longitude/latitude
(EPSG:4326, RFC 7946 axis order [lon, lat]). Longitudes are normalised to
[-180, 180]; parts drawn on a "wrapped" map copy (|lon| > 180) are split at the
antimeridian and shifted back. A ring edge that jumps more than 180° in
longitude is ambiguous and rejected (draw it on one continuous map copy).

Areas
-----
Physical areas are never taken from planar degree areas. Every geometry is
densified (≤ 0.1° segments) and projected with the Lambert cylindrical
equal-area projection on the sphere used by the rest of Earth Scope
(R = 6371.0088 km): x = R·λ, y = R·sin φ. In this projection a
latitude/longitude grid cell maps to an exact rectangle whose area is
R²·Δλ·(sin φ₂ − sin φ₁) — identical to the rectangle analysis — so a polygon
that equals a rectangle gets exactly the same weights. The WGS84 ellipsoidal
geodesic area (pyproj.Geod) is reported alongside for reference (they differ by
≲ 0.5 %).

Grid
----
A ``GridSpec`` describes the source grid (spacing and alignment). The three
NASA POWER parameters used here come from MERRA-2 (verified live: centres at
k·0.5° latitude and −180 + k·0.625° longitude). Cells are identified by integer
indices (i, j), never by floating-point strings.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import shapely
import shapely.affinity
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity

from app.core.catalog import VariableDefinition
from app.services.regional_grid import EARTH_RADIUS_KM, BBox, spherical_rect_area_km2
from app.utils.errors import GeometryTooComplexError, InvalidGeometryError

DENSIFY_DEG = 0.02   # sloped edges: piecewise error ~1e-8 relative; lon/lat-aligned edges are exact
_GEOD = Geod(ellps="WGS84")


# --------------------------------------------------------------------------- #
# Source grid
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GridSpec:
    name: str
    lat_step: float
    lon_step: float
    lat0: float = 0.0       # a centre latitude
    lon0: float = -180.0    # a centre longitude

    @property
    def n_lon(self) -> int:
        return int(round(360.0 / self.lon_step))

    def centre(self, i: int, j: int) -> tuple[float, float]:
        return self.lat0 + i * self.lat_step, self.lon0 + (j % self.n_lon) * self.lon_step

    def index(self, lat: float, lon: float, tol: float = 1e-4) -> tuple[int, int] | None:
        """Grid indices of a returned centre, or None if it is not on this grid."""
        fi = (lat - self.lat0) / self.lat_step
        fj = (lon - self.lon0) / self.lon_step
        i, j = int(round(fi)), int(round(fj))
        if abs(fi - i) * self.lat_step > tol or abs(fj - j) * self.lon_step > tol:
            return None
        return i, j % self.n_lon

    def footprint(self, i: int, j: int) -> Polygon | MultiPolygon:
        """Cell footprint in lon/lat; the cell centred on ±180° is split into two parts."""
        lat, lon = self.centre(i, j)
        la0, la1 = max(-90.0, lat - self.lat_step / 2), min(90.0, lat + self.lat_step / 2)
        lo0, lo1 = lon - self.lon_step / 2, lon + self.lon_step / 2
        if lo0 < -180.0:
            return MultiPolygon([box(-180.0, la0, lo1, la1), box(lo0 + 360.0, la0, 180.0, la1)])
        if lo1 > 180.0:
            return MultiPolygon([box(lo0, la0, 180.0, la1), box(-180.0, la0, lo1 - 360.0, la1)])
        return box(lo0, la0, lo1, la1)

    def cell_area_km2(self, i: int, j: int) -> float:
        lat, _ = self.centre(i, j)
        la0, la1 = max(-90.0, lat - self.lat_step / 2), min(90.0, lat + self.lat_step / 2)
        return spherical_rect_area_km2(la0, la1, 0.0, self.lon_step)


MERRA2_GRID = GridSpec("MERRA-2 native grid (0.5° latitude × 0.625° longitude)", 0.5, 0.625)
_GRID_BY_SOURCE = {"MERRA2": MERRA2_GRID}


def grid_for(variable: VariableDefinition) -> GridSpec:
    """Grid of the data source behind a variable. All integrated parameters (T2M, RH2M,
    GWETTOP) are MERRA-2; a new parameter from another source needs its own GridSpec."""
    return _GRID_BY_SOURCE["MERRA2"]


# --------------------------------------------------------------------------- #
# Parsing and validation
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GeometryLimits:
    max_vertices: int
    max_parts: int


def _polygon_parts(obj: Any) -> list[list[list[list[float]]]]:
    """Extract polygon coordinate arrays from Polygon / MultiPolygon / Feature / FeatureCollection."""
    if not isinstance(obj, dict):
        raise InvalidGeometryError("The geometry must be a GeoJSON object.")
    t = obj.get("type")
    if t == "Feature":
        return _polygon_parts(obj.get("geometry"))
    if t == "FeatureCollection":
        feats = obj.get("features")
        if not isinstance(feats, list) or not feats:
            raise InvalidGeometryError("The FeatureCollection contains no features.")
        parts: list = []
        for f in feats:
            parts.extend(_polygon_parts(f.get("geometry") if isinstance(f, dict) else None))
        return parts
    if t == "Polygon":
        return [obj.get("coordinates")]
    if t == "MultiPolygon":
        coords = obj.get("coordinates")
        if not isinstance(coords, list):
            raise InvalidGeometryError("MultiPolygon coordinates must be a list of polygons.")
        return coords
    raise InvalidGeometryError(
        f"Unsupported geometry type '{t}'.", ["Only Polygon and MultiPolygon areas (or Features containing them) can be analysed."]
    )


def _clean_ring(ring: Any, where: str) -> np.ndarray:
    try:
        arr = np.asarray(ring, dtype=float)
    except (TypeError, ValueError) as exc:
        raise InvalidGeometryError(f"{where}: coordinates must be numbers.") from exc
    if arr.ndim != 2 or arr.shape[1] < 2:
        raise InvalidGeometryError(f"{where}: each position must be [longitude, latitude].")
    arr = arr[:, :2]
    if not np.all(np.isfinite(arr)):
        raise InvalidGeometryError(f"{where}: coordinates must be finite numbers.")
    if np.any(np.abs(arr[:, 1]) > 90):
        raise InvalidGeometryError(f"{where}: latitude must be between −90 and 90.")
    if np.any(np.abs(arr[:, 0]) > 540):
        raise InvalidGeometryError(f"{where}: longitude is out of range.")
    keep = np.ones(len(arr), dtype=bool)
    keep[1:] = np.any(np.abs(np.diff(arr, axis=0)) > 1e-12, axis=1)   # drop repeated consecutive points
    arr = arr[keep]
    if len(arr) > 1 and np.allclose(arr[0], arr[-1], atol=1e-12):
        arr = arr[:-1]
    if len(np.unique(np.round(arr, 10), axis=0)) < 3:
        raise InvalidGeometryError(f"{where}: a polygon needs at least three distinct vertices.")
    if np.any(np.abs(np.diff(np.vstack([arr, arr[:1]])[:, 0])) > 180):
        raise InvalidGeometryError(
            f"{where}: an edge jumps more than 180° in longitude, so it is ambiguous whether it crosses the date line.",
            ["Draw the polygon on one continuous copy of the map, or split it into parts on each side of ±180°."],
        )
    return arr


def _wrap_longitudes(geom: Polygon | MultiPolygon) -> Polygon | MultiPolygon:
    """Split a geometry drawn across ±180° (|lon| > 180) and shift the pieces into [-180, 180]."""
    minx, _, maxx, _ = geom.bounds
    if minx >= -180 and maxx <= 180:
        return geom
    pieces = []
    for k in (-1, 0, 1):
        window = box(-180 + 360 * k, -90, 180 + 360 * k, 90)
        part = geom.intersection(window)
        if not part.is_empty:
            pieces.append(shapely.affinity.translate(part, xoff=-360 * k))
    merged = shapely.union_all(pieces)
    return _polygonal(merged)


def _polygonal(geom: Any) -> Polygon | MultiPolygon:
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    flat: list[Polygon] = []
    for g in polys:
        flat.extend(g.geoms if isinstance(g, MultiPolygon) else [g])
    if not flat:
        raise InvalidGeometryError("The geometry has no area.")
    return flat[0] if len(flat) == 1 else MultiPolygon(flat)


def _orient(geom: Polygon | MultiPolygon) -> Polygon | MultiPolygon:
    if isinstance(geom, Polygon):
        return orient(geom, sign=1.0)
    return MultiPolygon([orient(p, sign=1.0) for p in geom.geoms])


def parse_geometry(obj: Any, limits: GeometryLimits, *, repair: bool = False) -> tuple[Polygon | MultiPolygon, list[str]]:
    """Validate a GeoJSON area and return a normalised shapely geometry plus notes.

    User geometries (``repair=False``) are rejected if invalid — they are never
    silently reshaped. Authoritative boundaries (``repair=True``) may be repaired
    with ``shapely.make_valid``; the area change is reported in the notes.
    """
    notes: list[str] = []
    raw_parts = _polygon_parts(obj)
    if not raw_parts:
        raise InvalidGeometryError("The geometry is empty.")
    if len(raw_parts) > limits.max_parts:
        raise GeometryTooComplexError(f"The geometry has {len(raw_parts)} parts; at most {limits.max_parts} are allowed.")
    polys: list[Polygon] = []
    n_vertices = 0
    for k, rings in enumerate(raw_parts):
        if not isinstance(rings, list) or not rings:
            raise InvalidGeometryError(f"Polygon {k + 1} has no rings.")
        cleaned = [_clean_ring(r, f"Polygon {k + 1}, ring {m + 1}") for m, r in enumerate(rings)]
        n_vertices += sum(len(c) for c in cleaned)
        if n_vertices > limits.max_vertices:
            raise GeometryTooComplexError(
                f"The geometry has more than {limits.max_vertices} vertices.", ["Simplify the shape or select a smaller area."]
            )
        p = Polygon(cleaned[0], cleaned[1:])
        if shapely.MultiPoint(cleaned[0]).convex_hull.area < 1e-14:
            raise InvalidGeometryError(f"Polygon {k + 1} has zero area (its vertices lie on one line).")
        polys.append(p)
    geom: Polygon | MultiPolygon = polys[0] if len(polys) == 1 else MultiPolygon(polys)

    if not geom.is_valid:
        reason = explain_validity(geom)
        if not repair:
            raise InvalidGeometryError(
                "The polygon is not valid.",
                [reason, "Self-intersecting or overlapping shapes are not repaired automatically; redraw the boundary so edges do not cross."],
            )
        before = abs(geom.area)
        geom = _polygonal(shapely.make_valid(geom))
        change = abs(geom.area - before) / before * 100 if before else 0.0
        notes.append(f"The boundary geometry was repaired with shapely.make_valid ({reason}); planar area change {change:.3f}%.")
    if geom.is_empty or geom.area <= 0:
        raise InvalidGeometryError("The polygon has zero area.")
    geom = _orient(_wrap_longitudes(geom))
    if not geom.is_valid:  # e.g. pieces touching after wrapping
        geom = _orient(_polygonal(shapely.make_valid(geom)))
    return geom, notes


# --------------------------------------------------------------------------- #
# Areas and descriptors
# --------------------------------------------------------------------------- #

def _cea(coords: np.ndarray) -> np.ndarray:
    lon, lat = np.radians(coords[:, 0]), np.radians(coords[:, 1])
    return np.column_stack([EARTH_RADIUS_KM * lon, EARTH_RADIUS_KM * np.sin(lat)])


def equal_area_km2(geom: Any) -> Any:
    """Equal-area (spherical Lambert cylindrical) area in km² — scalar or array for arrays of geometries."""
    dense = shapely.segmentize(geom, DENSIFY_DEG)
    return shapely.area(shapely.transform(dense, _cea))


def geodesic_area_km2(geom: Polygon | MultiPolygon) -> float:
    """WGS84 ellipsoidal area (pyproj.Geod), densified so edges follow the lon/lat lines."""
    area, _ = _GEOD.geometry_area_perimeter(shapely.segmentize(geom, DENSIFY_DEG))
    return abs(area) / 1e6


def geometry_id(geom: Polygon | MultiPolygon) -> str:
    """Stable identifier: SHA-256 of the geometry rounded to 1e-7° (≈ 1 cm)."""
    wkb = shapely.to_wkb(shapely.normalize(shapely.set_precision(geom, 1e-7)), hex=True)
    return "geom-" + hashlib.sha256(wkb.encode()).hexdigest()[:16]


def n_vertices(geom: Polygon | MultiPolygon) -> int:
    """Distinct vertices (each ring's repeated closing point is not counted)."""
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    rings = sum(1 + len(p.interiors) for p in parts)
    return int(shapely.get_num_coordinates(geom)) - rings


def n_components(geom: Polygon | MultiPolygon) -> int:
    return len(geom.geoms) if isinstance(geom, MultiPolygon) else 1


def bbox_of(geom: Polygon | MultiPolygon) -> BBox:
    minx, miny, maxx, maxy = geom.bounds
    return BBox(miny, maxy, minx, maxx)


def display_geojson(geom: Polygon | MultiPolygon, tolerance: float = 0.01, digits: int = 4) -> dict[str, Any]:
    """Lightly simplified copy for drawing only (≈ 1 km); calculations always use the full geometry."""
    simple = shapely.simplify(geom, tolerance, preserve_topology=True)
    if simple.is_empty:
        simple = geom
    return mapping(shapely.set_precision(simple, 10 ** -digits))


# --------------------------------------------------------------------------- #
# Grid-cell intersection
# --------------------------------------------------------------------------- #

@dataclass
class CellOverlap:
    i: int
    j: int
    lat: float
    lon: float
    overlap_km2: float
    cell_km2: float
    clip: dict[str, Any] | None    # lon/lat GeoJSON of the part inside the area (None if the whole cell is inside)


def candidate_cells(geom: Polygon | MultiPolygon, grid: GridSpec) -> list[tuple[int, int]]:
    """All (i, j) whose footprint bounding box meets the bounding box of some geometry part."""
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    out: set[tuple[int, int]] = set()
    hl, hw = grid.lat_step / 2, grid.lon_step / 2
    for p in parts:
        minx, miny, maxx, maxy = p.bounds
        i0 = math.ceil((miny - hl - grid.lat0) / grid.lat_step - 1e-9)
        i1 = math.floor((maxy + hl - grid.lat0) / grid.lat_step + 1e-9)
        j0 = math.ceil((minx - hw - grid.lon0) / grid.lon_step - 1e-9)
        j1 = math.floor((maxx + hw - grid.lon0) / grid.lon_step + 1e-9)
        i_lo = math.ceil((-90 - grid.lat0) / grid.lat_step)
        i_hi = math.floor((90 - grid.lat0) / grid.lat_step)
        for i in range(max(i0, i_lo), min(i1, i_hi) + 1):
            for j in range(j0, j1 + 1):
                out.add((i, j % grid.n_lon))
    return sorted(out)


def intersecting_cells(geom: Polygon | MultiPolygon, grid: GridSpec) -> list[tuple[int, int]]:
    """Cells whose footprint intersects the area (positive-area overlap not yet checked)."""
    cand = candidate_cells(geom, grid)
    if not cand:
        return []
    shapely.prepare(geom)
    boxes = np.array([grid.footprint(i, j) for i, j in cand], dtype=object)
    hit = shapely.intersects(geom, boxes) & ~shapely.touches(geom, boxes)
    return [c for c, h in zip(cand, hit) if h]


def cell_overlaps(geom: Polygon | MultiPolygon, grid: GridSpec, cells: list[tuple[int, int]] | None = None,
                  clip_tolerance: float = 0.002) -> list[CellOverlap]:
    """Exact overlap area of every intersecting cell with the area (holes and parts respected)."""
    cells = intersecting_cells(geom, grid) if cells is None else cells
    if not cells:
        return []
    shapely.prepare(geom)
    boxes = np.array([grid.footprint(i, j) for i, j in cells], dtype=object)
    inter = shapely.intersection(boxes, geom)
    overlap = np.asarray(equal_area_km2(inter), dtype=float)
    out: list[CellOverlap] = []
    for (i, j), g, a in zip(cells, inter, overlap):
        full = grid.cell_area_km2(i, j)
        if a <= max(1e-6, 1e-9 * full):
            continue
        clip = None
        if a < full * (1 - 1e-6):
            poly = _polygonal_or_none(g)
            if poly is not None:
                clip = mapping(shapely.set_precision(shapely.simplify(poly, clip_tolerance, preserve_topology=True), 1e-5))
        lat, lon = grid.centre(i, j)
        out.append(CellOverlap(i, j, lat, lon, float(min(a, full)), float(full), clip))
    return out


def _polygonal_or_none(g: Any) -> Polygon | MultiPolygon | None:
    try:
        return _polygonal(g)
    except InvalidGeometryError:
        return None
