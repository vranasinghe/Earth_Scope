"""Regional analysis tests (fixtures only — NASA is mocked here).

Expected values are computed independently (brute-force loops, numerical
integration, hand-derived formulas) rather than with the application code.
See scripts/live_regional_validation.py for the live NASA equivalent.
"""

from __future__ import annotations

import calendar
import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from scipy import integrate

from app.api.deps import get_nasa_client
from app.core.catalog import get_variable
from app.core.config import Settings, get_settings
from app.main import app
from app.services import regional_aggregation as ra
from app.services import regional_analysis as ran
from app.services import trend_analysis as ta
from app.services.nasa_power import NasaPowerClient
from app.services.regional_grid import (
    EARTH_RADIUS_KM,
    AntimeridianError,
    BBox,
    RegionError,
    RegionTooLargeError,
    RegionTooSmallError,
    expected_cells,
    overlap_area_km2,
    request_box,
    spherical_rect_area_km2,
    validate_bbox,
)
from app.utils.errors import LocationNotSupportedError, StatisticsError

R = EARTH_RADIUS_KM


# --------------------------------------------------------------------------- #
# Fixture builder: a NASA-shaped regional FeatureCollection
# --------------------------------------------------------------------------- #

def centres_in(lat0, lat1, lon0, lon1):
    """Cell centres inside a CLOSED box — the rule observed on the live API."""
    out = []
    for i in range(math.ceil(lat0 / 0.5 - 1e-9), math.floor(lat1 / 0.5 + 1e-9) + 1):
        for j in range(math.ceil((lon0 + 180) / 0.625 - 1e-9), math.floor((lon1 + 180) / 0.625 + 1e-9) + 1):
            out.append((round(i * 0.5, 4), round(-180 + j * 0.625, 4)))
    return out


def make_regional_payload(bbox: BBox, start, end, value_fn, parameter="T2M", units="C", extra=None):
    req = request_box(bbox)
    feats = []
    for lat, lon in centres_in(req.lat_min, req.lat_max, req.lon_min, req.lon_max):
        series = {}
        for y in range(start, end + 1):
            for m in range(1, 13):
                series[f"{y}{m:02d}"] = value_fn(lat, lon, y, m)
            series[f"{y}13"] = 9999.0  # annual key must be ignored
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
                      "properties": {"parameter": {parameter: series}}})
    feats.extend(extra or [])
    return {"type": "FeatureCollection", "features": feats,
            "header": {"title": "NASA/POWER Source Native Resolution Monthly and Annual", "api": {"version": "v2.10.0"},
                       "sources": ["MERRA2"], "fill_value": -999.0, "time_standard": "LST"},
            "parameters": {parameter: {"units": units, "longname": "Test"}}, "messages": []}


BOX = BBox(6.0, 9.5, 79.5, 82.0)
S = Settings(_env_file=None)


# --------------------------------------------------------------------------- #
# Geography
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("box", [(6, 9, 79, 82), (-3, 1, 35, 39), (-36, -32, 142, 148), (60, 69, 10, 19), (-1, 1, -1, 1.5), (-1, 1, -1, 0.5)])
def test_valid_boxes_including_negative_and_equator_crossing(box):
    if box == (-1, 1, -1, 0.5):  # only 1.5° of longitude
        with pytest.raises(RegionTooSmallError):
            validate_bbox(*box, 2, 9)
        return
    b = validate_bbox(*box, 2, 9)
    assert (b.lat_min, b.lat_max, b.lon_min, b.lon_max) == box


@pytest.mark.parametrize(
    "box,err",
    [
        ((95, 99, 0, 5), RegionError), ((0, 5, 0, 190), RegionError), ((9, 6, 79, 82), RegionError),
        ((6, 6, 79, 82), RegionError), ((6, 9, 82, 82), AntimeridianError), ((-10, -6, 178, -178), AntimeridianError),
        ((6, 7, 79, 82), RegionTooSmallError), ((0, 9.5, 30, 35), RegionTooLargeError), ((0, 5, 30, 40), RegionTooLargeError),
    ],
)
def test_invalid_boxes(box, err):
    with pytest.raises(err):
        validate_bbox(*box, 2, 9)


