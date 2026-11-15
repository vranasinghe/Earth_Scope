"""Autocorrelation-aware trend statistics.

All functions are pure and use the ACTUAL year of every observation, so years
excluded for incomplete data (gaps) are handled explicitly rather than being
silently treated as consecutive.

Methods
-------
* Autocorrelation function (ACF) of the trend-removed annual series.
  Residuals are ``y − b_Sen·year`` (removing the trend first, because a trend
  itself produces spurious positive autocorrelation). With complete data the
  estimator equals the standard (biased) sample ACF used by statsmodels and
  pymannkendall; with gaps only pairs exactly k calendar years apart are used.
* Lag-1 test against the large-sample white-noise bound ±z(1−α/2)/√n
  (Bartlett), and the Ljung–Box portmanteau test (Ljung & Box 1978).
* Hamed & Rao (1998) modified Mann-Kendall: Var(S) is multiplied by
  n/n* = 1 + 2/(n(n−1)(n−2)) · Σ (n−i)(n−i−1)(n−i−2)·ρ_i, where ρ_i is the
  ACF of the RANKS of the detrended series and only lags whose ρ_i lies
  outside ±z/√n are included. Earth Scope considers the first 3 lags (as
  suggested by Hamed & Rao and pymannkendall), because higher-lag estimates
  from ~10–45 annual values are very noisy. If no lag is significant the
  correction factor is exactly 1 and the result equals the original test.
  Conservative rule: the factor is floored at 1 (variance is never reduced
  on the basis of estimated negative autocorrelation); the raw estimate is
  reported as ``raw_correction_factor``. The raw factor is validated against
  ``pymannkendall.hamed_rao_modification_test(x, lag=3)``.
* Yue & Wang (2004) lag-1 correction (sensitivity check only):
  factor = 1 + 2(1 − 1/n)·ρ_1 on the detrended values, applied without a
  significance screen, with the same floor at 1. Raw factor validated against
  ``pymannkendall.yue_wang_modification_test(x, lag=1)``.
* Newey–West (1987) HAC standard error for the OLS slope: Bartlett kernel,
  bandwidth L = floor(4·(n/100)^(2/9)) (Newey & West 1994), small-sample
  factor n/(n−2), t(n−2) reference distribution. Validated against
  statsmodels OLS ``cov_type="HAC"``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

from app.services.trend_analysis import direction_of

HR_MAX_LAG = 3
# Method labels make clear that the APPLIED result is Earth Scope's conservative
# variant; the unmodified (canonical) result is reported in the canonical_* fields.
HR_METHOD = "Hamed & Rao (1998), lags 1–3 — conservative variant (variance never reduced)"
YW_METHOD = "Yue & Wang (2004), lag-1 — conservative variant (variance never reduced)"
# Below this many years the autocorrelation estimates (and therefore the
# adjusted tests) are very uncertain. This is a conservative heuristic, not a
# threshold taken from the original papers.
RELIABLE_N = 20


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _z(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def _mk_z(s: float, var_s: float) -> float:
    if var_s <= 0:
        return 0.0
    if s > 0:
        return (s - 1) / math.sqrt(var_s)
    if s < 0:
        return (s + 1) / math.sqrt(var_s)
    return 0.0


def _p_from_z(z: float) -> float:
    return float(2 * stats.norm.sf(abs(z)))


def has_gaps(years: np.ndarray) -> bool:
    years = np.asarray(years, dtype=int)
    return bool(len(years) > 1 and np.any(np.diff(years) != 1))


def acf_by_year(years: np.ndarray, values: np.ndarray, max_lag: int) -> list[float]:
    """Sample ACF where lag k pairs observations exactly k calendar years apart.

    r_k = Σ_{t, t+k both present} (v_t − v̄)(v_{t+k} − v̄) / Σ_t (v_t − v̄)²

    For a complete series this is identical to the standard biased estimator.
    """
    years = np.asarray(years, dtype=int)
    v = np.asarray(values, dtype=float)
    dev = v - v.mean()
    denom = float(np.sum(dev**2))
    lookup = {int(y): d for y, d in zip(years, dev)}
    out = [1.0]
    for k in range(1, max_lag + 1):
        num = sum(d * lookup[y + k] for y, d in lookup.items() if (y + k) in lookup)
        out.append(float(num / denom) if denom > 0 else 0.0)
    return out


def detrend_sen(years: np.ndarray, values: np.ndarray, sen_slope: float) -> np.ndarray:
    return np.asarray(values, dtype=float) - sen_slope * np.asarray(years, dtype=float)


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #

def autocorrelation_diagnostics(
    years: np.ndarray, values: np.ndarray, sen_slope: float, alpha: float = 0.05
) -> dict[str, Any]:
    years = np.asarray(years, dtype=int)
    n = len(years)
    resid = detrend_sen(years, values, sen_slope)
    max_lag = max(1, min(10, n // 3))
    acf = acf_by_year(years, resid, max_lag)
    bound = _z(alpha) / math.sqrt(n)

    # Ljung–Box over h lags (h = min(10, n/5), a common rule of thumb).
    h = max(1, min(10, n // 5))
    q = n * (n + 2) * sum(acf[k] ** 2 / (n - k) for k in range(1, h + 1))
    lb_p = float(stats.chi2.sf(q, h))

    r1 = acf[1]
    if abs(r1) <= bound:
        lag1_assessment = "not_significant"
    elif r1 > 0:
        lag1_assessment = "significant_positive"
    else:
        lag1_assessment = "significant_negative"

    gaps = has_gaps(years)
    notes = [
        "Autocorrelation is measured on the trend-removed annual values (value − Sen's slope × year), "
        "because a trend on its own creates apparent positive autocorrelation.",
        f"The ±{bound:.3f} bound is the large-sample 95% range expected for independent data (±1.96/√n); "
        "with a short record, real autocorrelation can go undetected and occasional values outside the "
        "bound can occur by chance.",
    ]
    if n < RELIABLE_N:
        notes.append(f"With only {n} years, autocorrelation estimates are very uncertain.")
    if gaps:
        notes.append("Some years are missing; lags are measured in calendar years and pairs spanning a gap are skipped.")

    return {
        "basis": "Sen-detrended annual means",
        "n": n,
        "lag1": r1,
        "lag1_assessment": lag1_assessment,
        "bound": bound,
        "acf": [
            {"lag": k, "value": acf[k], "outside_bound": abs(acf[k]) > bound} for k in range(1, max_lag + 1)
        ],
        "ljung_box": {"q": float(q), "lags": h, "p_value": lb_p, "significant": lb_p < alpha},
        "has_gaps": gaps,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# Modified Mann-Kendall tests
# --------------------------------------------------------------------------- #

def _modified_result(
    method: str,
    s: float,
    var_s: float,
    raw_factor: float,
    n: int,
    alpha: float,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Apply a variance-correction factor, never letting it fall below 1.

    Conservative rule (Earth Scope's documented choice): estimated NEGATIVE
    autocorrelation would shrink Var(S) and make the test MORE significant.
    With 10–45 annual values single-lag estimates are very noisy, and live
    NASA series produced raw factors as low as 0.07 (an "effective sample"
    of ~350 years from 25), i.e. strongly anti-conservative tests. So only
    variance increases are applied; the raw estimate is still reported.
    """
    finite = math.isfinite(raw_factor)
    factor = max(1.0, raw_factor) if finite else raw_factor
    suppressed = finite and raw_factor < 1.0
    # Canonical (published) method: the raw factor applied as-is, with no floor.
    canonical: dict[str, Any] = {"canonical_var_s": None, "canonical_z": None,
                                 "canonical_p_value": None, "canonical_significant": None}
    if finite and raw_factor > 0:
        cz = _mk_z(s, var_s * raw_factor)
        cp = _p_from_z(cz)
        canonical = {"canonical_var_s": var_s * raw_factor, "canonical_z": cz,
                     "canonical_p_value": cp, "canonical_significant": cp < alpha}
    base = {
        "method": method,
        "s": s,
        "var_s_original": var_s,
        "raw_correction_factor": raw_factor,
        "correction_factor": factor,
        "reduction_suppressed": suppressed,
        "n": n,
        **canonical,
        **extra,
    }
    if not finite:
        return {
            **base,
            "available": False,
            "var_s": None,
            "z": None,
            "p_value": None,
            "significant": None,
            "trend": None,
            "effective_n": None,
            "unavailable_reason": "The variance correction could not be estimated for this series.",
        }
    var_adj = var_s * factor
    z = _mk_z(s, var_adj)
    p = _p_from_z(z)
    return {
        **base,
        "available": True,
        "var_s": var_adj,
        "z": z,
        "p_value": p,
        "significant": p < alpha,
        "trend": direction_of(s),
        "effective_n": n / factor,
        "unavailable_reason": None,
    }


