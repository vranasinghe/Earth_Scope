"""Independent validation of the statistical engine.

Every expected value here is computed from first principles with plain
Python / NumPy — deliberately NOT with ``scipy.stats.linregress`` or
``pymannkendall`` (which the application uses) — so the application's results
are checked against a separate implementation of the textbook formulas:

* OLS: closed-form slope/intercept, residual SE, t-test via the regularised
  incomplete beta function, CI with a bisection-solved t critical value.
* Mann-Kendall: brute-force S, tie-corrected Var(S), continuity-corrected Z,
  two-sided normal p-value via math.erfc.
* Sen's slope: median of all pairwise slopes (statistics.median).
* Annual means: calendar day weights.

Synthetic datasets (test-only): A perfect increase, B perfect decrease,
C constant, D noisy increase, E noisy decrease, F random/no trend,
G series with missing values.
"""

from __future__ import annotations

import calendar
import itertools
import math
import statistics

import numpy as np
import pandas as pd
import pytest
from scipy.special import betainc  # only the special function, not the regression routine

from app.services import data_processing as dp
from app.services import trend_analysis as ta
from app.utils.errors import NO_VARIATION_IN_DATA, StatisticsError

YEARS = list(range(1996, 2026))  # 30 years
RNG = np.random.default_rng(20261114)


# --------------------------------------------------------------------------- #
# Independent reference implementations
# --------------------------------------------------------------------------- #

def t_two_sided_p(t: float, df: int) -> float:
    if not math.isfinite(t):
        return 0.0
    return float(betainc(df / 2, 0.5, df / (df + t * t)))


def t_critical(conf: float, df: int) -> float:
    target = 1 - conf  # two-sided tail probability
    lo, hi = 0.0, 100.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_two_sided_p(mid, df) > target else (lo, mid)
    return (lo + hi) / 2


def ref_ols(x: list[float], y: list[float]) -> dict:
    n = len(x)
    xb, yb = sum(x) / n, sum(y) / n
    sxx = sum((xi - xb) ** 2 for xi in x)
    sxy = sum((xi - xb) * (yi - yb) for xi, yi in zip(x, y))
    b = sxy / sxx
    a = yb - b * xb
    sse = sum((yi - (a + b * xi)) ** 2 for xi, yi in zip(x, y))
    sst = sum((yi - yb) ** 2 for yi in y)
    se = math.sqrt(sse / (n - 2) / sxx)
    t = b / se if se > 0 else math.inf
    tc = t_critical(0.95, n - 2)
    return {"slope": b, "intercept": a, "std_err": se, "p_value": t_two_sided_p(t, n - 2),
            "r_squared": 1 - sse / sst, "ci_lower": b - tc * se, "ci_upper": b + tc * se}


def ref_mann_kendall(y: list[float]) -> dict:
    n = len(y)
    s = sum((y[j] > y[i]) - (y[j] < y[i]) for i, j in itertools.combinations(range(n), 2))
    ties = [c for c in (y.count(v) for v in set(y)) if c > 1]
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var) if s < 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"s": s, "var_s": var, "z": z, "p_value": p, "tau": s / (n * (n - 1) / 2)}


def ref_sen(x: list[float], y: list[float]) -> float:
    return statistics.median((y[j] - y[i]) / (x[j] - x[i]) for i, j in itertools.combinations(range(len(x)), 2) if x[j] != x[i])


# --------------------------------------------------------------------------- #
# Synthetic datasets
# --------------------------------------------------------------------------- #

def ds(kind: str) -> tuple[list[float], list[float]]:
    x = [float(v) for v in YEARS]
    t = np.arange(len(x))
    if kind == "A":
        y = 10 + 0.05 * t
    elif kind == "B":
        y = 80 - 0.2 * t
    elif kind == "C":
        y = np.full(len(x), 0.42)
    elif kind == "D":
        y = 25 + 0.03 * t + RNG.normal(0, 0.15, len(x))
    elif kind == "E":
        y = 0.7 - 0.004 * t + RNG.normal(0, 0.01, len(x))
    elif kind == "F":
        y = 15 + np.random.default_rng(7).normal(0, 1.0, len(x))
    else:
        raise ValueError(kind)
    return x, [float(v) for v in y]