def test_spherical_area_matches_numerical_integration_and_globe():
    for la0, la1, lo0, lo1 in [(6, 9.5, 79.5, 82), (60, 69, 10, 19), (-36, -32, 142, 148), (-1, 1, 0, 2)]:
        num, _ = integrate.dblquad(lambda phi, lam: R**2 * math.cos(phi), math.radians(lo0), math.radians(lo1),
                                   math.radians(la0), math.radians(la1))
        assert spherical_rect_area_km2(la0, la1, lo0, lo1) == pytest.approx(num, rel=1e-9)
    assert spherical_rect_area_km2(-90, 90, -180, 180) == pytest.approx(4 * math.pi * R**2, rel=1e-12)


def test_degrees_are_not_constant_distances():
    eq = spherical_rect_area_km2(0, 1, 0, 1)
    hi = spherical_rect_area_km2(60, 61, 0, 1)
    assert eq == pytest.approx(12364, rel=1e-3)
    assert hi / eq == pytest.approx(math.cos(math.radians(60.5)), rel=1e-3)


def test_expected_cells_match_live_closed_box_rule_and_cover_box_exactly():
    req = request_box(BOX)
    nasa_like = {c for c in centres_in(req.lat_min, req.lat_max, req.lon_min, req.lon_max) if overlap_area_km2(*c, BOX)[0] > 0}
    assert set(expected_cells(BOX)) == nasa_like
    total = sum(overlap_area_km2(*c, BOX)[0] for c in expected_cells(BOX))
    assert total == pytest.approx(spherical_rect_area_km2(6, 9.5, 79.5, 82), rel=1e-12)


def test_request_box_stays_within_nasa_limits_for_max_user_box():
    b = validate_bbox(0, 9, 0, 9, 2, 9)
    r = request_box(b)
    assert r.lat_max - r.lat_min <= 10 and r.lon_max - r.lon_min <= 10


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def test_parse_dedups_drops_outside_and_handles_missing():
    t2m = get_variable("T2M")
    dup = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [80.0, 7.0, 0]},
           "properties": {"parameter": {"T2M": {"200101": 99.0}}}}
    far = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [100.0, 30.0, 0]},
           "properties": {"parameter": {"T2M": {"200101": 1.0}}}}

    def val(lat, lon, y, m):
        if (lat, lon) == (7.5, 80.625) and m == 3:
            return -999.0
        if (lat, lon) == (8.0, 81.25):
            return -999.0  # entirely missing cell
        return 20.0 + lat

    g = ra.parse_regional_response(make_regional_payload(BOX, 2001, 2002, val, extra=[dup, far]), t2m, BOX, 2001, 2002)
    assert g.n_duplicates == 1 and g.n_outside == 1
    assert len(g.lats) == len(expected_cells(BOX))
    assert not np.any(g.values == 0)
    i = next(k for k in range(len(g.lats)) if (g.lats[k], g.lons[k]) == (7.5, 80.625))
    assert np.isnan(g.values[i, 2]) and np.isnan(g.values[i, 14]) and not np.isnan(g.values[i, 0])
    j = next(k for k in range(len(g.lats)) if (g.lats[k], g.lons[k]) == (8.0, 81.25))
    assert np.isnan(g.values[j]).all()
    assert np.all(g.values[~np.isnan(g.values)] != 9999.0)  # annual key ignored


# --------------------------------------------------------------------------- #
# Area-weighted aggregation vs brute force
# --------------------------------------------------------------------------- #

def brute_monthly_mean(cells_vals, box):
    num = den = 0.0
    for (lat, lon), v in cells_vals:
        if v is None or v == -999.0:
            continue
        la0, la1 = max(lat - 0.25, box.lat_min), min(lat + 0.25, box.lat_max)
        lo0, lo1 = max(lon - 0.3125, box.lon_min), min(lon + 0.3125, box.lon_max)
        if la1 <= la0 or lo1 <= lo0:
            continue
        w = R**2 * math.radians(lo1 - lo0) * (math.sin(math.radians(la1)) - math.sin(math.radians(la0)))
        num += w * v
        den += w
    return num / den, den


