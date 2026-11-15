"""Per-grid-cell spatial trend analysis and multiple-testing correction (fixtures only).

Expected values are computed independently of the application (explicit
day-weighted loops, numpy.polyfit, brute-force Mann-Kendall S, hand-worked
FDR examples, statsmodels.multipletests). NASA is mocked; see
scripts/live_spatial_validation.py for the live equivalent.
"""

from __future__ import annotations

import calendar
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import stats
from statsmodels.stats.multitest import multipletests

from app.api.deps import get_nasa_client
from app.core.catalog import get_variable
from app.core.config import get_settings
from app.main import app
from app.services import data_processing as dp
from app.services import regional_analysis as ran
from app.services import spatial_trend_analysis as sta
from app.services.nasa_power import NasaPowerClient
from app.services.regional_grid import EARTH_RADIUS_KM, BBox, request_box
from app.services.spatial_significance import adjust_pvalues, family_size
from app.services.trend_analysis import run_trend_analysis
from tests.conftest import make_power_payload
from tests.test_regional import Session, centres_in, make_regional_payload

BOX = BBox(6.0, 9.5, 79.5, 82.0)
START, END = 2001, 2020
YEARS = np.arange(START, END + 1)


@pytest.fixture(autouse=True)
def _clean():
    sta._cell_cache.clear()
    ran._results_cache.clear()
    yield
    app.dependency_overrides.clear()


def noise(lat, lon, y, m, scale=0.3):
    """Deterministic pseudo-random noise per cell-month (hash of floats/ints is not randomised)."""
    return float(np.random.default_rng(abs(hash((lat, lon, y, m))) % (2**32)).normal(0, scale))


def run(fn, box=BOX, var="T2M", units="C", method="mann_kendall", correction="fdr_bh", alpha=0.05, extra=None):
    payload = make_regional_payload(box, START, END, fn, parameter=get_variable(var).parameter, units=units, extra=extra)
    session = Session(payload)
    client = NasaPowerClient(get_settings(), session=session)
    q = ran.RegionalQuery(get_variable(var), box, START, END, 0.8)
    return sta.build_spatial_response(q, client, get_settings(), method, correction, alpha), q, client, session


def indep_annual(fn, lat, lon, skip=lambda y, m: False):
    """Day-weighted annual means computed with plain loops (independent of the app)."""
    out = []
    for y in YEARS:
        num = den = 0.0
        for m in range(1, 13):
            if skip(y, m):
                continue
            d = calendar.monthrange(int(y), m)[1]
            num += fn(lat, lon, int(y), m) * d
            den += d
        out.append(num / den)
    return np.array(out)


def brute_mk_s(y):
    return sum(np.sign(y[j] - y[i]) for i in range(len(y) - 1) for j in range(i + 1, len(y)))


def by_id(res):
    return {c["id"]: c for c in res["cells"]}


# --------------------------------------------------------------------------- #
# Test A / B — known increasing and decreasing trends
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("sign", [1, -1])
def test_known_trends_slopes_direction_and_tests(sign):
    slope_of = lambda lat, lon: sign * (0.02 + 0.01 * (lat - 6.0))  # noqa: E731 — slope varies by cell
    fn = lambda lat, lon, y, m: 25 + slope_of(lat, lon) * (y - START) + noise(lat, lon, y, m)  # noqa: E731
    res, *_ = run(fn)
    assert res["available"] and res["summary"]["n_hypotheses"] == len(res["cells"]) == 40
    for c in res["cells"]:
        ann = indep_annual(fn, c["latitude"], c["longitude"])
        assert c["ols_slope"] == pytest.approx(np.polyfit(YEARS, ann, 1)[0], abs=1e-10)
        assert c["mk_s"] == brute_mk_s(ann)
        n = len(ann)
        var_s = n * (n - 1) * (2 * n + 5) / 18          # no ties in continuous data
        z = (abs(c["mk_s"]) - 1) / math.sqrt(var_s)
        assert c["mk_p_value"] == pytest.approx(2 * stats.norm.sf(z), rel=1e-9)
        pairs = [(ann[j] - ann[i]) / (YEARS[j] - YEARS[i]) for i in range(n) for j in range(i + 1, n)]
        assert c["sen_slope"] == pytest.approx(np.median(pairs), abs=1e-12)
        assert c["direction_sen"] == ("increasing" if sign > 0 else "decreasing")
        assert c["status"] == ("significant_increasing" if sign > 0 else "significant_decreasing")
        assert c["sen_ci_lower"] <= c["sen_slope"] <= c["sen_ci_upper"]