def hamed_rao_test(
    years: np.ndarray,
    values: np.ndarray,
    s: float,
    var_s: float,
    sen_slope: float,
    alpha: float = 0.05,
    max_lag: int = HR_MAX_LAG,
) -> dict[str, Any]:
    """Hamed & Rao (1998) variance-corrected Mann-Kendall test (see module doc)."""
    years = np.asarray(years, dtype=int)
    n = len(years)
    lag_n = max(1, min(max_lag, n - 3))
    ranks = stats.rankdata(detrend_sen(years, values, sen_slope))
    rho = acf_by_year(years, ranks, lag_n)
    bound = _z(alpha) / math.sqrt(n)
    included = [i for i in range(1, lag_n + 1) if abs(rho[i]) > bound]
    sni = sum((n - i) * (n - i - 1) * (n - i - 2) * rho[i] for i in included)
    factor = 1 + 2 / (n * (n - 1) * (n - 2)) * sni
    reliable = n >= RELIABLE_N and not has_gaps(years)
    note = None
    if n < RELIABLE_N:
        note = f"Only {n} years: autocorrelation estimates are uncertain, so treat the adjusted result with caution."
    elif has_gaps(years):
        note = "Some years are missing; the correction treats lags in calendar years, an approximation of the original method."
    return _modified_result(
        HR_METHOD,
        s,
        var_s,
        factor,
        n,
        alpha,
        {
            "lags_considered": lag_n,
            "rank_acf": [{"lag": i, "value": rho[i], "outside_bound": abs(rho[i]) > bound} for i in range(1, lag_n + 1)],
            "significant_lags": included,
            "correction_applied": bool(included) and factor > 1.0,
            "reliable": reliable,
            "reliability_note": note,
        },
    )


