"""Statistical trend analysis engine.

Pure functions operating on NumPy arrays / pandas frames — no I/O, no web
framework — so they can be unit-tested against known results.

Methods
-------
* Ordinary least squares (``scipy.stats.linregress``) with a two-sided
  t-based confidence interval for the slope.
* Mann-Kendall test for a monotonic trend (``pymannkendall.original_test``,
  which includes the tie correction for the variance of S).
* Sen's slope: median of all pairwise slopes, computed with the *actual*
  year values so that gaps from excluded years are handled correctly.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy import stats

from app.utils.errors import NO_VARIATION_IN_DATA, StatisticsError

ZERO_TOL = 1e-12


def direction_of(value: float) -> str:
    if value > ZERO_TOL:
        return "increasing"
    if value < -ZERO_TOL:
        return "decreasing"
    return "no change"


def _check_inputs(x: np.ndarray, y: np.ndarray, min_n: int = 3) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise StatisticsError("Time and value arrays must be one-dimensional and the same length.")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise StatisticsError("Inputs contain missing or non-finite values; remove them before analysis.")
    if len(y) < min_n:
        raise StatisticsError(f"At least {min_n} observations are required (got {len(y)}).")
    if np.ptp(x) == 0:
        raise StatisticsError("All observations have the same time value.")
    # Treat floating-point noise (e.g. an area-weighted mean of exactly cancelling
    # cells) as constant: NASA values have 2-3 decimals, far above this tolerance.
    if np.ptp(y) <= 1e-12 * max(1.0, float(np.max(np.abs(y)))):
        raise StatisticsError(
            "All values are identical, so no trend can be estimated. A constant series is never "
            "reported as a significant increase or decrease.",
            code=NO_VARIATION_IN_DATA,
        )
    return x, y


def linear_regression(
    x: np.ndarray | list[float],
    y: np.ndarray | list[float],
    confidence_level: float = 0.95,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """OLS fit of ``y = a + b·x``.

    Returns slope ``b`` (units of y per unit of x), intercept ``a``, the
    two-sided p-value for H0: b = 0, R², the slope's standard error and a
    ``confidence_level`` confidence interval ``b ± t(1-(1-cl)/2, n-2)·SE``.
    """
    x, y = _check_inputs(np.asarray(x), np.asarray(y), min_n=3)
    n = len(x)
    res = stats.linregress(x, y)
    dof = n - 2
    t_crit = float(stats.t.ppf(1 - (1 - confidence_level) / 2, dof))
    slope = float(res.slope)
    std_err = float(res.stderr)
    r = float(res.rvalue)
    p = float(res.pvalue)
    if not math.isfinite(p):
        raise StatisticsError("Regression p-value could not be computed.")
    return {
        "slope": slope,
        "intercept": float(res.intercept),
        "p_value": p,
        "r": r,
        "r_squared": r * r,
        "std_err": std_err,
        "ci_lower": slope - t_crit * std_err,
        "ci_upper": slope + t_crit * std_err,
        "confidence_level": confidence_level,
        "n": n,
        "degrees_of_freedom": dof,
        "significant": p < alpha,
        "direction": direction_of(slope),
        "slope_per_decade": slope * 10.0,
        "trend_line": [
            {"year": int(xi), "value": float(res.intercept + slope * xi)} for xi in x
        ],
    }


TIE_REL_TOL = 1e-9


def merge_float_ties(y: np.ndarray | list[float], rel_tol: float = TIE_REL_TOL) -> np.ndarray:
    """Make values that differ only by floating-point rounding exactly equal.

    Mann-Kendall counts ties exactly (sign(0) = 0). Annual means that are
    mathematically identical can differ by ~1e-17 after floating-point
    summation (found live: two GWETTOP years whose day-weighted sums are both
    exactly 153.05/365), which would turn a tie into a ±1 in S. NASA values
    have 2–3 decimals, so real differences between annual means are ≥ ~1e-5;
    values closer than ``rel_tol × max(1, max|y|)`` are merged onto the
    smallest value of their group (compared with the group's first value, so
    groups never chain beyond the tolerance).
    """
    y = np.asarray(y, dtype=float)
    if y.size < 2:
        return y.copy()
    tol = rel_tol * max(1.0, float(np.max(np.abs(y))))
    order = np.argsort(y, kind="mergesort")
    out = y.copy()
    anchor = y[order[0]]
    for idx in order[1:]:
        if y[idx] - anchor <= tol:
            out[idx] = anchor
        else:
            anchor = y[idx]
    return out


def mann_kendall(y: np.ndarray | list[float], alpha: float = 0.05) -> dict[str, Any]:
    """Original Mann-Kendall test for a monotonic trend.

    The test only uses the *order* of the observations, so the input must be
    sorted by time. It does not assume linearity or normality. It does assume
    serially independent observations; no autocorrelation correction is
    applied here (see README limitations). Values equal up to floating-point
    rounding are treated as ties (``merge_float_ties``).
    """
    y = merge_float_ties(np.asarray(y, dtype=float))
    _check_inputs(np.arange(len(y), dtype=float), y, min_n=3)
    result = mk.original_test(y, alpha=alpha)
    p = float(result.p)
    s = float(result.s)
    return {
        "trend": direction_of(s),
        "significant": p < alpha,
        "p_value": p,
        "z": float(result.z),
        "tau": float(result.Tau),
        "s": s,
        "var_s": float(result.var_s),
        "n": int(len(y)),
    }


def mann_kendall_s(y: np.ndarray | list[float]) -> int:
    """Reference implementation of the Mann-Kendall S statistic (used in tests)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    return int(sum(np.sign(y[j] - y[i]) for i in range(n - 1) for j in range(i + 1, n)))