@pytest.mark.parametrize("kind", ["A", "B", "D", "E", "F"])
def test_regression_matches_independent_ols(kind):
    x, y = ds(kind)
    app = ta.linear_regression(x, y)
    ref = ref_ols(x, y)
    for k in ("slope", "intercept", "std_err", "r_squared", "ci_lower", "ci_upper"):
        assert app[k] == pytest.approx(ref[k], rel=1e-7, abs=1e-12), k
    assert app["p_value"] == pytest.approx(ref["p_value"], rel=1e-6, abs=1e-15)


@pytest.mark.parametrize("kind", ["A", "B", "D", "E", "F"])
def test_mann_kendall_matches_independent_implementation(kind):
    _, y = ds(kind)
    app = ta.mann_kendall(y)
    ref = ref_mann_kendall(y)
    assert app["s"] == ref["s"]
    assert app["var_s"] == pytest.approx(ref["var_s"])
    assert app["z"] == pytest.approx(ref["z"])
    assert app["p_value"] == pytest.approx(ref["p_value"], rel=1e-9, abs=1e-15)
    assert app["tau"] == pytest.approx(ref["tau"])


@pytest.mark.parametrize("kind", ["A", "B", "D", "E", "F"])
def test_sens_slope_matches_brute_force_median(kind):
    x, y = ds(kind)
    assert ta.sens_slope(x, y)["slope"] == pytest.approx(ref_sen(x, y), rel=1e-12)


def test_A_perfect_increase_exact_values():
    x, y = ds("A")
    reg, mk, sen = ta.linear_regression(x, y), ta.mann_kendall(y), ta.sens_slope(x, y)
    assert reg["slope"] == pytest.approx(0.05) and sen["slope"] == pytest.approx(0.05)
    assert reg["r_squared"] == pytest.approx(1.0)
    n = len(y)
    assert mk["s"] == n * (n - 1) / 2 and mk["tau"] == pytest.approx(1.0)
    assert reg["significant"] and mk["significant"]
    assert ta.classify_evidence(reg, mk, 0.05)["category"] == "significant_increasing"


def test_B_perfect_decrease_exact_values():
    x, y = ds("B")
    reg, mk, sen = ta.linear_regression(x, y), ta.mann_kendall(y), ta.sens_slope(x, y)
    assert reg["slope"] == pytest.approx(-0.2) and sen["slope"] == pytest.approx(-0.2)
    assert mk["tau"] == pytest.approx(-1.0)
    assert ta.classify_evidence(reg, mk, 0.05)["category"] == "significant_decreasing"


def test_C_constant_series_is_never_a_significant_trend():
    x, y = ds("C")
    for fn in (lambda: ta.linear_regression(x, y), lambda: ta.mann_kendall(y), lambda: ta.sens_slope(x, y)):
        with pytest.raises(StatisticsError) as info:
            fn()
        assert info.value.code == NO_VARIATION_IN_DATA
    annual = pd.DataFrame({"year": YEARS, "value": y, "valid_months": 12, "status": "complete", "used_in_trend": True})
    with pytest.raises(StatisticsError) as info:
        ta.run_trend_analysis(annual)
    assert info.value.code == NO_VARIATION_IN_DATA


def test_D_E_noisy_trends_detected_in_correct_direction():
    xd, yd = ds("D")
    xe, ye = ds("E")
    rd, re_ = ta.run_trend_analysis(_annual(xd, yd)), ta.run_trend_analysis(_annual(xe, ye))
    assert rd["evidence"]["category"] == "significant_increasing"
    assert re_["evidence"]["category"] == "significant_decreasing"
    # The true slope lies inside the 95% CI.
    assert rd["regression"]["ci_lower"] < 0.03 < rd["regression"]["ci_upper"]
    assert re_["regression"]["ci_lower"] < -0.004 < re_["regression"]["ci_upper"]


