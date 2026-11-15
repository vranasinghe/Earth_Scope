"""Independent validation of the autocorrelation-aware statistics.

References (none of them is the application's own code):
* statsmodels — sample ACF, Ljung–Box test, OLS with HAC (Newey–West) covariance;
* pymannkendall — Hamed–Rao (lag=3) and Yue–Wang (lag=1) modified tests, gap-free series;
* a from-scratch, gap-aware Hamed–Rao reference written below;
* a from-scratch Sen (1968) rank-based confidence interval written below.

Synthetic series are used ONLY for testing.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
import pymannkendall as pmk
import pytest
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf as sm_acf

from app.core.catalog import get_variable
from app.services import advanced_statistics as adv
from app.services import trend_analysis as ta
from app.services.interpretation import build_advanced_interpretation


def ar1(n: int, phi: float, seed: int, trend: float = 0.0, sd: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    e = np.zeros(n)
    e[0] = rng.normal(0, sd)
    for t in range(1, n):
        e[t] = phi * e[t - 1] + rng.normal(0, sd)
    return trend * np.arange(n) + e


SERIES = {
    "white_noise": ar1(30, 0.0, 1),
    "positive_ar": ar1(40, 0.8, 2, trend=0.03),
    "negative_ar": ar1(40, -0.7, 3, trend=0.03),
    "increasing": ar1(30, 0.2, 4, trend=0.15),
    "decreasing": ar1(30, 0.2, 5, trend=-0.15),
    "random": np.random.default_rng(6).uniform(0, 10, 25),
    "ties": np.array([3, 3, 4, 4, 4, 5, 5, 6, 6, 6, 7, 7, 7, 8, 8, 9, 9, 9, 10, 10], dtype=float),
    "small_n": ar1(10, 0.3, 7, trend=0.2),
}


def years_for(y: np.ndarray, start: int = 1990) -> np.ndarray:
    return np.arange(start, start + len(y))


def app_stats(y, years=None):
    years = years_for(y) if years is None else np.asarray(years)
    annual = pd.DataFrame({"year": years, "value": y, "valid_months": 12, "status": "complete", "used_in_trend": True})
    return ta.run_trend_analysis(annual, min_records=10)


# --------------------------------------------------------------------------- #
# Autocorrelation diagnostics vs statsmodels
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", list(SERIES))
def test_acf_matches_statsmodels_for_complete_series(name):
    y = SERIES[name]
    yrs = years_for(y)
    mine = adv.acf_by_year(yrs, y, 8)
    ref = sm_acf(y, nlags=8, adjusted=False, fft=False)
    assert np.allclose(mine, ref, atol=1e-12)


@pytest.mark.parametrize("name", ["white_noise", "positive_ar", "negative_ar", "increasing"])
def test_ljung_box_matches_statsmodels(name):
    y = SERIES[name]
    yrs = years_for(y)
    sen = ta.sens_slope(yrs, y)["slope"]
    diag = adv.autocorrelation_diagnostics(yrs, y, sen)
    resid = y - sen * yrs
    ref = acorr_ljungbox(resid, lags=[diag["ljung_box"]["lags"]], return_df=True)
    assert diag["ljung_box"]["q"] == pytest.approx(float(ref["lb_stat"].iloc[0]), rel=1e-10)
    assert diag["ljung_box"]["p_value"] == pytest.approx(float(ref["lb_pvalue"].iloc[0]), rel=1e-8)


def test_diagnostics_classify_positive_negative_and_none():
    pos = app_stats(SERIES["positive_ar"])["advanced"]["autocorrelation"]
    neg = app_stats(SERIES["negative_ar"])["advanced"]["autocorrelation"]
    none = app_stats(SERIES["white_noise"])["advanced"]["autocorrelation"]
    assert pos["lag1_assessment"] == "significant_positive" and pos["lag1"] > pos["bound"]
    assert neg["lag1_assessment"] == "significant_negative" and neg["lag1"] < -neg["bound"]
    assert none["lag1_assessment"] == "not_significant"
    assert none["bound"] == pytest.approx(1.959964 / math.sqrt(30), rel=1e-5)


def test_acf_with_missing_years_skips_pairs_across_gaps():
    yrs = np.array([2000, 2001, 2002, 2004, 2005, 2006, 2008, 2009, 2010, 2011])
    v = np.array([1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 5.0, 8.0, 7.0, 9.0])
    d = v - v.mean()
    pairs1 = [(0, 1), (1, 2), (3, 4), (4, 5), (6, 7), (7, 8), (8, 9)]  # exactly 1 year apart
    expected = sum(d[i] * d[j] for i, j in pairs1) / np.sum(d**2)
    assert adv.acf_by_year(yrs, v, 1)[1] == pytest.approx(expected)
    diag = adv.autocorrelation_diagnostics(yrs, v, 0.0)
    assert diag["has_gaps"] and any("missing" in n for n in diag["notes"])


# --------------------------------------------------------------------------- #
# Modified Mann-Kendall vs pymannkendall
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", list(SERIES))
def test_hamed_rao_matches_pymannkendall(name):
    y = SERIES[name]
    s_all = app_stats(y)
    hr = s_all["advanced"]["modified_mann_kendall"]
    with np.errstate(invalid="ignore"):
        ref = pmk.hamed_rao_modification_test(y, alpha=0.05, lag=3)
    assert hr["available"] and hr["s"] == ref.s
    # The RAW (unfloored) factor reproduces pymannkendall's variance exactly.
    assert hr["raw_correction_factor"] * hr["var_s_original"] == pytest.approx(ref.var_s, rel=1e-10)
    if hr["raw_correction_factor"] >= 1:
        assert hr["var_s"] == pytest.approx(ref.var_s, rel=1e-10)
        assert hr["z"] == pytest.approx(ref.z, rel=1e-10, abs=1e-12)
        assert hr["p_value"] == pytest.approx(ref.p, rel=1e-9, abs=1e-15)
        assert hr["significant"] == bool(ref.h)
    else:
        # Conservative floor: a variance reduction is never applied.
        assert hr["reduction_suppressed"] and hr["correction_factor"] == 1.0
        assert hr["p_value"] == pytest.approx(s_all["mann_kendall"]["p_value"])


@pytest.mark.parametrize("name", list(SERIES))
def test_yue_wang_matches_pymannkendall(name):
    y = SERIES[name]
    yw = app_stats(y)["advanced"]["yue_wang_sensitivity"]
    with np.errstate(invalid="ignore"):
        ref = pmk.yue_wang_modification_test(y, alpha=0.05, lag=1)
    assert yw["raw_correction_factor"] * yw["var_s_original"] == pytest.approx(ref.var_s, rel=1e-9)
    if ref.var_s < yw["var_s_original"]:
        # Negative lag-1 autocorrelation: pymannkendall shrinks the variance (and for
        # rho1 < -0.5 returns a NEGATIVE variance and a NaN p-value). Earth Scope
        # applies the conservative floor instead and stays equal to the original test.
        assert yw["reduction_suppressed"] and yw["correction_factor"] == 1.0 and yw["available"]
        return
    assert yw["var_s"] == pytest.approx(ref.var_s, rel=1e-9)
    assert yw["p_value"] == pytest.approx(ref.p, rel=1e-8, abs=1e-15)


def test_original_mann_kendall_is_retained_unchanged():
    y = SERIES["positive_ar"]
    s = app_stats(y)
    ref = pmk.original_test(y)
    assert s["mann_kendall"]["p_value"] == pytest.approx(ref.p)
    assert s["advanced"]["modified_mann_kendall"]["var_s_original"] == pytest.approx(ref.var_s)


def test_no_autocorrelation_means_no_correction():
    hr = app_stats(SERIES["white_noise"])["advanced"]["modified_mann_kendall"]
    orig = app_stats(SERIES["white_noise"])["mann_kendall"]
    assert hr["significant_lags"] == [] and not hr["correction_applied"]
    assert hr["correction_factor"] == 1.0
    assert hr["p_value"] == pytest.approx(orig["p_value"])


def test_positive_autocorrelation_inflates_variance_and_p():
    s = app_stats(SERIES["positive_ar"])
    hr = s["advanced"]["modified_mann_kendall"]
    assert hr["correction_applied"] and hr["correction_factor"] > 1
    assert hr["p_value"] >= s["mann_kendall"]["p_value"]
    assert hr["effective_n"] < hr["n"]


def test_negative_autocorrelation_is_detected_but_never_reduces_variance():
    s = app_stats(SERIES["negative_ar"])
    hr = s["advanced"]["modified_mann_kendall"]
    assert hr["significant_lags"] and hr["raw_correction_factor"] < 1
    assert hr["reduction_suppressed"] and not hr["correction_applied"]
    assert hr["correction_factor"] == 1.0
    assert hr["p_value"] == pytest.approx(s["mann_kendall"]["p_value"])


@pytest.mark.parametrize("seed", range(60))
def test_robust_evidence_is_never_more_significant_than_standard(seed):
    phi = [-0.7, -0.3, 0.0, 0.4, 0.8][seed % 5]
    y = ar1(25, phi, 500 + seed, trend=[0.0, 0.04, -0.04][seed % 3])
    s = app_stats(y)
    hr = s["advanced"]["modified_mann_kendall"]
    assert hr["p_value"] >= s["mann_kendall"]["p_value"] - 1e-15
    if s["evidence"]["category"] == "not_significant":
        assert s["advanced"]["robust_evidence"]["category"] == "not_significant"
    if s["advanced"]["robust_evidence"]["category"].startswith("significant_"):
        assert s["evidence"]["category"] == s["advanced"]["robust_evidence"]["category"]


def test_small_sample_flags_limited_reliability():
    hr = app_stats(SERIES["small_n"])["advanced"]["modified_mann_kendall"]
    assert hr["n"] == 10 and hr["reliable"] is False
    assert "Only 10 years" in hr["reliability_note"]


def ref_hamed_rao_gap_aware(years, y, alpha=0.05, max_lag=3):
    """From-scratch reference: same formulas, independently coded."""
    n = len(y)
    s = sum(np.sign(y[j] - y[i]) for i, j in itertools.combinations(range(n), 2))
    vals, counts = np.unique(y, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5) - sum(c * (c - 1) * (2 * c + 5) for c in counts)) / 18
    sl = [(y[j] - y[i]) / (years[j] - years[i]) for i, j in itertools.combinations(range(n), 2)]
    b = float(np.median(sl))
    r = stats.rankdata([y[k] - b * years[k] for k in range(n)])
    m = r.mean()
    den = sum((ri - m) ** 2 for ri in r)
    pos = {int(years[k]): r[k] - m for k in range(n)}
    bound = stats.norm.ppf(1 - alpha / 2) / math.sqrt(n)
    total = 0.0
    for lag in range(1, max_lag + 1):
        rho = sum(pos[t] * pos[t + lag] for t in pos if t + lag in pos) / den
        if abs(rho) > bound:
            total += (n - lag) * (n - lag - 1) * (n - lag - 2) * rho
    factor = 1 + 2 / (n * (n - 1) * (n - 2)) * total
    v = var_s * factor
    z = (s - 1) / math.sqrt(v) if s > 0 else (s + 1) / math.sqrt(v) if s < 0 else 0.0
    return factor, 2 * stats.norm.sf(abs(z))


def test_hamed_rao_with_missing_years_matches_independent_reference():
    base = ar1(36, 0.6, 11, trend=0.05)
    yrs = years_for(base)
    keep = np.ones(len(base), bool)
    keep[[4, 5, 17, 30]] = False  # four excluded years
    y, years = base[keep], yrs[keep]
    hr = app_stats(y, years)["advanced"]["modified_mann_kendall"]
    factor, p = ref_hamed_rao_gap_aware(years, y)
    assert hr["raw_correction_factor"] == pytest.approx(factor, rel=1e-10)
    assert factor > 1  # this series has positive autocorrelation, so the factor is applied
    assert hr["p_value"] == pytest.approx(p, rel=1e-9)
    assert hr["reliable"] is False and "missing" in hr["reliability_note"]


def test_correction_floor_and_unavailable_cases():
    neg = adv._modified_result("x", 10, 100.0, -0.2, 12, 0.05, {})
    assert neg["available"] and neg["correction_factor"] == 1.0 and neg["reduction_suppressed"]
    assert neg["var_s"] == 100.0
    bad = adv._modified_result("x", 10, 100.0, float("nan"), 12, 0.05, {})
    assert bad["available"] is False and bad["p_value"] is None and bad["unavailable_reason"]


# --------------------------------------------------------------------------- #
# Sen's slope confidence interval vs an independent Sen (1968) implementation
# --------------------------------------------------------------------------- #

def ref_sen_ci(x, y, conf=0.95):
    n = len(y)
    slopes = sorted((y[j] - y[i]) / (x[j] - x[i]) for i, j in itertools.combinations(range(n), 2) if x[j] != x[i])
    big_n = len(slopes)
    _, cy = np.unique(y, return_counts=True)
    _, cx = np.unique(x, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5) - sum(c * (c - 1) * (2 * c + 5) for c in cy) - sum(c * (c - 1) * (2 * c + 5) for c in cx)) / 18
    c_alpha = stats.norm.ppf(1 - (1 - conf) / 2) * math.sqrt(var_s)
    m1, m2 = (big_n - c_alpha) / 2, (big_n + c_alpha) / 2
    lower = slopes[int(np.round(m1)) - 1]          # M1-th smallest (1-based)
    upper = slopes[min(int(np.round(m2)), big_n - 1)]  # (M2+1)-th smallest (1-based)
    return lower, upper


@pytest.mark.parametrize("name", list(SERIES))
def test_sen_ci_matches_independent_reference(name):
    y = SERIES[name]
    x = years_for(y).astype(float)
    sen = ta.sens_slope(x, y)
    lo, hi = ref_sen_ci(list(x), list(y))
    assert sen["ci_lower"] == pytest.approx(lo, rel=1e-12, abs=1e-15)
    assert sen["ci_upper"] == pytest.approx(hi, rel=1e-12, abs=1e-15)
    assert sen["ci_lower"] <= sen["slope"] <= sen["ci_upper"]


def test_sen_ci_with_missing_years_and_ties():
    x = [2000.0, 2001, 2003, 2004, 2005, 2008, 2009, 2010, 2012, 2013, 2015, 2016]
    y = [1.0, 1.0, 1.5, 2.0, 2.0, 2.0, 3.0, 2.5, 3.0, 3.0, 4.0, 3.5]  # repeated values (ties)
    sen = ta.sens_slope(x, y)
    lo, hi = ref_sen_ci(x, y)
    assert (sen["ci_lower"], sen["ci_upper"]) == pytest.approx((lo, hi))


def test_sen_ci_is_not_the_ols_interval():
    y = SERIES["increasing"]
    x = years_for(y).astype(float)
    sen, reg = ta.sens_slope(x, y), ta.linear_regression(x, y)
    assert (sen["ci_lower"], sen["ci_upper"]) != pytest.approx((reg["ci_lower"], reg["ci_upper"]))


def test_sen_ci_coverage_is_close_to_nominal_for_independent_data():
    """Interpretation check: ~95% of intervals contain the true slope."""
    rng = np.random.default_rng(2026)
    x = np.arange(30, dtype=float)
    hits = 0
    sims = 400
    for _ in range(sims):
        y = 0.1 * x + rng.normal(0, 1, 30)
        s = ta.sens_slope(x, y)
        hits += s["ci_lower"] <= 0.1 <= s["ci_upper"]
    assert 0.92 <= hits / sims <= 0.98


# --------------------------------------------------------------------------- #
# Newey–West (HAC) regression vs statsmodels
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", ["white_noise", "positive_ar", "negative_ar", "increasing", "decreasing", "random"])
def test_hac_matches_statsmodels(name):
    y = SERIES[name]
    x = years_for(y).astype(float)
    mine = adv.ols_hac(x, y)
    fit = sm.OLS(y, sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": mine["max_lags"], "use_correction": True}, use_t=True
    )
    # statsmodels' use_correction scales by n/(n-k); verify the slope SE and p-value.
    assert mine["slope"] == pytest.approx(fit.params[1])
    assert mine["std_err"] == pytest.approx(fit.bse[1], rel=1e-8)
    assert mine["p_value"] == pytest.approx(fit.pvalues[1], rel=1e-7)


def test_hac_bandwidth_rule():
    assert [adv.newey_west_bandwidth(n) for n in (10, 25, 45, 100)] == [2, 2, 3, 4]


def test_hac_coverage_beats_ols_under_positive_autocorrelation():
    rng_seeds = range(300)
    ols_hits = hac_hits = 0
    x = np.arange(40, dtype=float)
    for seed in rng_seeds:
        y = ar1(40, 0.6, 1000 + seed, trend=0.05)
        r, h = ta.linear_regression(x, y), adv.ols_hac(x, y)
        ols_hits += r["ci_lower"] <= 0.05 <= r["ci_upper"]
        hac_hits += h["ci_lower"] <= 0.05 <= h["ci_upper"]
    assert hac_hits > ols_hits  # OLS intervals are too narrow with positive autocorrelation


# --------------------------------------------------------------------------- #
# Constant series, interpretation
# --------------------------------------------------------------------------- #

def test_constant_series_never_reaches_advanced_tests():
    from app.utils.errors import StatisticsError

    with pytest.raises(StatisticsError):
        app_stats(np.full(15, 2.5))


def _fake_stats(orig_sig: bool, adj_sig: bool, factor: float, lags: list[int]):
    return {
        "alpha": 0.05,
        "regression": {"slope": 0.03, "p_value": 0.01, "std_err": 0.01, "direction": "increasing"},
        "mann_kendall": {"significant": orig_sig, "trend": "increasing", "p_value": 0.02 if orig_sig else 0.2},
        "sens_slope": {"slope": 0.031, "ci_lower": 0.01, "ci_upper": 0.05},
        "evidence": {"category": "significant_increasing", "label": "Statistically significant increasing trend"},
        "advanced": {
            "autocorrelation": {"lag1": 0.45, "bound": 0.36, "lag1_assessment": "significant_positive",
                                "ljung_box": {"lags": 6, "p_value": 0.03, "significant": True}},
            "modified_mann_kendall": {"available": True, "correction_applied": bool(lags) and factor > 1,
                                      "significant_lags": lags, "raw_correction_factor": factor,
                                      "reduction_suppressed": factor < 1,
                                      "correction_factor": max(1.0, factor), "effective_n": 30 / max(1.0, factor), "n": 30,
                                      "p_value": 0.09 if not adj_sig else 0.03, "significant": adj_sig,
                                      "trend": "increasing", "lags_considered": 3},
            "regression_hac": {"max_lags": 2, "std_err": 0.015, "ci_lower": 0.0, "ci_upper": 0.06, "p_value": 0.06},
            "robust_evidence": {"category": "not_significant", "label": "No statistically significant trend"},
        },
    }


def test_interpretation_reports_lost_significance_after_adjustment():
    text = " ".join(build_advanced_interpretation(get_variable("T2M"), _fake_stats(True, False, 1.9, [1])))
    assert "original Mann-Kendall test identifies a statistically significant increasing trend" in text
    assert "no longer identifies statistically significant evidence of a monotonic trend" in text
    assert "factor of 1.90" in text and "+0.031 °C per year" in text
    assert "between +0.01 and +0.05" in text
    assert "do not by themselves identify the cause" in text


def test_interpretation_when_no_correction_needed():
    text = " ".join(build_advanced_interpretation(get_variable("T2M"), _fake_stats(True, True, 1.0, [])))
    assert "no variance correction was needed" in text


def test_interpretation_explains_suppressed_reduction():
    text = " ".join(build_advanced_interpretation(get_variable("T2M"), _fake_stats(True, True, 0.4, [2])))
    assert "negative rank autocorrelation at lag(s) 2" in text
    assert "never reduces the variance" in text and "0.40" in text


@pytest.mark.parametrize("name", list(SERIES))
def test_canonical_hamed_rao_fields_equal_pymannkendall_exactly(name):
    """The unmodified (canonical) method is reported alongside the conservative variant."""
    y = SERIES[name]
    hr = app_stats(y)["advanced"]["modified_mann_kendall"]
    with np.errstate(invalid="ignore"):
        ref = pmk.hamed_rao_modification_test(y, alpha=0.05, lag=3)
    assert "conservative variant" in hr["method"]
    if ref.var_s > 0:
        assert hr["canonical_var_s"] == pytest.approx(ref.var_s, rel=1e-10)
        assert hr["canonical_p_value"] == pytest.approx(ref.p, rel=1e-9, abs=1e-15)
        assert hr["canonical_significant"] == bool(ref.h)
    else:
        assert hr["canonical_p_value"] is None
