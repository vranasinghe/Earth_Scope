"""Per-grid-cell trend analysis and spatial significance mapping.

Pipeline (one NASA request, reused for everything)
--------------------------------------------------
1. ``regional_analysis.load_regional_grid`` — the SAME regional request,
   parsing, fill-value, physical-range and land-only rules as the regional
   mean. No per-cell point requests are made.
2. For every cell that overlaps the box: its monthly values → annual values
   with ``data_processing.aggregate_annual`` (the point-analysis function
   itself: day-weighted, ≥ ``min_valid_months_per_year`` valid months).
3. Cells with ≥ ``min_annual_records`` usable years go through the unchanged
   ``trend_analysis.run_trend_analysis`` (OLS, Mann-Kendall, Sen + CI,
   autocorrelation, Hamed–Rao conservative + canonical, Yue–Wang, HAC).
   The Hamed–Rao lag screen uses the application's α (0.05) — NOT the map
   threshold — so changing the map threshold never changes any p-value.
4. Steps 1–3 are cached per dataset. Choosing a test, a correction or a
   threshold only re-runs ``apply_significance``: one test's p-values from the
   fixed family of testable cells are adjusted together (BH / BY / none).

The regional aggregate (trend of the area-weighted mean series) is a
different quantity and is reported separately, never replaced by an average
of cell slopes.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.services import regional_aggregation as ra
from app.services import regional_analysis as ran
from app.services.nasa_power import NasaPowerClient, TTLCache
from app.services.regional_grid import cell_bounds
from app.services.spatial_significance import CORRECTIONS, adjust_pvalues, family_size, is_valid_p
from app.services.trend_analysis import run_trend_analysis
from app.utils.errors import NO_VARIATION_IN_DATA, DataUnavailableError, InvalidRequestError, StatisticsError

logger = logging.getLogger(__name__)

# Test whose p-values define the significance map. Only methods with a real
# p-value per cell are offered; the conservative variant is separate from the
# canonical published Hamed–Rao test and labelled as Earth Scope's own rule.
METHODS: dict[str, dict[str, str]] = {
    "mann_kendall": {
        "label": "Original Mann-Kendall",
        "short": "Mann-Kendall",
        "description": "Tie-corrected Mann-Kendall test (pymannkendall.original_test). Assumes independent years.",
    },
    "hamed_rao_canonical": {
        "label": "Hamed–Rao modified Mann-Kendall (canonical, published method)",
        "short": "Hamed–Rao (canonical)",
        "description": "Hamed & Rao (1998), significant rank autocorrelation at lags 1–3; the estimated variance "
        "correction is applied as published, including reductions from negative autocorrelation.",
    },
    "hamed_rao_conservative": {
        "label": "Hamed–Rao modified Mann-Kendall — Earth Scope conservative variant",
        "short": "Hamed–Rao (conservative)",
        "description": "Earth Scope's documented variant of Hamed & Rao (1998): the variance correction is never "
        "allowed below 1, so negative autocorrelation cannot make a cell more significant. Not the canonical method.",
    },
    "yue_wang_canonical": {
        "label": "Yue–Wang modified Mann-Kendall (canonical lag-1 correction)",
        "short": "Yue–Wang",
        "description": "Yue & Wang (2004) lag-1 correction applied as published. Unavailable for a cell when the "
        "correction factor is not positive (strong negative lag-1 autocorrelation).",
    },
}
DEFAULT_METHOD = "mann_kendall"
DEFAULT_CORRECTION = "fdr_bh"
ALLOWED_ALPHAS = (0.01, 0.05, 0.10)
NEAR_ZERO_FRACTION = 0.1

_cell_cache = TTLCache(ttl_seconds=6 * 3600, max_entries=32)


def cell_id(lat: float, lon: float) -> str:
    """Stable identifier of a MERRA-2 cell from its centre, e.g. ``7.000_80.6250``."""
    return f"{lat:.3f}_{lon:.4f}"


def _f(v: Any) -> float | None:
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def validate_settings(method: str, correction: str, alpha: float) -> None:
    if method not in METHODS:
        raise InvalidRequestError(
            f"Unsupported statistical method '{method}'.", [f"Choose one of: {', '.join(METHODS)}."]
        )
    if correction not in CORRECTIONS:
        raise InvalidRequestError(
            f"Unsupported multiple-testing correction '{correction}'.", [f"Choose one of: {', '.join(CORRECTIONS)}."]
        )
    if not any(math.isclose(alpha, a) for a in ALLOWED_ALPHAS):
        raise InvalidRequestError(
            f"Unsupported significance threshold {alpha}.", ["Choose 0.01, 0.05 or 0.10."]
        )


def direction_with_near_zero(slope: float | None, span_years: float, resid_sd: float | None) -> str | None:
    """Display rule for the direction layer (not a statistical test).

    'near_zero' when the change implied over the analysed period, |slope|·span,
    is smaller than NEAR_ZERO_FRACTION (10 %) of the cell's year-to-year
    variability (SD of the OLS residuals).
    """
    if slope is None:
        return None
    if resid_sd is not None and abs(slope) * span_years < NEAR_ZERO_FRACTION * resid_sd:
        return "near_zero"
    if slope > 0:
        return "increasing"
    if slope < 0:
        return "decreasing"
    return "near_zero"


@dataclass
class CellTrendSet:
    cells: list[dict[str, Any]]
    details: dict[str, dict[str, Any]]
    years: list[int]
    metadata: dict[str, Any]
    warnings: list[str]
    complete_records: bool   # every included cell valid in every month


def compute_cell_trends(q: ran.RegionalQuery, loaded: ran.LoadedGrid, settings: Settings) -> CellTrendSet:
    grid = loaded.grid
    n_years = len(grid.years) // 12
    years_axis = [int(y) for y in grid.years.reshape(n_years, 12)[:, 0]]
    cells, details, complete = compute_cell_rows(grid, range(len(grid.lats)), settings)
    metadata = ran.regional_metadata(q, loaded, None)  # type: ignore[arg-type]
    return CellTrendSet(cells, details, years_axis, metadata, list(grid.warnings), complete)


def compute_cell_rows(grid: ra.RegionalGrid, indices: Any, settings: Settings,
                      annual_table: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
                      ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
    """Per-cell rows (statistics + availability) for the cells at ``indices``.

    Cells are independent, so computing any partition of the cells in chunks
    (background worker) gives exactly the rows of one full pass (synchronous
    endpoint). Weights use the area of ALL included cells, never just the chunk.
    """
    n_years = len(grid.years) // 12
    inc = ~grid.excluded
    included_area = float(grid.overlap_km2[inc].sum())
    min_years = settings.min_annual_records
    cells: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    complete = True
    # Annual means for all cells at once — the aggregate_annual rule, vectorised (tested to agree exactly).
    ann_years, ann_means, ann_months = annual_table if annual_table is not None else ra.cell_annual_table(grid)
    min_months = settings.min_valid_months_per_year

    for i in indices:
        lat, lon = float(grid.lats[i]), float(grid.lons[i])
        cid = cell_id(lat, lon)
        row = grid.values[i]
        la0, la1, lo0, lo1 = cell_bounds(lat, lon)
        vm = ann_months[i]
        annual_df = pd.DataFrame({
            "year": ann_years.astype(int),
            "value": [None if np.isnan(v) else float(v) for v in ann_means[i]],
            "valid_months": vm.astype(int),
            "status": np.where(vm == 0, "missing", np.where(vm >= min_months, "complete", "incomplete")),
            "used_in_trend": vm >= min_months,
        })
        n_valid_months = int(np.sum(~np.isnan(row)))
        n_valid_years = int(annual_df["used_in_trend"].sum())
        if not grid.excluded[i] and n_valid_months < row.size:
            complete = False

        base: dict[str, Any] = {
            "id": cid,
            "latitude": lat, "longitude": lon,
            "lat_min": la0, "lat_max": la1, "lon_min": lo0, "lon_max": lo1,
            "cell_area_km2": float(grid.cell_km2[i]),
            "overlap_area_km2": float(grid.overlap_km2[i]),
            "overlap_fraction": float(grid.overlap_km2[i] / grid.cell_km2[i]) if grid.cell_km2[i] > 0 else 0.0,
            "clip": grid.clips[i] if grid.clips is not None else None,
            "weight": float(grid.overlap_km2[i] / included_area) if (inc[i] and included_area > 0) else 0.0,
            "valid_months": n_valid_months,
            "total_months": int(row.size),
            "valid_years": n_valid_years,
            "total_years": n_years,
            "period_mean": _f(annual_df.loc[annual_df["used_in_trend"], "value"].astype(float).mean()) if n_valid_years else None,
        }
        stat_fields = dict.fromkeys(
            ["ols_slope", "ols_intercept", "ols_p_value", "ols_r_squared", "ols_std_err", "ols_ci_lower", "ols_ci_upper",
             "hac_p_value", "sen_slope", "sen_ci_lower", "sen_ci_upper", "mk_s", "mk_tau", "mk_z", "mk_p_value",
             "hr_canonical_p_value", "hr_conservative_p_value", "yw_canonical_p_value", "lag1_autocorrelation",
             "ljung_box_p_value", "direction_sen", "direction_ols", "first_year", "last_year"]
        )
        statistics = None

        if grid.excluded[i]:
            data_status, availability = "excluded", "excluded"
            reason = "Water or ice cell: soil wetness is constant (1.0) here and is not soil information."
        elif n_valid_months == 0:
            data_status, availability, reason = "insufficient_data", "missing", "No valid monthly values in this period."
        elif n_valid_years < min_years:
            data_status, availability = "insufficient_data", "insufficient"
            reason = (f"Only {n_valid_years} year(s) have ≥ {settings.min_valid_months_per_year} valid months; "
                      f"at least {min_years} are required for trend tests.")
        else:
            availability = "complete" if n_valid_months == row.size else "partial"
            data_status, reason = "analysed", None
            try:
                statistics = run_trend_analysis(
                    annual_df, alpha=settings.significance_alpha, confidence_level=settings.confidence_level,
                    min_records=min_years,
                )
            except StatisticsError as exc:
                if exc.code == NO_VARIATION_IN_DATA:
                    data_status, reason = "no_variation", "Every usable annual value is identical; no trend can be estimated."
                else:
                    data_status, reason = "calculation_failed", str(exc)
            except Exception:  # pragma: no cover - defensive: one bad cell must not break the map
                logger.exception("Trend calculation failed for cell %s", cid)
                data_status, reason = "calculation_failed", "The statistical calculation failed for this cell."

        if statistics is not None:
            reg, mk, sen, adv = statistics["regression"], statistics["mann_kendall"], statistics["sens_slope"], statistics["advanced"]
            hr, yw, ac, hac = adv["modified_mann_kendall"], adv["yue_wang_sensitivity"], adv["autocorrelation"], adv["regression_hac"]
            used = annual_df[annual_df["used_in_trend"]]
            yrs, vals = used["year"].to_numpy(float), used["value"].to_numpy(float)
            resid_sd = float(np.std(vals - (reg["intercept"] + reg["slope"] * yrs), ddof=2)) if len(vals) > 2 else None
            span = float(yrs[-1] - yrs[0])
            stat_fields.update({
                "ols_slope": reg["slope"], "ols_intercept": reg["intercept"], "ols_p_value": reg["p_value"],
                "ols_r_squared": reg["r_squared"], "ols_std_err": reg["std_err"],
                "ols_ci_lower": reg["ci_lower"], "ols_ci_upper": reg["ci_upper"],
                "hac_p_value": _f(hac.get("p_value")),
                "sen_slope": sen["slope"], "sen_ci_lower": _f(sen.get("ci_lower")), "sen_ci_upper": _f(sen.get("ci_upper")),
                "mk_s": mk["s"], "mk_tau": mk["tau"], "mk_z": mk["z"], "mk_p_value": mk["p_value"],
                "hr_canonical_p_value": _f(hr.get("canonical_p_value")),
                "hr_conservative_p_value": _f(hr.get("p_value")) if hr.get("available") else None,
                "yw_canonical_p_value": _f(yw.get("canonical_p_value")),
                "lag1_autocorrelation": _f(ac.get("lag1")),
                "ljung_box_p_value": _f(ac.get("ljung_box", {}).get("p_value")),
                "direction_sen": direction_with_near_zero(sen["slope"], span, resid_sd),
                "direction_ols": direction_with_near_zero(reg["slope"], span, resid_sd),
                "first_year": int(yrs[0]), "last_year": int(yrs[-1]),
            })

        cells.append({**base, **stat_fields, "data_status": data_status, "availability": availability, "reason": reason})
        details[cid] = {
            "annual": [
                {"year": int(r.year), "value": _f(r.value), "valid_months": int(r.valid_months), "used_in_trend": bool(r.used_in_trend)}
                for r in annual_df.itertuples(index=False)
            ],
            "statistics": statistics,
        }

    return cells, details, complete


def _p_for(cell: dict[str, Any], method: str) -> float | None:
    key = {
        "mann_kendall": "mk_p_value",
        "hamed_rao_canonical": "hr_canonical_p_value",
        "hamed_rao_conservative": "hr_conservative_p_value",
        "yue_wang_canonical": "yw_canonical_p_value",
    }[method]
    return cell.get(key) if cell["data_status"] == "analysed" else None


def _status(sig: bool, s: float | None) -> str:
    if not sig:
        return "not_significant"
    return "significant_increasing" if (s or 0) > 0 else "significant_decreasing"


def apply_significance(cells: list[dict[str, Any]], method: str, correction: str, alpha: float) -> tuple[list[dict[str, Any]], int]:
    """Classify every cell for one test / correction / threshold.

    The family is fixed BEFORE any significance is looked at: every analysed
    cell with a valid p-value for the chosen test. All of them are adjusted
    together (never only the increasing, decreasing or already-significant
    ones). Changing α does not change the family or the adjusted p-values.
    """
    raw = [_p_for(c, method) for c in cells]
    m = family_size(raw)
    adjusted = adjust_pvalues(raw, correction)
    out = []
    for c, p, q in zip(cells, raw, adjusted):
        in_family = is_valid_p(p)
        if in_family:
            raw_status = _status(p < alpha, c["mk_s"])                       # raw p < α (as everywhere in Earth Scope)
            adj_status = _status(q is not None and q <= alpha, c["mk_s"])     # BH/BY step-up rule: q ≤ α
            status = adj_status if correction != "none" else raw_status
            not_testable_reason = None
        else:
            if c["data_status"] == "excluded":
                status = "excluded"
            elif c["data_status"] == "insufficient_data":
                status = "insufficient_data"
            else:
                status = "not_testable"
            raw_status = adj_status = status
            not_testable_reason = (
                f"{METHODS[method]['short']} p-value is not available for this cell."
                if c["data_status"] == "analysed" else c["reason"]
            )
        out.append({
            **c,
            "raw_p_value": p if in_family else None,
            "adjusted_p_value": q if (in_family and correction != "none") else None,
            "in_family": in_family,
            "raw_status": raw_status,
            "adjusted_status": adj_status,
            "status": status,
            "status_reason": not_testable_reason,
        })
    return out, m


CATEGORIES = ("significant_increasing", "significant_decreasing", "not_significant", "insufficient_data", "not_testable", "excluded")


def spatial_summary(cells: list[dict[str, Any]], m: int, correction: str, alpha: float, complete_records: bool) -> dict[str, Any]:
    included = [c for c in cells if c["status"] != "excluded"]
    tested = [c for c in cells if c["in_family"]]
    inc_area = sum(c["overlap_area_km2"] for c in included)
    tested_area = sum(c["overlap_area_km2"] for c in tested)
    cats = {}
    for k in CATEGORIES:
        sel = [c for c in cells if c["status"] == k]
        area = sum(c["overlap_area_km2"] for c in sel)
        in_tested = k in ("significant_increasing", "significant_decreasing", "not_significant")
        cats[k] = {
            "count": len(sel),
            "area_km2": area,
            "pct_of_included_cells": (len(sel) / len(included) * 100) if included and k != "excluded" else None,
            "pct_of_included_area": (area / inc_area * 100) if inc_area > 0 and k != "excluded" else None,
            "pct_of_tested_cells": (len(sel) / len(tested) * 100) if tested and in_tested else None,
            "pct_of_tested_area": (area / tested_area * 100) if tested_area > 0 and in_tested else None,
        }
    analysed = [c for c in cells if c["data_status"] == "analysed"]
    w = np.array([c["overlap_area_km2"] for c in analysed])
    b = np.array([c["ols_slope"] for c in analysed]) if analysed else np.array([])
    signs = [c["direction_sen"] for c in analysed]
    return {
        "n_cells_total": len(cells),
        "n_cells_included": len(included),
        "n_cells_excluded": len(cells) - len(included),
        "n_cells_analysed": len(analysed),
        "n_hypotheses": m,
        "n_raw_significant": sum(1 for c in tested if c["raw_status"].startswith("significant")),
        "n_fdr_discoveries": sum(1 for c in tested if c["adjusted_status"].startswith("significant")) if correction != "none" else None,
        "included_area_km2": inc_area,
        "tested_area_km2": tested_area,
        "categories": cats,
        "n_positive_slope": signs.count("increasing"),
        "n_negative_slope": signs.count("decreasing"),
        "n_near_zero_slope": signs.count("near_zero"),
        "area_weighted_mean_ols_slope": float(np.sum(w * b) / np.sum(w)) if analysed and w.sum() > 0 else None,
        "slope_identity_exact": bool(complete_records and len(analysed) == len(included) and len(included) > 0),
        "alpha": alpha,
    }


def _regional_aggregate(q: ran.RegionalQuery, client: NasaPowerClient, settings: Settings) -> dict[str, Any] | None:
    """Trend of the area-weighted regional mean series (Phase 3 result, cached), for comparison only."""
    try:
        r = ran.build_regional_response(q, client, settings, analyze=True)  # type: ignore[arg-type]
    except DataUnavailableError:
        return None
    return regional_aggregate_from(r)


def regional_aggregate_from(r: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact regional-mean trend block from a regional analysis result."""
    if r is None:
        return None
    s = r.get("statistics")
    return {
        "annual": [{"year": a["year"], "value": a["value"], "used_in_trend": a["used_in_trend"]} for a in r["annual"]],
        "ols_slope": s["regression"]["slope"] if s else None,
        "ols_p_value": s["regression"]["p_value"] if s else None,
        "sen_slope": s["sens_slope"]["slope"] if s else None,
        "mk_p_value": s["mann_kendall"]["p_value"] if s else None,
        "evidence_label": s["evidence"]["label"] if s else None,
        "n_years": s["n_years"] if s else 0,
        "analysis_message": r.get("analysis_message"),
    }