def test_exact_linear_series_recovers_the_true_slope_per_cell():
    fn = lambda lat, lon, y, m: 10 + (0.01 * lat - 0.002 * lon) * (y - START)  # noqa: E731 — no noise, no seasonality
    res, *_ = run(fn)
    for c in res["cells"]:
        true = 0.01 * c["latitude"] - 0.002 * c["longitude"]
        assert c["ols_slope"] == pytest.approx(true, abs=1e-10)
        assert c["sen_slope"] == pytest.approx(true, abs=1e-10)
        assert c["ols_r_squared"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Test C — opposing local trends; the regional aggregate is computed separately
# --------------------------------------------------------------------------- #

def test_opposing_local_trends_are_not_hidden():
    b = lambda lon: 0.06 if lon < 80.75 else -0.06  # noqa: E731
    fn = lambda lat, lon, y, m: 15 + b(lon) * (y - START) + noise(lat, lon, y, m, 0.05)  # noqa: E731
    res, *_ = run(fn)
    cells = res["cells"]
    for c in cells:
        ann = indep_annual(fn, c["latitude"], c["longitude"])
        assert c["ols_slope"] == pytest.approx(np.polyfit(YEARS, ann, 1)[0], abs=1e-10)
        assert np.sign(c["ols_slope"]) == np.sign(b(c["longitude"]))
    cats = res["summary"]["categories"]
    assert cats["significant_increasing"]["count"] > 0 and cats["significant_decreasing"]["count"] > 0
    # Regional aggregate: an independent quantity (trend of the area-weighted mean series).
    reg = res["regional_aggregate"]
    w = np.array([c["overlap_area_km2"] for c in cells])
    expected = float(np.sum(w * np.array([c["ols_slope"] for c in cells])) / w.sum())
    # OLS is linear in y, so with complete data the regional slope equals Σw·b exactly.
    assert res["summary"]["slope_identity_exact"] is True
    assert reg["ols_slope"] == pytest.approx(expected, abs=1e-9)
    assert res["summary"]["area_weighted_mean_ols_slope"] == pytest.approx(expected, abs=1e-12)
    assert abs(reg["ols_slope"]) < 0.03  # the average hides ±0.06 local trends
    text = " ".join(res["interpretation"])
    assert "both positive and negative" in text and "conceal" in text


# --------------------------------------------------------------------------- #
# Test D — constant series
# --------------------------------------------------------------------------- #

def test_constant_region_is_not_a_significant_trend_and_no_map_is_claimed():
    res, *_ = run(lambda lat, lon, y, m: 25.0)
    assert res["available"] is False and res["summary"]["n_hypotheses"] == 0
    assert all(c["data_status"] == "no_variation" and c["status"] == "not_testable" for c in res["cells"])
    assert res["summary"]["categories"]["significant_increasing"]["count"] == 0
    assert "No grid cell" in res["interpretation"][0]


def test_one_constant_cell_among_trending_cells():
    fn = lambda lat, lon, y, m: 25.0 if (lat, lon) == (7.0, 80.625) else 20 + 0.05 * (y - START) + noise(lat, lon, y, m)  # noqa: E731
    res, *_ = run(fn)
    c = by_id(res)["7.000_80.6250"]
    assert c["data_status"] == "no_variation" and c["status"] == "not_testable" and not c["in_family"]
    assert res["summary"]["n_hypotheses"] == 39


# --------------------------------------------------------------------------- #
# Test E — missing months, missing years, insufficient coverage, invalid markers
# --------------------------------------------------------------------------- #

def test_missing_observations():
    def fn(lat, lon, y, m):
        if (lat, lon) == (7.0, 80.625):
            return -999.0                                        # all missing
        if (lat, lon) == (8.0, 80.625) and m <= 3:
            return -999.0                                        # 9 valid months every year
        if (lat, lon) == (8.5, 81.25) and y <= 2011:
            return -999.0                                        # 11 of 20 years missing
        if (lat, lon) == (7.5, 81.25) and m == 6:
            return -999.0                                        # June missing: 11 months, still usable
        if (lat, lon) == (6.5, 80.0) and (y, m) == (2005, 3):
            return 500.0                                         # physically impossible -> missing
        return 20 + 0.04 * (y - START) + noise(lat, lon, y, m)

    res, *_ = run(fn)
    c = by_id(res)
    assert c["7.000_80.6250"]["availability"] == "missing" and c["7.000_80.6250"]["status"] == "insufficient_data"
    assert c["8.000_80.6250"]["valid_years"] == 0 and c["8.000_80.6250"]["status"] == "insufficient_data"
    assert c["8.500_81.2500"]["valid_years"] == 9 and c["8.500_81.2500"]["availability"] == "insufficient"
    june = c["7.500_81.2500"]
    assert june["availability"] == "partial" and june["valid_months"] == 220 and june["data_status"] == "analysed"
    ann = indep_annual(fn, 7.5, 81.25, skip=lambda y, m: m == 6)
    assert june["ols_slope"] == pytest.approx(np.polyfit(YEARS, ann, 1)[0], abs=1e-10)
    assert c["6.500_80.0000"]["valid_months"] == 239
    for cid in ("7.000_80.6250", "8.000_80.6250", "8.500_81.2500"):
        assert not c[cid]["in_family"] and c[cid]["raw_p_value"] is None and c[cid]["ols_slope"] is None
    assert res["summary"]["n_hypotheses"] == 37
    assert res["summary"]["categories"]["insufficient_data"]["count"] == 3
    assert res["summary"]["slope_identity_exact"] is False


# --------------------------------------------------------------------------- #
# Test F — FDR arithmetic against independent references
# --------------------------------------------------------------------------- #

BH_1995 = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344, 0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0]