def yue_wang_lag1_test(
    years: np.ndarray,
    values: np.ndarray,
    s: float,
    var_s: float,
    sen_slope: float,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Yue & Wang (2004) lag-1 correction — reported as a sensitivity check only."""
    years = np.asarray(years, dtype=int)
    n = len(years)
    rho1 = acf_by_year(years, detrend_sen(years, values, sen_slope), 1)[1]
    factor = 1 + 2 * (1 - 1 / n) * rho1
    return _modified_result(
        YW_METHOD,
        s,
        var_s,
        factor,
        n,
        alpha,
        {
            "lags_considered": 1,
            "rank_acf": [],
            "significant_lags": [],
            "correction_applied": factor > 1.0,
            "reliable": n >= RELIABLE_N and not has_gaps(years),
            "reliability_note": "Sensitivity check: applies the lag-1 correction whether or not the "
            "autocorrelation is statistically significant.",
        },
    )


# --------------------------------------------------------------------------- #
# Newey–West (HAC) standard error for the OLS slope
# --------------------------------------------------------------------------- #

def newey_west_bandwidth(n: int) -> int:
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def ols_hac(
    years: np.ndarray,
    values: np.ndarray,
    alpha: float = 0.05,
    confidence_level: float = 0.95,
    max_lags: int | None = None,
) -> dict[str, Any]:
    years = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    n = len(y)
    lags = newey_west_bandwidth(n) if max_lags is None else max_lags
    X = np.column_stack([np.ones(n), years])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    e = y - X @ beta

    meat = (X * e[:, None]).T @ (X * e[:, None])
    index_of = {int(round(t)): i for i, t in enumerate(years)}
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        gamma = np.zeros((2, 2))
        for t_year, i in index_of.items():
            j = index_of.get(t_year - lag)
            if j is not None:  # only pairs exactly `lag` years apart
                gamma += e[i] * e[j] * np.outer(X[i], X[j])
        meat += w * (gamma + gamma.T)

    cov = xtx_inv @ meat @ xtx_inv * (n / (n - 2))
    se = float(math.sqrt(cov[1, 1]))
    slope = float(beta[1])
    dof = n - 2
    t_stat = slope / se if se > 0 else math.inf
    p = float(2 * stats.t.sf(abs(t_stat), dof))
    t_crit = float(stats.t.ppf(1 - (1 - confidence_level) / 2, dof))
    return {
        "method": "Newey–West (HAC) standard error",
        "slope": slope,
        "std_err": se,
        "t_statistic": float(t_stat),
        "p_value": p,
        "ci_lower": slope - t_crit * se,
        "ci_upper": slope + t_crit * se,
        "confidence_level": confidence_level,
        "max_lags": lags,
        "kernel": "Bartlett",
        "significant": p < alpha,
        "degrees_of_freedom": dof,
    }