def build_interpretation(summary: dict[str, Any], regional: dict[str, Any] | None, variable_name: str,
                         method: str, correction: str, alpha: float) -> list[str]:
    """Rule-based statements, each generated only when the computed results support it."""
    out: list[str] = []
    name = variable_name.lower()
    pos, neg = summary["n_positive_slope"], summary["n_negative_slope"]
    cats = summary["categories"]
    inc, dec = cats["significant_increasing"]["count"], cats["significant_decreasing"]["count"]
    m = summary["n_hypotheses"]
    corr = {"none": "without a multiple-testing correction", "fdr_bh": "after the Benjamini–Hochberg FDR correction",
            "fdr_by": "after the Benjamini–Yekutieli FDR correction"}[correction]
    test = METHODS[method]["short"]
    if m == 0:
        return ["No grid cell has enough valid annual data for a trend test, so no spatial significance map can be drawn."]
    if pos and neg:
        out.append(f"The region contains both positive and negative local {name} slopes ({pos} cells with a positive "
                   f"Sen's slope, {neg} with a negative one).")
    elif pos and not neg:
        out.append(f"All analysed cells with a clear slope show an increase in {name} ({pos} cells); cells may still differ in rate.")
    elif neg and not pos:
        out.append(f"All analysed cells with a clear slope show a decrease in {name} ({neg} cells); cells may still differ in rate.")
    if inc and dec:
        out.append(f"Some cells show statistically significant increases and others significant decreases ({test}, α = {alpha:g}, {corr}).")
    elif inc and inc < m:
        out.append(f"{inc} of {m} tested cells show statistically significant increases {corr} ({test}, α = {alpha:g}), while the other cells do not.")
    elif dec and dec < m:
        out.append(f"{dec} of {m} tested cells show statistically significant decreases {corr} ({test}, α = {alpha:g}), while the other cells do not.")
    elif inc == m or dec == m:
        out.append(f"Every tested cell shows a statistically significant {'increase' if inc else 'decrease'} {corr} ({test}, α = {alpha:g}).")
    else:
        out.append(f"No cell shows a statistically significant trend {corr} ({test}, α = {alpha:g}). This means the evidence is "
                   "insufficient under this test, not that the true local trends are zero.")
    if correction != "none" and summary["n_raw_significant"] > (summary["n_fdr_discoveries"] or 0):
        out.append(f"{summary['n_raw_significant']} cells have raw p < {alpha:g}, but only {summary['n_fdr_discoveries']} remain "
                   f"significant once the {m} tests are corrected together; the others could plausibly be chance findings.")
    if regional and regional.get("ols_slope") is not None:
        reg_sig = regional.get("mk_p_value") is not None and regional["mk_p_value"] < alpha
        if (pos and neg) or (reg_sig and (inc == 0 and dec == 0)) or ((inc or dec) and not reg_sig) or (reg_sig and inc and dec):
            out.append("The regional average may conceal differences between individual locations: compare the map with the "
                       "single regional trend above.")
    out.append("A statistically significant trend describes how values changed; it does not by itself identify the cause.")
    return out