def test_bh_worked_example_from_benjamini_hochberg_1995():
    q = adjust_pvalues(BH_1995, "fdr_bh")
    assert sum(v <= 0.05 for v in q) == 4      # the paper rejects the four smallest at q* = 0.05


def test_hand_computed_bh_and_by():
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted .005,.01,.03,.04 -> ×4/k = .02,.02,.04,.04 -> running min from the right
    assert adjust_pvalues(p, "fdr_bh") == pytest.approx([0.02, 0.04, 0.04, 0.02])
    c = 1 + 1 / 2 + 1 / 3 + 1 / 4
    assert adjust_pvalues(p, "fdr_by") == pytest.approx([0.02 * c, 0.04 * c, 0.04 * c, 0.02 * c])
    assert adjust_pvalues([0.01, 0.01, 0.01], "fdr_bh") == pytest.approx([0.01] * 3)   # ties share q
    assert adjust_pvalues([0.9, 0.95], "fdr_by") == pytest.approx([1.0, 1.0])             # capped at 1


@pytest.mark.parametrize("method", ["fdr_bh", "fdr_by"])
def test_matches_statsmodels_including_ties_and_order(method):
    rng = np.random.default_rng(7)
    p = np.round(np.concatenate([rng.uniform(0, 0.01, 40), rng.uniform(0, 1, 160)]), 3)  # rounding creates ties
    rng.shuffle(p)
    reject, ref, *_ = multipletests(p, alpha=0.05, method=method)
    ours = np.array(adjust_pvalues(list(p), method))
    assert ours == pytest.approx(ref, abs=1e-12)
    assert np.array_equal(ours <= 0.05, reject)


def test_invalid_pvalues_are_excluded_from_the_family():
    p = [0.001, None, float("nan"), 1.5, -0.1, 0.02, 0.04]
    assert family_size(p) == 3
    q = adjust_pvalues(p, "fdr_bh")
    assert q[1:5] == [None] * 4
    assert [q[0], q[5], q[6]] == pytest.approx(list(multipletests([0.001, 0.02, 0.04], method="fdr_bh")[1]))
    with pytest.raises(ValueError):
        adjust_pvalues([0.1], "bonferroni_typo")


def test_family_is_all_testable_cells_and_methods_are_not_mixed():
    fn = lambda lat, lon, y, m: 20 + (0.03 if lat < 7.75 else 0.0) * (y - START) + noise(lat, lon, y, m, 0.4)  # noqa: E731
    for method, key in [("mann_kendall", "mk_p_value"), ("hamed_rao_canonical", "hr_canonical_p_value"),
                        ("hamed_rao_conservative", "hr_conservative_p_value"), ("yue_wang_canonical", "yw_canonical_p_value")]:
        sta._cell_cache.clear()
        res, *_ = run(fn, method=method)
        fam = [c for c in res["cells"] if c["in_family"]]
        raw = [c[key] for c in fam]
        assert all(c["raw_p_value"] == c[key] for c in fam)                   # one test only
        ref = multipletests(raw, method="fdr_bh")[1]
        assert [c["adjusted_p_value"] for c in fam] == pytest.approx(list(ref))
        assert res["config"]["n_hypotheses"] == len(fam) == family_size(raw)
        # Significance is decided on q for every family member, not only on raw-significant cells.
        for c in fam:
            assert c["status"].startswith("significant") == (c["adjusted_p_value"] <= 0.05)


