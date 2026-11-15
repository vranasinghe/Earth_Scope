"""Country and custom-polygon analysis (fixtures only — NASA and boundary downloads are mocked).

Expected values come from independent calculations: numerical integration of the
spherical area, pyproj geodesic areas, the rectangle-mode overlap formula,
explicit weighted loops, numpy.polyfit and statsmodels.multipletests.
See scripts/live_polygon_validation.py for the live NASA equivalent.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient
from scipy import integrate
from statsmodels.stats.multitest import multipletests

from app.api.deps import get_nasa_client
from app.core.catalog import get_variable
from app.core.config import get_settings
from app.main import app
from app.services import area_analysis as aa
from app.services import area_geometry as ag
from app.services import boundaries
from app.services import regional_aggregation as ra
from app.services import regional_analysis as ran
from app.services import spatial_trend_analysis as sta
from app.services.data_processing import aggregate_annual
from app.services.nasa_power import NasaPowerClient
from app.services.regional_grid import EARTH_RADIUS_KM, BBox, overlap_area_km2
from app.services.regional_tiling import NASA_MAX_SPAN, Tile, TileResult, fetch_tiles, merge_tiles, plan_tiles
from app.utils.errors import (
    CountryNotFoundError,
    GeometryTooComplexError,
    IncompleteTileRetrievalError,
    InvalidGeometryError,
    LocationNotSupportedError,
    NasaPowerResponseError,
    NasaPowerUnavailableError,
)
from tests.test_regional import centres_in

R = EARTH_RADIUS_KM
G = ag.MERRA2_GRID
LIM = ag.GeometryLimits(5000, 50)
START, END = 2001, 2016


def poly(*rings):
    return {"type": "Polygon", "coordinates": [list(map(list, r)) + [list(r[0])] for r in rings]}


def rect(lon0, lat0, lon1, lat1):
    return poly([(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])


@pytest.fixture(autouse=True)
def _clean():
    ran._results_cache.clear()
    sta._cell_cache.clear()
    boundaries.country_geometry.cache_clear()
    yield
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Fake NASA: answers ANY regional box with the centres inside it (closed box)
# --------------------------------------------------------------------------- #

class TileSession:
    def __init__(self, value_fn, fail=None, parameter="T2M", units="C", drop=()):
        self.value_fn, self.fail, self.parameter, self.units, self.drop = value_fn, fail or (lambda n, p: None), parameter, units, set(drop)
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        p = dict(params)
        self.calls.append(p)
        exc = self.fail(len(self.calls), p)
        if exc:
            raise exc
        la0, la1, lo0, lo1 = (float(p[k]) for k in ("latitude-min", "latitude-max", "longitude-min", "longitude-max"))
        feats = []
        for lat, lon in centres_in(la0, la1, lo0, lo1):
            if lon >= 180 or (lat, lon) in self.drop:
                continue
            s = {f"{y}{m:02d}": self.value_fn(lat, lon, y, m) for y in range(int(p["start"]), int(p["end"]) + 1) for m in range(1, 13)}
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat, 0]},
                          "properties": {"parameter": {self.parameter: s}}})
        body = {"type": "FeatureCollection", "features": feats,
                "header": {"title": "NASA/POWER test", "api": {"version": "v2.10.0"}, "sources": ["MERRA2"], "fill_value": -999.0},
                "parameters": {self.parameter: {"units": self.units, "longname": "Test"}}, "messages": []}

        class Resp:
            status_code = 200

            def json(self_inner):
                return body

        return Resp()


def area_query(geometry, var="T2M", name="test", start=START, end=END):
    a = aa.area_from_request(None, geometry, name, get_settings())
    return ran.RegionalQuery(get_variable(var), a.bbox, start, end, 0.8, a)


def run_area(geometry, value_fn, var="T2M", units="C", **kw):
    session = TileSession(value_fn, parameter=get_variable(var).parameter, units=units, **kw)
    client = NasaPowerClient(get_settings(), session=session)
    q = area_query(geometry, var)
    return ran.build_regional_response(q, client, get_settings()), q, client, session


def noise(lat, lon, y, m, s=0.3):
    return float(np.random.default_rng(abs(hash((lat, lon, y, m))) % (2**32)).normal(0, s))


# --------------------------------------------------------------------------- #
# Test A — country boundaries (catalogue, ISO mapping, fallback, repair, security)
# --------------------------------------------------------------------------- #

def test_catalogue_integrity():
    cs = boundaries.list_countries()
    codes = [c["iso3"] for c in cs]
    assert len(codes) == len(set(codes)) > 200
    for c in cs:
        assert len(c["iso3"]) == 3 and c["iso3"].isupper()
        assert c["license"] and c["attribution"] and c["version"] and c["boundary_id"]
        assert c["geometry_url"].startswith(boundaries.ALLOWED_PREFIXES)
    assert boundaries.country_meta("lka")["source"] == "geoBoundaries"
    assert "commit" in boundaries.country_meta("LKA")["version"]
    assert boundaries.country_meta("IND")["source"] == "Natural Earth"      # not in gbOpen -> labelled fallback
    with pytest.raises(CountryNotFoundError):
        boundaries.country_meta("XYZ")
    with pytest.raises(CountryNotFoundError):
        boundaries.country_meta("../etc")


ISLANDS = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"shapeISO": "LKA"}, "geometry": {
    "type": "MultiPolygon", "coordinates": [
        [[[80.0, 6.0], [81.8, 6.0], [81.8, 9.5], [80.0, 9.5], [80.0, 6.0]]],
        [[[79.5, 8.0], [79.8, 8.0], [79.8, 8.3], [79.5, 8.3], [79.5, 8.0]]],
    ]}}]}


def fake_download(monkeypatch, tmp_path, payloads):
    monkeypatch.setattr(boundaries, "_cache_dir", lambda: tmp_path)
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(payloads(url)).encode()

    monkeypatch.setattr(boundaries, "fetch_bytes", fetch)
    return calls


def test_country_boundary_loading_area_and_caching(monkeypatch, tmp_path):
    calls = fake_download(monkeypatch, tmp_path, lambda url: ISLANDS)
    s = boundaries.country_summary("lka")
    assert s["meta"]["iso3"] == "LKA" and s["n_components"] == 2
    expected = sum(abs(ag._GEOD.geometry_area_perimeter(ag.shapely.segmentize(g, 0.01))[0]) for g in s["geometry"].geoms) / 1e6
    assert s["geodesic_area_km2"] == pytest.approx(expected, rel=1e-6)
    assert s["area_km2"] == pytest.approx(s["geodesic_area_km2"], rel=0.006)   # sphere vs WGS84
    boundaries.country_geometry.cache_clear()
    boundaries.country_summary("LKA")
    assert len(calls) == 1, "the boundary file is downloaded once and cached on disk"


def test_natural_earth_fallback_picks_the_country_feature(monkeypatch, tmp_path):
    ne = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"ADM0_A3": "PAK"}, "geometry": rect(60, 25, 70, 35)},
        {"type": "Feature", "properties": {"ADM0_A3": "IND"}, "geometry": rect(70, 10, 85, 30)},
    ]}
    fake_download(monkeypatch, tmp_path, lambda url: ne)
    s = boundaries.country_summary("IND")
    assert s["meta"]["source"] == "Natural Earth" and s["geometry"].bounds == (70.0, 10.0, 85.0, 30.0)


def test_invalid_authoritative_boundary_is_repaired_and_reported(monkeypatch, tmp_path):
    bow = {"type": "Feature", "geometry": poly([(80, 6), (82, 9), (82, 6), (80, 9)])}
    fake_download(monkeypatch, tmp_path, lambda url: bow)
    s = boundaries.country_summary("LKA")
    assert s["geometry"].is_valid and any("make_valid" in n for n in s["notes"])


def test_download_allow_list():
    from app.utils.errors import BoundarySourceUnavailableError

    with pytest.raises(BoundarySourceUnavailableError):
        boundaries.fetch_bytes("http://169.254.169.254/latest/meta-data")
    with pytest.raises(BoundarySourceUnavailableError):
        boundaries.fetch_bytes("https://evil.example.com/geoBoundaries/raw/x.geojson")


# --------------------------------------------------------------------------- #
# Test B — custom polygon validation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("geom,cls,needle", [
    (poly([(0, 0), (1, 0)]), InvalidGeometryError, "three distinct"),
    (poly([(0, 0), (1, 1), (2, 2)]), InvalidGeometryError, "zero area"),                # collinear
    (poly([(0, 0), (2, 2), (2, 0), (0, 2)]), InvalidGeometryError, "not valid"),         # bow-tie
    (poly([(0, 0), (1, float("nan")), (1, 1)]), InvalidGeometryError, "finite"),
    (poly([(0, 0), (1, 95), (1, 1)]), InvalidGeometryError, "latitude"),
    (poly([(170, 0), (-170, 0), (-170, 2), (170, 2)]), InvalidGeometryError, "180°"),
    ({"type": "Point", "coordinates": [0, 0]}, InvalidGeometryError, "Unsupported"),
    ({"type": "GeometryCollection", "geometries": []}, InvalidGeometryError, "Unsupported"),
    ({"type": "Polygon", "coordinates": "x"}, InvalidGeometryError, ""),
    (poly([(math.cos(t) * 2, math.sin(t) * 2) for t in np.linspace(0, 6.28, 6000)]), GeometryTooComplexError, "vertices"),
])
def test_invalid_polygons_are_rejected_not_repaired(geom, cls, needle):
    with pytest.raises(cls) as e:
        ag.parse_geometry(geom, LIM)
    assert needle.lower() in (e.value.message + " ".join(e.value.details)).lower()


def test_valid_polygon_hole_multipart_and_orientation():
    g, notes = ag.parse_geometry({"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],   # clockwise exterior
        [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]]]}, LIM)
    assert ag.n_components(g) == 2 and not notes and g.is_valid
    assert all(p.exterior.is_ccw for p in g.geoms)
    whole = ag.equal_area_km2(ag.parse_geometry(rect(0, 0, 4, 4), LIM)[0])
    hole = ag.equal_area_km2(ag.parse_geometry(rect(1, 1, 3, 3), LIM)[0])
    small = ag.equal_area_km2(ag.parse_geometry(rect(10, 10, 11, 11), LIM)[0])
    assert ag.equal_area_km2(g) == pytest.approx(whole - hole + small, rel=1e-9)


def test_polygon_drawn_across_the_date_line_is_split():
    g, _ = ag.parse_geometry(rect(178.5, -17.5, 181.5, -16.0), LIM)
    assert ag.n_components(g) == 2 and g.bounds[0] == -180 and g.bounds[2] == 180
    assert ag.equal_area_km2(g) == pytest.approx(R * R * math.radians(3) * (math.sin(math.radians(-16)) - math.sin(math.radians(-17.5))), rel=1e-9)


# --------------------------------------------------------------------------- #
# Test C / D — grid intersection and area weights
# --------------------------------------------------------------------------- #

def test_rectangle_polygon_reproduces_rectangle_mode_weights():
    box = BBox(6.0, 9.5, 79.5, 82.0)
    g, _ = ag.parse_geometry(rect(79.5, 6.0, 82.0, 9.5), LIM)
    ov = ag.cell_overlaps(g, G)
    assert len(ov) == 40
    for c in ov:
        assert c.overlap_km2 == pytest.approx(overlap_area_km2(c.lat, c.lon, box)[0], rel=1e-12)


def test_triangle_area_matches_numerical_integration_and_geodesic():
    # lon in [20, 21], lat from 10 to 10 + 2(lon − 20): A = R² ∫ (sin φ_hi − sin φ_lo) dλ
    g, _ = ag.parse_geometry(poly([(20, 10), (21, 10), (21, 12)]), LIM)
    exact, _ = integrate.quad(lambda lam: math.sin(math.radians(10 + 2 * (lam - 20))) - math.sin(math.radians(10)), 20, 21)
    exact *= R * R * math.radians(1)
    assert ag.equal_area_km2(g) == pytest.approx(exact, rel=1e-4)
    assert ag.geodesic_area_km2(g) == pytest.approx(exact, rel=0.006)
    ov = ag.cell_overlaps(g, G)
    # sloped edge: per-cell pieces and the whole triangle are densified differently -> tiny piecewise difference
    assert sum(c.overlap_km2 for c in ov) == pytest.approx(ag.equal_area_km2(g), rel=1e-7)


def test_full_partial_none_hole_and_disconnected_overlaps():
    # Cell centred (0, 0): lon −0.3125…0.3125, lat −0.25…0.25
    full = R * R * math.radians(0.625) * 2 * math.sin(math.radians(0.25))
    g, _ = ag.parse_geometry(rect(-1, -1, 1, 1), LIM)
    by = {(c.i, c.j): c for c in ag.cell_overlaps(g, G)}
    centre = by[G.index(0.0, 0.0)]
    assert centre.overlap_km2 == pytest.approx(full, rel=1e-9) and centre.clip is None
    # partial: right half of the centre cell only
    g2, _ = ag.parse_geometry(rect(0.0, -0.25, 0.3125, 0.25), LIM)
    ov2 = ag.cell_overlaps(g2, G)
    assert len(ov2) == 1 and ov2[0].overlap_km2 == pytest.approx(full / 2, rel=1e-9) and ov2[0].clip is not None
    # touching only along an edge: no overlap
    g3, _ = ag.parse_geometry(rect(0.3125, -0.25, 0.9375, 0.25), LIM)
    assert G.index(0.0, 0.0) not in {(c.i, c.j) for c in ag.cell_overlaps(g3, G)}
    # hole removes the interior cell completely
    gh, _ = ag.parse_geometry({"type": "Polygon", "coordinates": [
        [[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]], [[-0.3125, -0.25], [0.3125, -0.25], [0.3125, 0.25], [-0.3125, 0.25], [-0.3125, -0.25]]]}, LIM)
    assert G.index(0.0, 0.0) not in {(c.i, c.j) for c in ag.cell_overlaps(gh, G)}
    # disconnected parts never share or double count cells
    gm, _ = ag.parse_geometry({"type": "MultiPolygon", "coordinates": [rect(0, 0, 1, 1)["coordinates"], rect(5, 5, 6, 6)["coordinates"]]}, LIM)
    ovm = ag.cell_overlaps(gm, G)
    assert len({(c.i, c.j) for c in ovm}) == len(ovm)
    assert sum(c.overlap_km2 for c in ovm) == pytest.approx(ag.equal_area_km2(gm), rel=1e-9)


def test_date_line_cell_is_split_and_weighted_correctly():
    # cell centred at −180 spans 179.6875…180 and −180…−179.6875
    g, _ = ag.parse_geometry(rect(179.8, -1, 180.2, 1), LIM)   # wrapped across the line
    by = {(c.i, c.j): c for c in ag.cell_overlaps(g, G)}
    c = by[(0, 0)]
    assert c.lon == -180.0
    assert c.overlap_km2 == pytest.approx(R * R * math.radians(0.4) * 2 * math.sin(math.radians(0.25)), rel=1e-9)


@pytest.mark.parametrize("box", [(-1, -3, 1, 3), (10, 64, 22, 70), (-75, -55, -65, -50)])
def test_high_latitude_equator_and_southern_areas(box):
    g, _ = ag.parse_geometry(rect(*box), LIM)
    lon0, lat0, lon1, lat1 = box
    exact = R * R * math.radians(lon1 - lon0) * (math.sin(math.radians(lat1)) - math.sin(math.radians(lat0)))
    assert ag.equal_area_km2(g) == pytest.approx(exact, rel=1e-9)
    assert sum(c.overlap_km2 for c in ag.cell_overlaps(g, G)) == pytest.approx(exact, rel=1e-9)


def test_narrow_and_tiny_polygons():
    strip, _ = ag.parse_geometry(rect(80.0, 6.0, 80.05, 9.0), LIM)    # 0.05° wide
    ov = ag.cell_overlaps(strip, G)
    assert sum(c.overlap_km2 for c in ov) == pytest.approx(ag.equal_area_km2(strip), rel=1e-9)
    assert all(c.overlap_km2 < c.cell_km2 * 0.1 for c in ov)
    tiny = aa.area_from_request(None, rect(80.01, 7.01, 80.05, 7.05), "islet", get_settings())
    pf = aa.preflight(tiny, get_variable("T2M"), 2001, 2010, get_settings())
    assert pf["n_cells"] == 1 and pf["small_area_warning"] and pf["available"]


# --------------------------------------------------------------------------- #
# Test E — tiling
# --------------------------------------------------------------------------- #

def test_tile_plan_limits_and_coverage():
    g, _ = ag.parse_geometry(rect(60, 5, 100, 38), LIM)
    cells = ag.intersecting_cells(g, G)
    tiles = plan_tiles(cells, G)
    assert sum(t.n_needed for t in tiles) == len(cells)          # every needed cell in exactly one block
    for t in tiles:
        assert 2.0 - 1e-9 <= t.lat_max - t.lat_min <= NASA_MAX_SPAN and 2.0 - 1e-9 <= t.lon_max - t.lon_min <= NASA_MAX_SPAN
    # each needed centre falls strictly inside at least one tile (edges are between centres)
    for i, j in cells[:: max(1, len(cells) // 300)]:
        lat, lon = G.centre(i, j)
        assert any(t.lat_min < lat < t.lat_max and t.lon_min < lon < t.lon_max for t in tiles)


def test_small_polygon_tile_is_expanded_to_the_nasa_minimum():
    g, _ = ag.parse_geometry(rect(80.0, 7.0, 80.3, 7.2), LIM)
    tiles = plan_tiles(ag.intersecting_cells(g, G), G)
    assert len(tiles) == 1 and tiles[0].lat_max - tiles[0].lat_min == pytest.approx(2.0) and tiles[0].lon_max - tiles[0].lon_min == pytest.approx(2.0)


def test_overlapping_tiles_are_deduplicated_by_grid_index():
    g, _ = ag.parse_geometry(rect(80.0, 6.0, 82.0, 8.0), LIM)
    ov = ag.cell_overlaps(g, G)
    session = TileSession(lambda la, lo, y, m: 20 + la)
    client = NasaPowerClient(get_settings(), session=session)
    # two deliberately overlapping tiles
    tiles = [Tile("A", 5.75, 8.25, 79.6875, 81.5625, 0), Tile("B", 5.75, 8.25, 80.9375, 82.8125, 0)]
    res = fetch_tiles(client, get_variable("T2M"), tiles, 2001, 2002, concurrency=2, retries=0, backoff=0)
    merged = merge_tiles(res, get_variable("T2M"), ov, G, 2001, 2002, ag.equal_area_km2(g))
    assert merged.n_duplicates > 0 and merged.n_missing_cells == 0
    assert len(merged.grid.lats) == len(ov) == len({(c.i, c.j) for c in ov})
    assert np.allclose(merged.grid.values[:, 0], merged.grid.lats + 20)


def _tile_result(tile, feats):
    return TileResult(tile, {"features": feats, "header": {"fill_value": -999.0, "sources": ["MERRA2"]},
                             "parameters": {"T2M": {"units": "C"}}}, "u", "t", False, 1, len(feats))


def _feat(lat, lon, v):
    return {"geometry": {"coordinates": [lon, lat]}, "properties": {"parameter": {"T2M": {f"2001{m:02d}": v for m in range(1, 13)}}}}


def test_conflicting_duplicates_and_off_grid_cells_are_errors():
    ov = [ag.CellOverlap(14, 416, 7.0, 80.0, 100.0, 3800.0, None)]
    t = Tile("A", 6, 8, 79, 81, 1)
    with pytest.raises(NasaPowerResponseError, match="different values"):
        merge_tiles([_tile_result(t, [_feat(7.0, 80.0, 20)]), _tile_result(t, [_feat(7.0, 80.0, 21)])], get_variable("T2M"), ov, G, 2001, 2001, 100)
    with pytest.raises(NasaPowerResponseError, match="expected grid"):
        merge_tiles([_tile_result(t, [_feat(7.1, 80.0, 20)])], get_variable("T2M"), ov, G, 2001, 2001, 100)


def test_missing_cell_is_reported_and_treated_as_missing():
    ov = [ag.CellOverlap(14, 416, 7.0, 80.0, 100.0, 3800.0, None), ag.CellOverlap(14, 417, 7.0, 80.625, 100.0, 3800.0, None)]
    m = merge_tiles([_tile_result(Tile("A", 6, 8, 79, 81, 2), [_feat(7.0, 80.0, 20)])], get_variable("T2M"), ov, G, 2001, 2001, 200)
    assert m.n_missing_cells == 1 and np.isnan(m.grid.values[1]).all() and any("not returned" in w for w in m.grid.warnings)


def test_failed_tiles_never_produce_a_partial_result():
    slept = []
    g, _ = ag.parse_geometry(rect(60, 5, 75, 15), LIM)
    tiles = plan_tiles(ag.intersecting_cells(g, G), G)
    assert len(tiles) >= 2
    bad = tiles[1]
    session = TileSession(lambda *a: 20.0, fail=lambda n, p: requests.ConnectionError("down") if float(p["latitude-min"]) == bad.lat_min and float(p["longitude-min"]) == bad.lon_min else None)
    client = NasaPowerClient(get_settings(), session=session)
    with pytest.raises(IncompleteTileRetrievalError) as e:
        fetch_tiles(client, get_variable("T2M"), tiles, 2001, 2002, concurrency=2, retries=2, backoff=0.5, sleep=slept.append)
    assert bad.key in e.value.details[0] and slept == [0.5, 1.0]          # exponential backoff, then give up


def test_transient_tile_failure_is_retried():
    state = {"n": 0}

    def fail(n, p):
        state["n"] += 1
        return requests.Timeout("slow") if state["n"] == 1 else None

    client = NasaPowerClient(get_settings(), session=TileSession(lambda *a: 20.0, fail=fail))
    res = fetch_tiles(client, get_variable("T2M"), [Tile("A", 6, 8, 79, 81, 1)], 2001, 2002, concurrency=1, retries=2, backoff=0, sleep=lambda s: None)
    assert res[0].attempts == 2


def test_non_retryable_tile_error_propagates():
    class Rejecting(TileSession):
        def get(self, url, params=None, timeout=None):
            self.calls.append(params)

            class Resp:
                status_code = 422

                def json(self_inner):
                    return {"messages": ["Latitude out of range"]}

            return Resp()

    client = NasaPowerClient(get_settings(), session=Rejecting(lambda *a: 0))
    with pytest.raises(LocationNotSupportedError):
        fetch_tiles(client, get_variable("T2M"), [Tile("A", 6, 8, 79, 81, 1)], 2001, 2002, concurrency=1, retries=2, backoff=0, sleep=lambda s: None)


# --------------------------------------------------------------------------- #
# Test F / G — polygon-weighted series and statistics
# --------------------------------------------------------------------------- #

TWO_PART = {"type": "MultiPolygon", "coordinates": [rect(80.1, 6.1, 81.4, 7.4)["coordinates"], rect(84.2, 8.2, 85.0, 9.3)["coordinates"]]}


def test_polygon_weighted_monthly_mean_matches_an_independent_weighted_loop():
    fn = lambda la, lo, y, m: 20 + 0.3 * la - 0.1 * lo + 0.5 * m  # noqa: E731
    res, q, *_ = run_area(TWO_PART, fn)
    g, _ = ag.parse_geometry(TWO_PART, LIM)
    ov = ag.cell_overlaps(g, G)
    w = np.array([c.overlap_km2 for c in ov])
    for rec in res["monthly"][:14]:
        v = np.array([fn(c.lat, c.lon, rec["year"], rec["month"]) for c in ov])
        assert rec["value"] == pytest.approx(float(np.sum(w * v) / w.sum()), rel=1e-12)
        assert rec["coverage"] == pytest.approx(1.0) and rec["valid_cells"] == len(ov)
    m = res["metadata"]
    assert m["area_mode"] == "polygon" and m["n_tiles"] == len(plan_tiles(ag.intersecting_cells(g, G), G)) and m["grid_representability"] == pytest.approx(1.0, abs=1e-9)
    assert len(m["request_manifest"]) == m["n_tiles"] and all(t["url"].startswith("https://power.larc.nasa.gov/") for t in m["request_manifest"])
    assert m["region_area_km2"] == pytest.approx(ag.equal_area_km2(g), rel=1e-12)


def test_polygon_trend_equals_independent_weighted_ols():
    slope = lambda la, lo: 0.02 + 0.01 * (la - 6)  # noqa: E731
    fn = lambda la, lo, y, m: 25 + slope(la, lo) * (y - START) + noise(la, lo, y, m)  # noqa: E731
    res, *_ = run_area(TWO_PART, fn)
    g, _ = ag.parse_geometry(TWO_PART, LIM)
    ov = ag.cell_overlaps(g, G)
    w = np.array([c.overlap_km2 for c in ov])
    yrs = np.arange(START, END + 1)
    import calendar
    ann = []
    for y in yrs:
        d = np.array([calendar.monthrange(int(y), m)[1] for m in range(1, 13)])
        monthly = [np.sum(w * np.array([fn(c.lat, c.lon, int(y), m) for c in ov])) / w.sum() for m in range(1, 13)]
        ann.append(np.sum(np.array(monthly) * d) / d.sum())
    assert res["statistics"]["regression"]["slope"] == pytest.approx(np.polyfit(yrs, ann, 1)[0], abs=1e-10)
    assert res["statistics"]["advanced"]["modified_mann_kendall"]["canonical_p_value"] is not None


def test_vectorised_annual_table_equals_aggregate_annual_for_every_cell():
    import pandas as pd

    fn = lambda la, lo, y, m: -999.0 if (m in (2, 7) and la > 7) or (y == 2003 and m < 5) else 20 + la + m  # noqa: E731
    res, q, client, _ = run_area(TWO_PART, fn)
    loaded = ran.load_regional_grid(q, client, get_settings())
    years, means, months = ra.cell_annual_table(loaded.grid)
    for k, row in enumerate(loaded.grid.values):
        df = pd.DataFrame({"year": loaded.grid.years, "month": loaded.grid.months,
                           "value": np.where(np.isnan(row), None, row), "status": np.where(np.isnan(row), "missing", "valid")})
        ref = aggregate_annual(df, 10)
        assert list(ref["valid_months"]) == list(months[k])
        assert np.allclose(ref["value"].astype(float), means[k], equal_nan=True, atol=1e-12)


# --------------------------------------------------------------------------- #
# Test H / I — spatial FDR inside the polygon, opposing trends
# --------------------------------------------------------------------------- #

TRIANGLE = poly([(79.6, 6.1), (81.9, 6.1), (79.6, 9.4)])


def test_spatial_family_is_only_the_polygon_cells_and_bh_is_correct():
    fn = lambda la, lo, y, m: 20 + (0.05 if lo < 80.5 else -0.05) * (y - START) + noise(la, lo, y, m, 0.4)  # noqa: E731
    session = TileSession(fn)
    client = NasaPowerClient(get_settings(), session=session)
    q = area_query(TRIANGLE)
    out = sta.build_spatial_response(q, client, get_settings(), "mann_kendall", "fdr_bh", 0.05)
    g, _ = ag.parse_geometry(TRIANGLE, LIM)
    expected = {sta.cell_id(c.lat, c.lon) for c in ag.cell_overlaps(g, G)}
    got = {c["id"] for c in out["cells"]}
    rect_cells = 6 * 4  # cells whose centres lie in the bounding rectangle — many are outside the triangle
    assert got == expected and len(got) < rect_cells + 20
    fam = [c for c in out["cells"] if c["in_family"]]
    assert out["summary"]["n_hypotheses"] == len(fam) == len(expected)
    ref = multipletests([c["mk_p_value"] for c in fam], method="fdr_bh")[1]
    assert [c["adjusted_p_value"] for c in fam] == pytest.approx(list(ref))
    cats = out["summary"]["categories"]
    assert cats["significant_increasing"]["count"] > 0 and cats["significant_decreasing"]["count"] > 0
    w = np.array([c["overlap_area_km2"] for c in out["cells"]])
    b = np.array([c["ols_slope"] for c in out["cells"]])
    assert out["regional_aggregate"]["ols_slope"] == pytest.approx(float(np.sum(w * b) / w.sum()), abs=1e-9)
    assert any(c["clip"] is not None for c in out["cells"])          # edge cells carry their clipped shape
    assert "both positive and negative" in " ".join(out["interpretation"])
    assert len(session.calls) == len(plan_tiles(ag.intersecting_cells(g, G), G))  # fetched once for spatial + aggregate


# --------------------------------------------------------------------------- #
# Test J / K — missing data, budgets, API, edge cases
# --------------------------------------------------------------------------- #

def api(session):
    client = NasaPowerClient(get_settings(), session=session)   # one shared client, as in the app
    app.dependency_overrides[get_nasa_client] = lambda: client
    return TestClient(app)


BODY = {"geometry": TWO_PART, "name": "Two parts", "variable": "T2M", "start_year": START, "end_year": END}


def test_api_analyze_spatial_and_cell_endpoints():
    session = TileSession(lambda la, lo, y, m: 20 + 0.03 * (y - START) + noise(la, lo, y, m))
    c = api(session)
    pv = c.post("/api/polygon/preview", json=BODY).json()
    assert pv["area"]["n_components"] == 2 and pv["preflight"]["n_tiles"] >= 1 and session.calls == []
    r = c.post("/api/polygon/analyze", json=BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metadata"]["area_name"] == "Two parts" and body["metadata"]["data_mode"] == "LIVE"
    s = c.post("/api/polygon/spatial-trends", json={**BODY, "correction": "fdr_by"}).json()
    cid = s["cells"][0]["id"]
    d = c.post("/api/polygon/spatial-trends/cell", json={**BODY, "cell_id": cid})
    assert d.status_code == 200 and len(d.json()["annual"]) == END - START + 1
    assert len(session.calls) == pv["preflight"]["n_tiles"]


def test_api_tile_failure_is_an_error_not_a_partial_result(monkeypatch):
    import app.services.regional_tiling as rt

    monkeypatch.setattr(rt.time, "sleep", lambda s: None)
    wide = rect(70, 5, 88, 12)                   # several tiles; only the eastern ones fail
    session = TileSession(lambda *a: 20.0, fail=lambda n, p: requests.ConnectionError("x") if float(p["longitude-min"]) > 75 else None)
    r = api(session).post("/api/polygon/analyze", json={**BODY, "geometry": wide})
    assert r.status_code == 503 and r.json()["error"] == "INCOMPLETE_TILE_RETRIEVAL" and r.json()["retryable"]
    assert "statistics" not in r.json() and "no result is shown" in r.json()["message"]
    assert any(float(p["longitude-min"]) <= 75 for p in session.calls)   # other tiles did succeed


def test_api_missing_months_lower_coverage_and_are_excluded():
    fn = lambda la, lo, y, m: -999.0 if (la < 7.5 and y == 2005) else 20 + 0.02 * (y - START)  # noqa: E731
    body = api(TileSession(fn)).post("/api/polygon/analyze", json=BODY).json()
    rec = [x for x in body["monthly"] if x["year"] == 2005]
    assert all(x["status"] == "insufficient_coverage" and x["value"] is None and x["coverage"] < 0.8 for x in rec)
    assert not [a for a in body["annual"] if a["year"] == 2005][0]["used_in_trend"]


def test_api_budget_refusal_happens_before_any_nasa_request(monkeypatch):
    session = TileSession(lambda *a: 20.0)
    big = rect(40, -30, 100, 40)
    r = api(session).post("/api/polygon/analyze", json={**BODY, "geometry": big})
    assert r.status_code == 422 and r.json()["error"] == "ANALYSIS_TOO_LARGE" and session.calls == []
    assert "more data than the current analysis limit" in r.json()["message"]
    pv = api(session).post("/api/polygon/preview", json={**BODY, "geometry": big}).json()["preflight"]
    assert not pv["available"] and pv["reasons"] and pv["suggestions"]


def test_api_validation_errors():
    c = api(TileSession(lambda *a: 20.0))
    assert c.post("/api/polygon/analyze", json={**BODY, "geometry": poly([(0, 0), (2, 2), (2, 0), (0, 2)])}).json()["error"] == "INVALID_GEOMETRY"
    assert c.post("/api/polygon/analyze", json={**BODY, "iso3": "LKA"}).json()["error"] == "INVALID_REQUEST"      # both given
    r = c.post("/api/polygon/analyze", json={"variable": "T2M"})
    assert r.json()["error"] == "INVALID_REQUEST"
    assert c.get("/api/boundaries/countries/QQQ").json()["error"] == "COUNTRY_NOT_FOUND"
    huge = c.post("/api/polygon/preview", content=b"{" + b" " * 3_100_000 + b"}", headers={"content-type": "application/json"})
    assert huge.json()["error"] == "GEOMETRY_TOO_COMPLEX"


def test_api_land_only_country_like_area_excludes_water_cells():
    fn = lambda la, lo, y, m: 1.0 if lo > 84.5 else 0.4 + 0.003 * (y - START)  # noqa: E731
    body = api(TileSession(fn, parameter="GWETTOP", units="1")).post("/api/polygon/analyze", json={**BODY, "variable": "GWETTOP"}).json()
    assert body["metadata"]["n_cells_excluded"] > 0 and body["metadata"]["land_fraction"] < 1


def test_api_date_line_polygon():
    session = TileSession(lambda la, lo, y, m: 26 + 0.01 * (y - START))
    body = api(session).post("/api/polygon/analyze", json={**BODY, "geometry": rect(178.5, -17.5, 181.5, -16.0)}).json()
    m = body["metadata"]
    assert m["n_components"] == 2 and m["n_tiles"] == 2 and m["grid_representability"] == pytest.approx(1.0, abs=1e-9)
    assert any(t["lon_min"] == -180.0 for t in m["request_manifest"])
    assert any(c["longitude"] == -180.0 for c in body["cells"])


def test_api_country_analysis_with_mocked_boundary(monkeypatch, tmp_path):
    fake_download(monkeypatch, tmp_path, lambda url: ISLANDS)
    session = TileSession(lambda la, lo, y, m: 27 + 0.02 * (y - START) + noise(la, lo, y, m))
    c = api(session)
    cd = c.get("/api/boundaries/countries/lka", params={"start_year": START, "end_year": END}).json()
    assert cd["area"]["iso3"] == "LKA" and cd["area"]["boundary"]["source"] == "geoBoundaries" and cd["preflight"]["available"]
    body = c.post("/api/polygon/analyze", json={"iso3": "LKA", "variable": "T2M", "start_year": START, "end_year": END}).json()
    m = body["metadata"]
    assert m["area_mode"] == "country" and m["iso3"] == "LKA" and m["boundary"]["license"]
    assert m["geometry_id"] == cd["area"]["geometry_id"]
    assert "country boundary of Sri Lanka" in json.dumps(body["interpretation"], ensure_ascii=False)