def sens_slope(
    x: np.ndarray | list[float], y: np.ndarray | list[float], confidence_level: float = 0.95
) -> dict[str, Any]:
    """Sen's (Theil–Sen) slope: median of (y_j − y_i)/(x_j − x_i) over all i < j.

    The confidence interval is the non-parametric interval of Sen (1968,
    eq. 2.6; Gilbert 1987 §16.5): with C = z(1−α/2)·√Var(S), the bounds are
    the ordered pairwise slopes at ranks round((N−C)/2) and round((N+C)/2)+1,
    where N is the number of pairwise slopes and Var(S) is the Mann-Kendall
    variance corrected for ties in both years and values. Computed with
    ``scipy.stats.theilslopes`` using the actual years, so missing years are
    handled. It assumes independent observations (no autocorrelation
    adjustment) and is NOT derived from the OLS interval.
    """
    x, y = _check_inputs(np.asarray(x), np.asarray(y), min_n=3)
    i, j = np.triu_indices(len(x), k=1)
    dx = x[j] - x[i]
    keep = dx != 0
    slopes = (y[j] - y[i])[keep] / dx[keep]
    slope = float(np.median(slopes))
    intercept = float(np.median(y) - slope * np.median(x))
    ts = stats.theilslopes(y, x, alpha=confidence_level)
    return {
        "slope": slope,
        "intercept": intercept,
        "slope_per_decade": slope * 10.0,
        "direction": direction_of(slope),
        "n_pairs": int(len(slopes)),
        "ci_lower": float(ts.low_slope),
        "ci_upper": float(ts.high_slope),
        "confidence_level": confidence_level,
        "ci_method": "Sen (1968) non-parametric rank interval (tie-corrected Var(S))",
    }


EVIDENCE_LABELS = {
    "significant_increasing": "Statistically significant increasing trend",
    "significant_decreasing": "Statistically significant decreasing trend",
    "not_significant": "No statistically significant trend",
    "mixed": "Mixed statistical evidence",
}


def _fmt_p(p: float) -> str:
    """'p = 0.023' or 'p < 0.001' (never 'p = < 0.001')."""
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def classify_evidence(reg: dict[str, Any], mkr: dict[str, Any], alpha: float) -> dict[str, str]:
    """Combine regression and Mann-Kendall results without hiding disagreement."""
    reg_sig, mk_sig = reg["significant"], mkr["significant"]
    reg_dir, mk_dir = reg["direction"], mkr["trend"]
    rp, mp = _fmt_p(reg["p_value"]), _fmt_p(mkr["p_value"])

    if reg_sig and mk_sig and reg_dir == mk_dir and reg_dir in ("increasing", "decreasing"):
        category = f"significant_{reg_dir}"
        explanation = (
            f"Both tests agree: the linear regression slope ({rp}) and the Mann-Kendall "
            f"test ({mp}) are each below α = {alpha}, and both indicate "
            f"{'an' if reg_dir == 'increasing' else 'a'} {reg_dir} trend."
        )
    elif not reg_sig and not mk_sig:
        category = "not_significant"
        explanation = (
            f"Neither test reaches significance at α = {alpha} (regression {rp}, "
            f"Mann-Kendall {mp}). Any visible change could plausibly be explained by "
            "natural year-to-year variability over this period."
        )
    else:
        category = "mixed"
        if reg_sig and not mk_sig:
            detail = (
                f"The linear regression slope is significant ({rp}) but the Mann-Kendall "
                f"test is not ({mp}). This can happen when a few extreme years strongly "
                "influence the straight-line fit, or when the change is not consistently monotonic."
            )
        elif mk_sig and not reg_sig:
            detail = (
                f"The Mann-Kendall test is significant ({mp}) but the linear regression slope "
                f"is not ({rp}). This can happen when values change fairly consistently in one "
                "direction but not along a straight line, or when outliers inflate the regression error."
            )
        else:
            detail = (
                f"Both tests are significant (regression {rp}, Mann-Kendall {mp}) but "
                f"point in different directions ({reg_dir} vs {mk_dir})."
            )
        explanation = f"The two tests give different conclusions. {detail} Treat this result with caution."

    return {"category": category, "label": EVIDENCE_LABELS[category], "explanation": explanation}