def test_conservative_hamed_rao_is_never_more_significant_than_canonical_when_reduced():
    fn = lambda lat, lon, y, m: 20 + 0.02 * (y - START) + (0.8 if y % 2 else -0.8) + noise(lat, lon, y, m, 0.1)  # alternating -> negative r1
    res, *_ = run(fn, method="hamed_rao_conservative", correction="none")
    pairs = [(c["hr_conservative_p_value"], c["hr_canonical_p_value"]) for c in res["cells"]
             if c["hr_canonical_p_value"] is not None and c["hr_conservative_p_value"] is not None]
    assert pairs and all(cons >= canon - 1e-12 for cons, canon in pairs)
    assert any(cons > canon + 1e-6 for cons, canon in pairs), "fixture must contain cells where the floor was applied"
    # The canonical and conservative tests are separate options with separate p-values.
    assert all(c["raw_p_value"] == c["hr_conservative_p_value"] for c in res["cells"] if c["in_family"])


# --------------------------------------------------------------------------- #
# Test G — changing the threshold never changes the family or the p-values
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("method", ["mann_kendall", "hamed_rao_canonical"])
def test_changing_alpha_keeps_the_family_and_pvalues(method):
    fn = lambda lat, lon, y, m: 20 + 0.02 * (lat - 7.5) * (y - START) + noise(lat, lon, y, m, 0.5)  # noqa: E731
    out = {}
    for a in (0.01, 0.05, 0.10):
        res, *_ = run(fn, method=method, alpha=a)
        out[a] = res
    base = out[0.05]
    for a in (0.01, 0.10):
        assert out[a]["summary"]["n_hypotheses"] == base["summary"]["n_hypotheses"]
        assert [c["raw_p_value"] for c in out[a]["cells"]] == [c["raw_p_value"] for c in base["cells"]]
        assert [c["adjusted_p_value"] for c in out[a]["cells"]] == [c["adjusted_p_value"] for c in base["cells"]]
    d = [out[a]["summary"]["n_fdr_discoveries"] for a in (0.01, 0.05, 0.10)]
    assert d == sorted(d)


# --------------------------------------------------------------------------- #
# Test H — behaviour under spatially correlated null fields (Monte Carlo)
# --------------------------------------------------------------------------- #

def _correlated_null_pvalues(rng, n_side=10, corr_range=3.0, reps=600):
    xy = np.array([(i, j) for i in range(n_side) for j in range(n_side)], dtype=float)
    d = np.linalg.norm(xy[:, None] - xy[None], axis=2)
    L = np.linalg.cholesky(np.exp(-d / corr_range) + 1e-10 * np.eye(len(xy)))
    z = rng.standard_normal((reps, len(xy))) @ L.T
    return 2 * stats.norm.sf(np.abs(z))


def test_fdr_under_spatially_correlated_null():
    """All cells trendless but neighbours correlated (exponential covariance, range 3 cells).

    Under the global null every discovery is false, so P(≥1 discovery) is the
    FDR. Raw p < 0.05 gives many false 'trend' maps; BH stays near α in this
    positively-dependent setting (PRDS), BY is never more liberal than BH.
    This is evidence for the simulated case only — not a proof for arbitrary
    real spatial dependence (see README).
    """
    pv = _correlated_null_pvalues(np.random.default_rng(42))
    raw = np.mean([(row < 0.05).any() for row in pv])
    bh = np.mean([(np.array(adjust_pvalues(list(row), "fdr_bh")) <= 0.05).any() for row in pv])
    by = np.mean([(np.array(adjust_pvalues(list(row), "fdr_by")) <= 0.05).any() for row in pv])
    se = math.sqrt(0.05 * 0.95 / len(pv))
    assert raw > 0.5                  # uncorrected maps almost always show spurious "trends"
    assert bh <= 0.05 + 3 * se
    assert by <= bh