def test_F_random_series_has_no_significant_trend():
    x, y = ds("F")
    r = ta.run_trend_analysis(_annual(x, y))
    assert r["evidence"]["category"] == "not_significant"
    assert r["regression"]["ci_lower"] < 0 < r["regression"]["ci_upper"]


def test_G_missing_values_monthly_to_annual_and_trend():
    """Monthly series with gaps: day-weighted annual means, incomplete years excluded."""
    rows = []
    for y in YEARS:
        for m in range(1, 13):
            v = 20 + 0.04 * (y - YEARS[0]) + 2 * math.sin(2 * math.pi * m / 12)
            missing = (y == 2000 and m <= 4) or (y == 2010 and m in (6, 7)) or (y == 2020)
            rows.append({"date": f"{y}-{m:02d}", "year": y, "month": m,
                         "value": None if missing else v, "status": "missing" if missing else "valid"})
    monthly = pd.DataFrame(rows)
    annual = dp.aggregate_annual(monthly, min_valid_months=10).set_index("year")

    # Independent day-weighted mean for a complete year and for 2010 (10 valid months).
    for year in (1996, 2010):
        vals = [(r["value"], calendar.monthrange(year, r["month"])[1]) for r in rows if r["year"] == year and r["value"] is not None]
        expected = sum(v * d for v, d in vals) / sum(d for _, d in vals)
        assert annual.loc[year, "value"] == pytest.approx(expected)
    assert annual.loc[2010, "valid_months"] == 10 and annual.loc[2010, "used_in_trend"]
    assert annual.loc[2000, "valid_months"] == 8 and not annual.loc[2000, "used_in_trend"]
    assert annual.loc[2020, "status"] == "missing" and pd.isna(annual.loc[2020, "value"])
    assert not (monthly["value"] == 0).any()

    result = ta.run_trend_analysis(annual.reset_index())
    assert result["n_years"] == len(YEARS) - 2
    used = annual[annual["used_in_trend"]]
    ref = ref_ols([float(v) for v in used.index], used["value"].tolist())
    assert result["regression"]["slope"] == pytest.approx(ref["slope"], rel=1e-9)
    assert result["sens_slope"]["slope"] == pytest.approx(ref_sen([float(v) for v in used.index], used["value"].tolist()))


def test_mann_kendall_tie_correction_against_reference():
    y = [1, 2, 2, 3, 3, 3, 4, 5, 5, 6, 7, 7]
    app, ref = ta.mann_kendall(y), ref_mann_kendall([float(v) for v in y])
    assert app["var_s"] == pytest.approx(ref["var_s"])
    assert app["var_s"] < len(y) * (len(y) - 1) * (2 * len(y) + 5) / 18
    assert app["p_value"] == pytest.approx(ref["p_value"])


def test_rates_are_per_year_even_with_year_gaps():
    x = [2000.0, 2001.0, 2004.0, 2005.0, 2010.0, 2011.0, 2015.0, 2016.0, 2018.0, 2020.0]
    y = [3 + 0.25 * (v - 2000) for v in x]
    assert ta.linear_regression(x, y)["slope"] == pytest.approx(0.25)
    assert ta.sens_slope(x, y)["slope"] == pytest.approx(0.25)


def test_minimum_records_for_normal_approximation():
    x, y = ds("D")
    with pytest.raises(StatisticsError, match="at least 10"):
        ta.run_trend_analysis(_annual(x[:9], y[:9]))
    assert ta.run_trend_analysis(_annual(x[:10], y[:10]))["n_years"] == 10


def test_ci_and_significance_are_consistent():
    """For OLS, p < 0.05 exactly when the 95% CI excludes zero."""
    for seed in range(40):
        y = list(15 + 0.01 * np.arange(20) + np.random.default_rng(seed).normal(0, 0.3, 20))
        r = ta.linear_regression(list(range(2000, 2020)), y)
        excludes_zero = r["ci_lower"] > 0 or r["ci_upper"] < 0
        assert excludes_zero == r["significant"], seed


def _annual(x, y):
    return pd.DataFrame({"year": [int(v) for v in x], "value": y, "valid_months": 12,
                         "status": "complete", "used_in_trend": True})