def run_trend_analysis(
    annual: pd.DataFrame,
    alpha: float = 0.05,
    confidence_level: float = 0.95,
    min_records: int = 10,
) -> dict[str, Any]:
    """Run all trend tests on the annual records flagged ``used_in_trend``.

    Raises ``StatisticsError`` with a user-readable message if there are too
    few usable years or the series is degenerate.
    """
    usable = annual[annual["used_in_trend"] & annual["value"].notna()].sort_values("year")
    n = len(usable)
    if n < min_records:
        raise StatisticsError(
            f"Only {n} year(s) have enough valid monthly data for trend testing; at least "
            f"{min_records} are required. Try a longer time range or a different location."
        )
    years = usable["year"].to_numpy(dtype=float)
    values = usable["value"].to_numpy(dtype=float)

    reg = linear_regression(years, values, confidence_level=confidence_level, alpha=alpha)
    mkr = mann_kendall(values, alpha=alpha)
    sen = sens_slope(years, values, confidence_level=confidence_level)
    evidence = classify_evidence(reg, mkr, alpha)

    return {
        "alpha": alpha,
        "n_years": n,
        "first_year": int(years[0]),
        "last_year": int(years[-1]),
        "regression": reg,
        "mann_kendall": mkr,
        "sens_slope": sen,
        "evidence": evidence,
        "advanced": run_advanced_analysis(years, values, reg, mkr, sen, alpha, confidence_level),
    }


def run_advanced_analysis(
    years: np.ndarray,
    values: np.ndarray,
    reg: dict[str, Any],
    mkr: dict[str, Any],
    sen: dict[str, Any],
    alpha: float,
    confidence_level: float,
) -> dict[str, Any]:
    """Autocorrelation diagnostics and autocorrelation-aware versions of the tests.

    The original results above are kept unchanged; these are additional,
    separately labelled methods.
    """
    from app.services import advanced_statistics as adv  # local import avoids a cycle

    diag = adv.autocorrelation_diagnostics(years, values, sen["slope"], alpha)
    hr = adv.hamed_rao_test(years, values, mkr["s"], mkr["var_s"], sen["slope"], alpha)
    yw = adv.yue_wang_lag1_test(years, values, mkr["s"], mkr["var_s"], sen["slope"], alpha)
    hac = adv.ols_hac(years, values, alpha, confidence_level)

    # Autocorrelation-aware evidence: combine the regression (significant only if
    # BOTH the ordinary and the HAC p-values are below alpha, i.e. the larger
    # p-value is used) with the Hamed–Rao test (variance never reduced). By
    # construction it is never MORE significant than the standard evidence.
    if hr["available"]:
        reg_p = max(reg["p_value"], hac["p_value"])
        robust = classify_evidence(
            {"significant": reg_p < alpha, "direction": reg["direction"], "p_value": reg_p},
            {"significant": hr["significant"], "trend": hr["trend"], "p_value": hr["p_value"]},
            alpha,
        )
        robust["explanation"] = (
            robust["explanation"]
            .replace("linear regression slope", "regression slope (larger of the OLS and Newey–West p-values)")
            .replace("Mann-Kendall", "Hamed–Rao modified Mann-Kendall")
        )
    else:
        robust = {
            "category": "not_significant",
            "label": "Autocorrelation-aware evidence unavailable",
            "explanation": hr["unavailable_reason"],
        }
    return {
        "autocorrelation": diag,
        "modified_mann_kendall": hr,
        "yue_wang_sensitivity": yw,
        "regression_hac": hac,
        "robust_evidence": robust,
    }