def test_by_discoveries_are_a_subset_of_bh():
    rng = np.random.default_rng(3)
    for _ in range(50):
        p = np.concatenate([rng.uniform(0, 0.02, 10), rng.uniform(0, 1, 90)])
        bh = np.array(adjust_pvalues(list(p), "fdr_bh")) <= 0.05
        by = np.array(adjust_pvalues(list(p), "fdr_by")) <= 0.05
        assert not np.any(by & ~bh)


# --------------------------------------------------------------------------- #
# Test I — geometry: cells, partial overlaps, weights, clipping
# --------------------------------------------------------------------------- #

def test_cells_partial_overlap_and_weights():
    res, *_ = run(lambda lat, lon, y, m: 20 + 0.03 * (y - START) + noise(lat, lon, y, m))
    req = request_box(BOX)
    expected = {}
    for lat, lon in centres_in(req.lat_min, req.lat_max, req.lon_min, req.lon_max):
        la0, la1 = max(lat - 0.25, BOX.lat_min), min(lat + 0.25, BOX.lat_max)
        lo0, lo1 = max(lon - 0.3125, BOX.lon_min), min(lon + 0.3125, BOX.lon_max)
        if la1 > la0 and lo1 > lo0:
            area = EARTH_RADIUS_KM**2 * math.radians(lo1 - lo0) * (math.sin(math.radians(la1)) - math.sin(math.radians(la0)))
            expected[f"{lat:.3f}_{lon:.4f}"] = area
    cells = by_id(res)
    assert set(cells) == set(expected)                       # nothing outside the box is tested
    for cid, area in expected.items():
        c = cells[cid]
        assert c["overlap_area_km2"] == pytest.approx(area, rel=1e-9)
        assert c["lat_max"] - c["lat_min"] == pytest.approx(0.5) and c["lon_max"] - c["lon_min"] == pytest.approx(0.625)
        inside = BOX.lat_min <= c["lat_min"] and c["lat_max"] <= BOX.lat_max and BOX.lon_min <= c["lon_min"] and c["lon_max"] <= BOX.lon_max
        assert (c["overlap_fraction"] > 0.999) == inside
    assert sum(c["weight"] for c in res["cells"]) == pytest.approx(1.0)
    s = res["summary"]
    assert s["tested_area_km2"] == pytest.approx(sum(expected.values()))
    tot = s["categories"]["significant_increasing"]
    assert tot["pct_of_tested_area"] == pytest.approx(tot["area_km2"] / s["tested_area_km2"] * 100)


def test_land_only_water_cells_are_excluded_from_the_family():
    fn = lambda lat, lon, y, m: 1.0 if lon > 81.5 else 0.4 + 0.004 * (y - START) + noise(lat, lon, y, m, 0.02)  # noqa: E731
    res, *_ = run(fn, var="GWETTOP", units="1")
    water = [c for c in res["cells"] if c["longitude"] > 81.5]
    assert water and all(c["status"] == "excluded" and not c["in_family"] and c["weight"] == 0 for c in water)
    assert res["summary"]["n_cells_excluded"] == len(water)
    assert res["summary"]["categories"]["excluded"]["pct_of_included_cells"] is None


# --------------------------------------------------------------------------- #
# Test J — consistency with the point-analysis engine for the same series
# --------------------------------------------------------------------------- #

def test_cell_matches_point_analysis_of_the_same_series():
    fn = lambda lat, lon, y, m: 18 + 3 * math.sin(m) + 0.035 * (y - START) + noise(lat, lon, y, m, 0.6)  # noqa: E731
    res, *_ = run(fn)
    lat, lon = 7.5, 80.625
    cell = by_id(res)["7.500_80.6250"]
    point = make_power_payload("T2M", START, END, value_fn=lambda y, m: fn(lat, lon, y, m))
    parsed = dp.parse_power_response(point, get_variable("T2M"), START, END)
    stats_point = run_trend_analysis(dp.aggregate_annual(parsed.monthly, 10), min_records=10)
    adv = stats_point["advanced"]
    assert cell["ols_slope"] == pytest.approx(stats_point["regression"]["slope"], abs=1e-12)
    assert cell["ols_p_value"] == pytest.approx(stats_point["regression"]["p_value"], abs=1e-12)
    assert cell["mk_p_value"] == pytest.approx(stats_point["mann_kendall"]["p_value"], abs=1e-12)
    assert cell["sen_slope"] == pytest.approx(stats_point["sens_slope"]["slope"], abs=1e-12)
    assert cell["hr_canonical_p_value"] == pytest.approx(adv["modified_mann_kendall"]["canonical_p_value"], abs=1e-12)
    assert cell["yw_canonical_p_value"] == pytest.approx(adv["yue_wang_sensitivity"]["canonical_p_value"], abs=1e-12)
    assert cell["lag1_autocorrelation"] == pytest.approx(adv["autocorrelation"]["lag1"], abs=1e-12)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