def test_weighted_monthly_mean_equals_brute_force_with_latitude_dependent_weights():
    box = BBox(52.0, 60.0, 5.0, 12.0)  # high latitude: weights vary strongly with latitude

    def val(lat, lon, y, m):
        if (lat, lon) == (55.0, 8.125) and m == 6:
            return -999.0
        return 0.3 * lat - 0.1 * lon + m

    g = ra.parse_regional_response(make_regional_payload(box, 2001, 2001, val), get_variable("T2M"), box, 2001, 2001)
    st = ra.weighted_monthly(g, 0.5)
    for t, m in enumerate(range(1, 13)):
        cells = [((la, lo), (None if ((la, lo) == (55.0, 8.125) and m == 6) else val(la, lo, 2001, m))) for la, lo in zip(g.lats, g.lons)]
        exp, den = brute_monthly_mean(cells, box)
        assert st["mean"][t] == pytest.approx(exp, rel=1e-12)
        assert st["valid_area_km2"][t] == pytest.approx(den, rel=1e-12)
    naive = np.nanmean(g.values[:, 0])
    assert st["mean"][0] != pytest.approx(naive, rel=1e-6)  # differs from an unweighted mean
    assert st["n_missing"][5] == 1 and st["coverage"][5] < 1 and st["coverage"][0] == pytest.approx(1.0)


def test_spread_min_max_are_weighted_and_correct():
    g = ra.parse_regional_response(make_regional_payload(BOX, 2001, 2001, lambda la, lo, y, m: la), get_variable("T2M"), BOX, 2001, 2001)
    st = ra.weighted_monthly(g, 0.8)
    w = g.overlap_km2
    mean = np.sum(w * g.lats) / w.sum()
    sd = math.sqrt(np.sum(w * (g.lats - mean) ** 2) / w.sum())
    assert st["mean"][0] == pytest.approx(mean) and st["sd"][0] == pytest.approx(sd)
    assert st["min"][0] == g.lats.min() and st["max"][0] == g.lats.max()


def test_coverage_threshold_flags_months_and_excludes_them_from_annual():
    # In March, cells with lat >= 8 are missing (well over 20% of the area).
    def val(lat, lon, y, m):
        return -999.0 if (m == 3 and lat >= 8.0) else 25.0 + 0.05 * (y - 2001)

    g = ra.parse_regional_response(make_regional_payload(BOX, 2001, 2012, val), get_variable("T2M"), BOX, 2001, 2012)
    st = ra.weighted_monthly(g, 0.8)
    assert set(st["status"][2::12]) == {"insufficient_coverage"}
    assert set(np.delete(st["status"], np.s_[2::12])) == {"valid"}


# --------------------------------------------------------------------------- #
# End-to-end regional analysis on fixtures (mocked NASA)
# --------------------------------------------------------------------------- #