def _cached_cell_set(q: ran.RegionalQuery, client: NasaPowerClient, settings: Settings) -> tuple[CellTrendSet, bool]:
    key = (q.variable.id, q.variable.community, q.bbox, q.area_key, q.start_year, q.end_year,
           settings.min_valid_months_per_year, settings.min_annual_records, settings.significance_alpha, settings.confidence_level)
    hit = _cell_cache.get(key)
    if hit is not None:
        return hit, True
    loaded = ran.load_regional_grid(q, client, settings)  # type: ignore[arg-type]
    cs = compute_cell_trends(q, loaded, settings)
    _cell_cache.set(key, cs)
    return cs, False


def _config(method: str, correction: str, alpha: float, m: int, settings: Settings) -> dict[str, Any]:
    return {
        "method": method,
        "method_label": METHODS[method]["label"],
        "method_description": METHODS[method]["description"],
        "correction": correction,
        "correction_label": CORRECTIONS[correction],
        "alpha": alpha,
        "n_hypotheses": m,
        "min_valid_months_per_year": settings.min_valid_months_per_year,
        "min_years": settings.min_annual_records,
        "screening_alpha": settings.significance_alpha,
        "confidence_level": settings.confidence_level,
        "raw_rule": "significant when raw p < α",
        "adjusted_rule": "significant when adjusted p (q) ≤ α (Benjamini–Hochberg step-up rule)",
        "direction_basis": "sign of the Mann-Kendall S statistic (shared by all offered tests)",
        "near_zero_rule": f"Direction layer only: |slope| × period length < {NEAR_ZERO_FRACTION:g} × SD of the cell's OLS residuals.",
        "methods": [{"id": k, "label": v["label"], "short": v["short"], "description": v["description"]} for k, v in METHODS.items()],
        "corrections": [{"id": k, "label": v} for k, v in CORRECTIONS.items()],
        "alphas": list(ALLOWED_ALPHAS),
    }