PARAMS = dict(variable="T2M", lat_min=6, lat_max=9.5, lon_min=79.5, lon_max=82, start_year=START, end_year=END)


def api(session):
    app.dependency_overrides[get_nasa_client] = lambda: NasaPowerClient(get_settings(), session=session)
    return TestClient(app)


def trend_fn(lat, lon, y, m):
    return 20 + 0.04 * (lat - 7.5) * (y - START) + noise(lat, lon, y, m)


def test_api_reuses_one_nasa_request_for_every_setting_and_cell():
    session = Session(make_regional_payload(BOX, START, END, trend_fn))
    c = api(session)
    r = c.get("/api/regional/spatial-trends", params=PARAMS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metadata"]["data_mode"] == "LIVE" and body["config"]["method"] == "mann_kendall"
    assert body["config"]["correction"] == "fdr_bh" and body["config"]["alpha"] == 0.05
    for extra in ({"method": "hamed_rao_canonical"}, {"correction": "fdr_by"}, {"alpha": 0.1}, {"correction": "none", "alpha": 0.01}):
        rr = c.get("/api/regional/spatial-trends", params={**PARAMS, **extra})
        assert rr.status_code == 200 and rr.json()["config"]["method"] == extra.get("method", "mann_kendall")
    cid = body["cells"][5]["id"]
    d = c.get("/api/regional/spatial-trends/cell", params={**PARAMS, "cell_id": cid})
    assert d.status_code == 200
    det = d.json()
    assert len(det["annual"]) == END - START + 1 and det["statistics"]["regression"]["slope"] == pytest.approx(body["cells"][5]["ols_slope"])
    assert det["cell"]["adjusted_p_value"] == pytest.approx(body["cells"][5]["adjusted_p_value"])
    assert len(det["regional_annual"]) == END - START + 1
    assert len(session.calls) == 1, "settings changes and cell details must reuse the cached NASA data"


@pytest.mark.parametrize("extra", [{"method": "spearman"}, {"correction": "bonferroni"}, {"alpha": 0.2}])
def test_api_rejects_unsupported_settings_before_calling_nasa(extra):
    session = Session(make_regional_payload(BOX, START, END, trend_fn))
    r = api(session).get("/api/regional/spatial-trends", params={**PARAMS, **extra})
    assert r.status_code == 422 and r.json()["error"] == "INVALID_REQUEST" and session.calls == []


def test_api_unknown_cell_and_invalid_region():
    session = Session(make_regional_payload(BOX, START, END, trend_fn))
    c = api(session)
    assert c.get("/api/regional/spatial-trends/cell", params={**PARAMS, "cell_id": "0.000_0.0000"}).json()["error"] == "INVALID_REQUEST"
    r = c.get("/api/regional/spatial-trends", params={**PARAMS, "lat_max": 30})
    assert r.status_code == 422 and r.json()["error"] == "REGION_TOO_LARGE"


def test_api_outage_never_falls_back_to_synthetic():
    import requests

    class Down:
        headers: dict = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    r = api(Down()).get("/api/regional/spatial-trends", params=PARAMS)
    assert r.status_code == 503 and r.json()["error"] == "NASA_API_UNAVAILABLE" and "cells" not in r.json()


def test_api_ocean_soil_wetness_is_rejected():
    session = Session(make_regional_payload(BOX, START, END, lambda *a: 1.0, parameter="GWETTOP", units="1"))
    r = api(session).get("/api/regional/spatial-trends", params={**PARAMS, "variable": "GWETTOP"})
    assert r.status_code == 422 and r.json()["error"] == "LOCATION_NOT_SUPPORTED"


def test_api_response_is_gzip_compressed():
    session = Session(make_regional_payload(BOX, START, END, trend_fn))
    r = api(session).get("/api/regional/spatial-trends", params=PARAMS, headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