class Session:
    def __init__(self, payload):
        self.payload, self.calls, self.headers = payload, [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        body = self.payload

        class Resp:
            status_code = 200

            def json(self_inner):
                return body

        return Resp()


def run(payload, var="T2M", box=BOX, start=2001, end=2015, thr=0.8):
    ran._results_cache.clear()
    client = NasaPowerClient(get_settings(), session=Session(payload))
    q = ran.RegionalQuery(get_variable(var), box, start, end, thr)
    return ran.build_regional_response(q, client, get_settings()), client


def test_uniform_increasing_and_decreasing_trends():
    for slope in (0.04, -0.03):
        res, _ = run(make_regional_payload(BOX, 2001, 2015, lambda la, lo, y, m, s=slope: 20 + 0.2 * la + s * (y - 2001) + m / 10))
        assert res["statistics"]["regression"]["slope"] == pytest.approx(slope, rel=1e-9)
        assert res["statistics"]["sens_slope"]["slope"] == pytest.approx(slope, rel=1e-9)


def test_opposing_trends_give_area_weighted_combined_slope():
    """North of 7.75° warms by +0.10/yr, south cools by −0.10/yr. With no missing data the
    regional OLS slope must equal the area-weighted mean of the cell slopes."""
    def val(lat, lon, y, m):
        return 25 + (0.10 if lat > 7.75 else -0.10) * (y - 2001) + 0.5 * math.sin(m)

    res, _ = run(make_regional_payload(BOX, 2001, 2015, val))
    cells = res["cells"]
    expected = sum(c["weight"] * (0.10 if c["latitude"] > 7.75 else -0.10) for c in cells)
    assert res["statistics"]["regression"]["slope"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert abs(expected) < 0.10  # partially cancels — not the slope of either half
    # Analysis is applied to the aggregated annual series:
    used = [a for a in res["annual"] if a["used_in_trend"]]
    direct = ta.linear_regression([a["year"] for a in used], [a["value"] for a in used])
    assert direct["slope"] == pytest.approx(res["statistics"]["regression"]["slope"])


def test_exactly_cancelling_trends_give_constant_mean_and_no_trend():
    # Symmetric weights: pair cells mirrored around the box centre longitude have equal area.
    box = BBox(-2.0, 2.0, 30.0, 32.5)

    def val(lat, lon, y, m):
        return 20 + (0.1 if lon > 31.25 else -0.1 if lon < 31.25 else 0.0) * (y - 2001)

    res, _ = run(make_regional_payload(box, 2001, 2015, val), box=box)
    assert res["statistics"] is None and res["analysis_error"] == "NO_VARIATION_IN_DATA"


def test_annual_regional_values_are_day_weighted_means_of_valid_months():
    res, _ = run(make_regional_payload(BOX, 2001, 2012, lambda la, lo, y, m: 10 + m + 0.01 * la))
    monthly = res["monthly"]
    y2004 = [r for r in monthly if r["year"] == 2004]
    exp = sum(r["value"] * calendar.monthrange(2004, r["month"])[1] for r in y2004) / 366
    a = next(a for a in res["annual"] if a["year"] == 2004)
    assert a["value"] == pytest.approx(exp, rel=1e-12)


def test_insufficient_years_reported_not_faked():
    def val(lat, lon, y, m):
        return -999.0 if y >= 2006 else 20 + y * 0.01

    res, _ = run(make_regional_payload(BOX, 2001, 2012, val), end=2012)
    assert res["statistics"] is None and res["analysis_error"] == "INSUFFICIENT_DATA_FOR_ANALYSIS"
    assert all(r["value"] is None for r in res["monthly"] if r["year"] >= 2006)


def test_land_only_variable_excludes_water_cells_and_rejects_ocean_regions():
    box = BBox(-2.0, 2.0, 30.0, 34.0)

    def soil(lat, lon, y, m):
        return 1.0 if lon >= 32.5 else 0.5 + 0.002 * (y - 2001) + 0.01 * m

    res, _ = run(make_regional_payload(box, 2001, 2015, soil, parameter="GWETTOP", units="1"), var="soil_wetness", box=box)
    excluded = [c for c in res["cells"] if c["status"] == "excluded"]
    assert excluded and all(c["exclusion_reason"] == "water_or_ice" and c["weight"] == 0 for c in excluded)
    assert 0 < res["metadata"]["land_fraction"] < 1
    assert res["summary"]["mean_coverage"] == pytest.approx(1.0)
    with pytest.raises(LocationNotSupportedError):
        run(make_regional_payload(box, 2001, 2015, lambda *a: 1.0, parameter="GWETTOP", units="1"), var="soil_wetness", box=box)


def test_weights_sum_to_one_and_partial_cells_weighted_by_overlap():
    res, _ = run(make_regional_payload(BOX, 2001, 2012, lambda la, lo, y, m: 20 + y * 0.01))
    assert sum(c["weight"] for c in res["cells"]) == pytest.approx(1.0)
    corner = next(c for c in res["cells"] if (c["latitude"], c["longitude"]) == (6.0, 79.375))
    assert corner["overlap_fraction"] == pytest.approx(0.15, rel=1e-3)


def test_request_uses_expanded_box_and_single_parameter():
    res, client = run(make_regional_payload(BOX, 2001, 2012, lambda *a: 20.0 + a[2] * 0.01))
    params = client.session.calls[0][1]
    assert params["parameters"] == "T2M" and params["latitude-min"] == "5.7500" and params["longitude-max"] == "82.3125"
    assert res["metadata"]["request_url"].startswith("https://power.larc.nasa.gov/api/temporal/monthly/regional?")


# --------------------------------------------------------------------------- #
# API: validation, outage, caching
# --------------------------------------------------------------------------- #

def api_client(session):
    nasa = NasaPowerClient(get_settings(), session=session)
    app.dependency_overrides[get_nasa_client] = lambda: nasa
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    ran._results_cache.clear()
    yield
    app.dependency_overrides.clear()


def test_api_analyze_and_processed_cache():
    session = Session(make_regional_payload(BOX, 2001, 2012, lambda la, lo, y, m: 20 + 0.03 * (y - 2001)))
    c = api_client(session)
    params = dict(variable="T2M", lat_min=6, lat_max=9.5, lon_min=79.5, lon_max=82, start_year=2001, end_year=2012)
    r1 = c.get("/api/regional/analyze", params=params)
    assert r1.status_code == 200, r1.json()
    r2 = c.get("/api/regional/analyze", params=params)
    assert len(session.calls) == 1 and r2.json()["metadata"]["served_from_cache"]
    r3 = c.get("/api/regional/analyze", params={**params, "coverage_threshold": 0.9})  # different science -> recompute
    assert r3.status_code == 200 and r3.json()["metadata"]["coverage_threshold"] == 0.9


@pytest.mark.parametrize(
    "params,code",
    [
        (dict(lat_min=6, lat_max=7, lon_min=79, lon_max=82), "REGION_TOO_SMALL"),
        (dict(lat_min=0, lat_max=12, lon_min=30, lon_max=35), "REGION_TOO_LARGE"),
        (dict(lat_min=-10, lat_max=-6, lon_min=178, lon_max=-178), "ANTIMERIDIAN_NOT_SUPPORTED"),
        (dict(lat_min=95, lat_max=99, lon_min=0, lon_max=5), "INVALID_REGION"),
        (dict(lat_min=6, lat_max=9, lon_min=79, lon_max=82, coverage_threshold=0.2), "INVALID_REQUEST"),
    ],
)
def test_api_validation(params, code):
    session = Session({})
    r = api_client(session).get("/api/regional/analyze", params={"variable": "T2M", **params})
    assert r.status_code == 422 and r.json()["error"] == code and session.calls == []


def test_api_outage_never_falls_back_to_synthetic():
    import requests

    class Down:
        headers: dict = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    r = api_client(Down()).get("/api/regional/analyze", params=dict(variable="T2M", lat_min=6, lat_max=9, lon_min=79, lon_max=82))
    assert r.status_code == 503 and r.json()["error"] == "NASA_API_UNAVAILABLE" and "statistics" not in r.json()


def test_api_config_and_preview():
    c = TestClient(app)
    cfg = c.get("/api/regional/config").json()
    assert cfg["min_span_deg"] == 2 and cfg["max_span_deg"] == 9 and len(cfg["presets"]) >= 6
    for p in cfg["presets"]:
        validate_bbox(p["bbox"]["lat_min"], p["bbox"]["lat_max"], p["bbox"]["lon_min"], p["bbox"]["lon_max"], 2, 9)
    pv = c.get("/api/regional/preview", params=dict(lat_min=6, lat_max=9.5, lon_min=79.5, lon_max=82)).json()
    assert pv["expected_cells"] == 40


def test_point_analysis_still_works_alongside_regional():
    from tests.conftest import make_power_payload
    from tests.test_nasa_power import FakeResponse, FakeSession

    c = api_client(FakeSession(FakeResponse(200, make_power_payload(start_year=2001, end_year=2012))))
    r = c.get("/api/analyze", params=dict(variable="T2M", latitude=6.9, longitude=79.8, start_year=2001, end_year=2012))
    assert r.status_code == 200 and r.json()["metadata"]["data_mode"] == "LIVE"


def test_regional_monthly_frame_is_not_mutated_by_trend_engine():
    df = pd.DataFrame({"year": range(2001, 2016), "value": np.linspace(1, 2, 15), "valid_months": 12,
                       "status": "complete", "used_in_trend": True})
    before = df.copy()
    ta.run_trend_analysis(df)
    pd.testing.assert_frame_equal(df, before)


def test_statistics_error_for_constant_input():
    with pytest.raises(StatisticsError):
        ta.linear_regression([2001, 2002, 2003], [1.0, 1.0, 1.0])