def build_spatial_response(q: ran.RegionalQuery, client: NasaPowerClient, settings: Settings,
                           method: str = DEFAULT_METHOD, correction: str = DEFAULT_CORRECTION, alpha: float = 0.05) -> dict[str, Any]:
    validate_settings(method, correction, alpha)
    cs, cached = _cached_cell_set(q, client, settings)
    regional = _regional_aggregate(q, client, settings)
    return spatial_response_from_set(q.variable.name, cs, regional, settings, method, correction, alpha, cached)


def spatial_response_from_set(variable_name: str, cs: CellTrendSet, regional: dict[str, Any] | None, settings: Settings,
                              method: str, correction: str, alpha: float, cached: bool = False) -> dict[str, Any]:
    """Classify the COMPLETE cell family of ``cs`` for one test / correction / α.

    Shared by the synchronous endpoint and background-job results: the family is
    always every analysed cell of the area (never a tile, a viewport or a
    pre-filtered subset), so both paths give identical adjusted p-values.
    """
    cells, m = apply_significance(cs.cells, method, correction, alpha)
    summary = spatial_summary(cells, m, correction, alpha, cs.complete_records)
    available = m > 0
    warnings = list(cs.warnings)
    n_unavailable = sum(1 for c in cells if c["data_status"] == "analysed" and not c["in_family"])
    if n_unavailable:
        warnings.append(f"{n_unavailable} analysed cell(s) have no {METHODS[method]['short']} p-value and are not part of the "
                        "correction family for this test.")
    if summary["n_cells_analysed"] and summary["n_cells_analysed"] < summary["n_cells_included"]:
        warnings.append(f"{summary['n_cells_included'] - summary['n_cells_analysed']} cell(s) could not be trend-tested "
                        "(insufficient data, no variation or calculation failure) and are shown as such on the map.")
    return {
        "metadata": {**cs.metadata, "served_from_cache": cs.metadata["served_from_cache"] or cached},
        "config": _config(method, correction, alpha, m, settings),
        "summary": summary,
        "regional_aggregate": regional,
        "cells": cells,
        "years": cs.years,
        "available": available,
        "unavailable_reason": None if available else
        "No grid cell has enough valid annual observations for a trend test. The data-availability layer shows why.",
        "interpretation": build_interpretation(summary, regional, variable_name, method, correction, alpha),
        "warnings": warnings,
    }


def build_cell_detail(q: ran.RegionalQuery, client: NasaPowerClient, settings: Settings, cid: str,
                      method: str = DEFAULT_METHOD, correction: str = DEFAULT_CORRECTION, alpha: float = 0.05) -> dict[str, Any]:
    validate_settings(method, correction, alpha)
    cs, _ = _cached_cell_set(q, client, settings)
    if cid not in cs.details:
        raise InvalidRequestError(f"Grid cell '{cid}' is not part of this region.", ["Use a cell id from /api/regional/spatial-trends."])
    cells, m = apply_significance(cs.cells, method, correction, alpha)
    cell = next(c for c in cells if c["id"] == cid)
    regional = _regional_aggregate(q, client, settings)
    return {
        "metadata": cs.metadata,
        "config": _config(method, correction, alpha, m, settings),
        "cell": cell,
        "annual": cs.details[cid]["annual"],
        "statistics": cs.details[cid]["statistics"],
        "regional_annual": regional["annual"] if regional else None,
    }
