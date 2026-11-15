"""Tests for the statistical engine against known, hand-checkable results.

Synthetic series (increasing, decreasing, no trend, missing values,
insufficient observations) are used ONLY for testing.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pymannkendall as pmk
import pytest
from scipy import stats

from app.services import trend_analysis as ta
from app.services.interpretation import build_interpretation
from app.utils.errors import StatisticsError

YEARS = np.arange(2001, 2021, dtype=float)  # 20 years


def noisy(slope: float, seed: int = 0, sd: float = 0.3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 25 + slope * (YEARS - YEARS[0]) + rng.normal(0, sd, len(YEARS))


# --- Linear regression -------------------------------------------------------------

def test_regression_exact_line():
    y = 3.0 + 0.5 * YEARS
    r = ta.linear_regression(YEARS, y)
    assert r["slope"] == pytest.approx(0.5)
    assert r["intercept"] == pytest.approx(3.0)
    assert r["r_squared"] == pytest.approx(1.0)
    assert r["p_value"] < 1e-10
    assert r["direction"] == "increasing"
    assert r["slope_per_decade"] == pytest.approx(5.0)
    assert r["trend_line"][0] == {"year": 2001, "value": pytest.approx(3.0 + 0.5 * 2001)}


def test_regression_matches_closed_form_and_confidence_interval():
    y = noisy(0.03, seed=1)
    r = ta.linear_regression(YEARS, y, confidence_level=0.95)
    n = len(YEARS)
    xb, yb = YEARS.mean(), y.mean()
    sxx = np.sum((YEARS - xb) ** 2)
    b = np.sum((YEARS - xb) * (y - yb)) / sxx
    a = yb - b * xb
    resid = y - (a + b * YEARS)
    se = math.sqrt(np.sum(resid**2) / (n - 2) / sxx)
    t = stats.t.ppf(0.975, n - 2)
    r2 = 1 - np.sum(resid**2) / np.sum((y - yb) ** 2)
    p = 2 * stats.t.sf(abs(b / se), n - 2)
    assert r["slope"] == pytest.approx(b)
    assert r["intercept"] == pytest.approx(a)
    assert r["std_err"] == pytest.approx(se)
    assert r["ci_lower"] == pytest.approx(b - t * se)
    assert r["ci_upper"] == pytest.approx(b + t * se)
    assert r["r_squared"] == pytest.approx(r2)
    assert r["p_value"] == pytest.approx(p)
    assert r["degrees_of_freedom"] == n - 2
    assert r["ci_lower"] < r["slope"] < r["ci_upper"]


def test_regression_known_decreasing_trend_is_significant():
    r = ta.linear_regression(YEARS, noisy(-0.08, seed=2))
    assert r["direction"] == "decreasing"
    assert r["significant"] is True
    assert r["ci_upper"] < 0


def test_regression_no_trend_is_not_significant():
    y = np.array([5.0, 7.0] * 10)  # alternating, zero slope component
    r = ta.linear_regression(YEARS, y)
    assert abs(r["slope"]) < 0.05
    assert r["significant"] is False
    assert r["ci_lower"] < 0 < r["ci_upper"]


# --- Mann-Kendall ---------------------------------------------------------------------

def test_mann_kendall_perfectly_increasing_hand_computed():
    # n=5: S=10, Var(S)=n(n-1)(2n+5)/18=16.667, Z=(S-1)/sqrt(Var)=2.2045, p=0.0275
    r = ta.mann_kendall([1, 2, 3, 4, 5])
    assert r["s"] == 10
    assert r["var_s"] == pytest.approx(5 * 4 * 15 / 18)
    assert r["z"] == pytest.approx(9 / math.sqrt(5 * 4 * 15 / 18))
    assert r["p_value"] == pytest.approx(2 * stats.norm.sf(9 / math.sqrt(5 * 4 * 15 / 18)))
    assert r["tau"] == pytest.approx(1.0)
    assert r["trend"] == "increasing"
    assert r["significant"] is True


def test_mann_kendall_s_matches_reference_and_tau():
    y = noisy(0.02, seed=3, sd=0.5)
    r = ta.mann_kendall(y)
    s_ref = ta.mann_kendall_s(y)
    n = len(y)
    assert r["s"] == s_ref
    assert r["tau"] == pytest.approx(s_ref / (n * (n - 1) / 2))


def test_mann_kendall_decreasing_and_no_trend():
    dec = ta.mann_kendall(noisy(-0.1, seed=4))
    assert dec["trend"] == "decreasing" and dec["significant"]
    flat = ta.mann_kendall([5.0, 7.0] * 10)
    assert flat["significant"] is False


def test_mann_kendall_handles_ties():
    r = ta.mann_kendall([1, 1, 2, 2, 3, 3, 4, 4])
    assert r["var_s"] < 8 * 7 * 21 / 18  # tie correction reduces the variance
    assert r["trend"] == "increasing"


# --- Sen's slope -------------------------------------------------------------------------

def test_sens_slope_hand_computed():
    # pairwise slopes: 2, 0.5, 4/3, -1, 1, 3 -> median = (1 + 4/3)/2
    r = ta.sens_slope([1, 2, 3, 4], [1, 3, 2, 5])
    assert r["slope"] == pytest.approx((1 + 4 / 3) / 2)
    assert r["n_pairs"] == 6


def test_sens_slope_matches_pymannkendall_for_regular_spacing():
    y = noisy(0.04, seed=5)
    assert ta.sens_slope(YEARS, y)["slope"] == pytest.approx(pmk.sens_slope(y).slope)


def test_sens_slope_uses_real_years_when_there_are_gaps():
    years = np.array([2001, 2002, 2005, 2006, 2010], dtype=float)
    y = 2.0 * years  # exact slope 2 per year
    assert ta.sens_slope(years, y)["slope"] == pytest.approx(2.0)


def test_sens_slope_is_robust_to_an_outlier():
    y = 1.0 + 0.1 * YEARS
    y_out = y.copy()
    y_out[-1] += 100
    assert ta.sens_slope(YEARS, y_out)["slope"] == pytest.approx(0.1, rel=1e-6)
    assert ta.linear_regression(YEARS, y_out)["slope"] > 1  # OLS is pulled by the outlier


# --- Degenerate / invalid input --------------------------------------------------------------

@pytest.mark.parametrize(
    "x,y",
    [
        ([2001, 2002], [1.0, 2.0]),                 # too few
        ([2001, 2002, 2003], [1.0, np.nan, 2.0]),   # missing value
        ([2001, 2002, 2003], [4.0, 4.0, 4.0]),      # constant
        ([2001, 2002, 2003], [1.0, 2.0]),           # length mismatch
    ],
)
def test_invalid_inputs_raise(x, y):
    with pytest.raises(StatisticsError):
        ta.linear_regression(x, y)


def _annual(values, used=None):
    years = list(range(2001, 2001 + len(values)))
    used = used if used is not None else [v is not None for v in values]
    return pd.DataFrame({
        "year": years,
        "value": values,
        "valid_months": [12 if u else 5 for u in used],
        "status": ["complete" if u else "incomplete" for u in used],
        "used_in_trend": used,
    })


def test_run_trend_analysis_excludes_unusable_years():
    vals = list(25 + 0.05 * np.arange(15))
    used = [True] * 15
    vals[3], used[3] = 99.0, False  # incomplete year with a wild value must be ignored
    vals[7] = None
    used[7] = False
    res = ta.run_trend_analysis(_annual(vals, used), min_records=8)
    assert res["n_years"] == 13
    assert res["regression"]["slope"] == pytest.approx(0.05)
    assert res["sens_slope"]["slope"] == pytest.approx(0.05)


def test_run_trend_analysis_insufficient_records():
    with pytest.raises(StatisticsError, match="at least 8"):
        ta.run_trend_analysis(_annual([1.0, 2.0, 3.0, 4.0, 5.0]), min_records=8)


# --- Evidence classification ---------------------------------------------------------------------

def _r(sig, d, p):
    return {"significant": sig, "direction": d, "p_value": p}


def _m(sig, d, p):
    return {"significant": sig, "trend": d, "p_value": p}


@pytest.mark.parametrize(
    "reg,mk,expected",
    [
        (_r(True, "increasing", 0.01), _m(True, "increasing", 0.02), "significant_increasing"),
        (_r(True, "decreasing", 0.01), _m(True, "decreasing", 0.02), "significant_decreasing"),
        (_r(False, "increasing", 0.3), _m(False, "increasing", 0.4), "not_significant"),
        (_r(True, "increasing", 0.01), _m(False, "increasing", 0.07), "mixed"),
        (_r(False, "decreasing", 0.09), _m(True, "decreasing", 0.03), "mixed"),
    ],
)
def test_classify_evidence(reg, mk, expected):
    ev = ta.classify_evidence(reg, mk, 0.05)
    assert ev["category"] == expected
    if expected == "mixed":
        assert "different conclusions" in ev["explanation"]


def test_interpretation_uses_computed_numbers(t2m):
    vals = list(noisy(0.05, seed=6))
    stats_ = ta.run_trend_analysis(_annual(vals), min_records=8)
    text = build_interpretation(t2m, stats_, 6.9271, 79.8612, 2001, 2020, 0)
    joined = " ".join(text["paragraphs"])
    assert f"{stats_['mann_kendall']['tau']:.3f}" in joined
    assert "°C per year" in joined
    assert any("does not identify the cause" in c for c in text["caveats"])


# --- Floating-point ties (found in live NASA GWETTOP data) -----------------------------

def test_mann_kendall_treats_floating_point_noise_as_a_tie():
    """Two real GWETTOP years (cell -3.0, 38.75) whose day-weighted sums are both exactly 153.05/365.

    numpy's summation leaves a 5.6e-17 difference; the test must still count the pair as a tie.
    """
    import calendar

    from app.services.data_processing import aggregate_annual

    y2001 = [0.54, 0.36, 0.39, 0.51, 0.43, 0.42, 0.36, 0.3, 0.27, 0.27, 0.6, 0.58]
    y2009 = [0.33, 0.36, 0.34, 0.54, 0.45, 0.46, 0.34, 0.3, 0.26, 0.51, 0.54, 0.6]
    for year, vals in ((2001, y2001), (2009, y2009)):
        assert sum(v * calendar.monthrange(year, m + 1)[1] for m, v in enumerate(vals)) == pytest.approx(153.05, abs=1e-12)
    monthly = pd.DataFrame(
        [{"year": y, "month": m + 1, "value": v, "status": "valid"} for y, vals in ((2001, y2001), (2009, y2009)) for m, v in enumerate(vals)]
    )
    a, b = aggregate_annual(monthly)["value"].tolist()
    series = [a, 0.40, b, 0.45, 0.38]       # a and b are mathematically equal
    exact = [153.05 / 365, 0.40, 153.05 / 365, 0.45, 0.38]
    assert ta.mann_kendall(series)["s"] == ta.mann_kendall_s(ta.merge_float_ties(exact))
    assert ta.mann_kendall(series)["var_s"] == pytest.approx(ta.mann_kendall(exact)["var_s"])


def test_merge_float_ties_never_merges_real_differences():
    y = np.array([0.41, 0.41 + 1e-5, 0.41 + 2e-5, 25.0, 25.0 + 0.5e-9 * 25])   # tolerance here is 1e-9 × 25
    out = ta.merge_float_ties(y)
    assert len(set(out[:3])) == 3                     # NASA-scale differences stay distinct
    assert out[3] == out[4] == 25.0                    # rounding-level difference merges
    assert ta.merge_float_ties([1.0, 1.0 + 6e-10, 1.0 + 1.2e-9]).tolist() == [1.0, 1.0, 1.0 + 1.2e-9]  # no chaining
