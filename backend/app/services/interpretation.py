"""Rule-based plain-language interpretation of trend results.

Every number in the generated text comes from the computed statistics. No
language model is used, and the text never attributes a cause to a trend.
"""

from __future__ import annotations

from typing import Any

from app.core.catalog import VariableDefinition


def fmt_num(x: float, sig: int = 3) -> str:
    if x == 0:
        return "0"
    s = f"{x:.{sig}g}"
    if "e" in s:  # very small numbers: avoid scientific notation in prose
        s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s


def fmt_signed(x: float, sig: int = 3) -> str:
    s = fmt_num(x, sig)
    return f"+{s}" if x > 0 else s


def fmt_p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def fmt_p_expr(p: float) -> str:
    """'p = 0.023' or 'p < 0.001'."""
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def fmt_coord(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}°{ns}, {abs(lon):.4f}°{ew}"


COMMON_CAVEATS = [
    "This is a point-based analysis for the selected NASA POWER grid cell, not an average for a whole city, district or country.",
    "Values are model-derived (MERRA-2 reanalysis via NASA POWER), not direct ground-station measurements.",
    "A statistically significant trend shows that a change is unlikely to be due to random variability alone; it does not identify the cause of the change.",
    "Serial correlation (year-to-year persistence) can make standard significance tests over-confident. The standard regression, Mann-Kendall and Sen intervals assume independent years; the Advanced Statistical Analysis section adds autocorrelation diagnostics, a Hamed–Rao modified Mann-Kendall test and Newey–West (HAC) regression errors, which reduce but cannot fully remove this risk in short records.",
]


def build_interpretation(
    variable: VariableDefinition,
    stats: dict[str, Any] | None,
    latitude: float,
    longitude: float,
    start_year: int,
    end_year: int,
    n_excluded_years: int,
    analysis_message: str | None = None,
    *,
    location_phrase: str | None = None,
    scope_caveat: str | None = None,
) -> dict[str, Any]:
    """``location_phrase`` / ``scope_caveat`` let regional analysis describe its
    area-weighted box instead of a single grid point (defaults: point analysis)."""
    caveats = list(COMMON_CAVEATS)
    if scope_caveat:
        caveats[0] = scope_caveat
    if variable.parameter == "GWETTOP":
        caveats.insert(
            2,
            "GWETTOP is a relative wetness fraction (0 = dry, 1 = saturated) from a land-surface model, not volumetric soil water content.",
        )
    if n_excluded_years:
        caveats.append(
            f"{n_excluded_years} year(s) in the selected period had too few valid months and were excluded from the trend tests."
        )

    where = fmt_coord(latitude, longitude)
    subject = location_phrase or f"the selected NASA POWER grid point ({where})"
    
    name_lc = variable.name.lower()

    if stats is None:
        return {
            "headline": "Trend tests could not be run for this selection",
            "paragraphs": [
                analysis_message
                or "There was not enough usable data to run the statistical trend tests.",
                f"The retrieved {name_lc} records for {location_phrase or where} are still shown in the chart and table.",
            ],
            "caveats": caveats,
        }

    reg, mkr, sen, ev = stats["regression"], stats["mann_kendall"], stats["sens_slope"], stats["evidence"]
    alpha = stats["alpha"]
    unit = variable.rate_phrase
    cl = int(round(reg["confidence_level"] * 100))
    period = f"{stats['first_year']}–{stats['last_year']}"

    p1 = (
        f"Over {period}, using {stats['n_years']} annual averages with adequate monthly coverage, "
        f"the {name_lc} {'over' if location_phrase else 'at'} {subject} shows an overall "
        f"{reg['direction'] if reg['direction'] != 'no change' else 'flat'} tendency. "
        f"The fitted linear trend corresponds to a change of {fmt_signed(reg['slope'])} {unit} "
        f"({fmt_signed(reg['slope_per_decade'])} per decade), with a {cl}% confidence interval of "
        f"{fmt_signed(reg['ci_lower'])} to {fmt_signed(reg['ci_upper'])} {unit}. "
        f"The straight-line fit explains {reg['r_squared'] * 100:.1f}% of the year-to-year variation "
        f"(R² = {reg['r_squared']:.3f}); the regression slope p-value is {fmt_p(reg['p_value'])}."
    )
    if reg["ci_lower"] <= 0 <= reg["ci_upper"]:
        p1 += " Because the confidence interval includes zero, a 'no change' trend cannot be ruled out by the regression."

    mk_sig_text = "is" if mkr["significant"] else "is not"
    p2 = (
        f"The Mann-Kendall test, which checks for a consistent upward or downward (monotonic) trend "
        f"without assuming a straight line, gives S = {mkr['s']:.0f}, Kendall's τ = {mkr['tau']:.3f} "
        f"and {fmt_p_expr(mkr['p_value'])}. At the significance threshold α = {alpha}, the monotonic "
        f"trend {mk_sig_text} statistically significant. Sen's slope, a robust estimate of the rate "
        f"of change, is {fmt_signed(sen['slope'])} {unit}"
    )
    if sen.get("ci_lower") is not None and sen.get("ci_upper") is not None:
        p2 += (
            f", with a {cl}% confidence interval between {fmt_signed(sen['ci_lower'])} and "
            f"{fmt_signed(sen['ci_upper'])} {unit}"
        )
        if sen["ci_lower"] <= 0 <= sen["ci_upper"]:
            p2 += " (the interval includes zero, so no change is also consistent with the data)"
    p2 += "."

    p3 = f"Overall evidence: {ev['label']}. {ev['explanation']}"

    return {
        "headline": ev["label"],
        "paragraphs": [p1, p2, p3],
        "caveats": caveats,
        "advanced": build_advanced_interpretation(variable, stats),
    }


def build_advanced_interpretation(variable: VariableDefinition, stats: dict[str, Any]) -> list[str]:
    """Rule-based sentences for the autocorrelation-aware results. Every number
    comes from the computed statistics; no cause is ever inferred."""
    adv = stats.get("advanced")
    if not adv:
        return []
    unit = variable.rate_phrase
    alpha = stats["alpha"]
    ac, hr, hac = adv["autocorrelation"], adv["modified_mann_kendall"], adv["regression_hac"]
    mkr, reg, sen = stats["mann_kendall"], stats["regression"], stats["sens_slope"]
    out: list[str] = []

    # 1. Diagnostics
    assess = {
        "not_significant": "which is within the range expected for independent years",
        "significant_positive": "which indicates significant positive autocorrelation (consecutive years tend to resemble each other)",
        "significant_negative": "which indicates significant negative autocorrelation (consecutive years tend to alternate)",
    }[ac["lag1_assessment"]]
    lb = ac["ljung_box"]
    out.append(
        f"After removing the trend, the lag-1 autocorrelation of the annual values is r₁ = {ac['lag1']:.2f} "
        f"(95% bound for independent data ±{ac['bound']:.2f}), {assess}. The Ljung–Box test over the first "
        f"{lb['lags']} lags gives {fmt_p_expr(lb['p_value'])}"
        + (", suggesting serial dependence." if lb["significant"] else ", so it does not detect serial dependence.")
        + " These diagnostics have limited power for short records: failing to detect autocorrelation does not prove it is absent."
    )

    # 2. Original vs modified Mann-Kendall
    orig = "identifies" if mkr["significant"] else "does not identify"
    trend_word = f" {mkr['trend']}" if mkr["significant"] and mkr["trend"] != "no change" else ""
    if not hr["available"]:
        out.append(
            f"The original Mann-Kendall test {orig} a statistically significant{trend_word} trend. "
            f"The Hamed–Rao adjusted test could not be computed: {hr['unavailable_reason']}"
        )
    elif not hr["correction_applied"] and hr.get("reduction_suppressed") and hr["significant_lags"]:
        lags = ", ".join(str(lag) for lag in hr["significant_lags"])
        out.append(
            f"The original Mann-Kendall test {orig} a statistically significant{trend_word} trend "
            f"({fmt_p_expr(mkr['p_value'])}). The Hamed–Rao check found negative rank autocorrelation at "
            f"lag(s) {lags}, which would shrink the variance of S (estimated factor "
            f"{hr['raw_correction_factor']:.2f}) and make the test more significant. Because such estimates "
            "from a short annual record are unreliable, Earth Scope never reduces the variance, so the "
            "adjusted result is the same as the original."
        )
    elif not hr["correction_applied"]:
        out.append(
            f"The original Mann-Kendall test {orig} a statistically significant{trend_word} trend "
            f"({fmt_p_expr(mkr['p_value'])}). The Hamed–Rao check found no statistically significant "
            f"autocorrelation in the first {hr['lags_considered']} lags of the ranked, trend-removed series, so "
            "no variance correction was needed and the adjusted result is the same as the original."
        )
    else:
        lags = ", ".join(str(lag) for lag in hr["significant_lags"])
        base = (
            f"The original Mann-Kendall test {orig} a statistically significant{trend_word} trend "
            f"({fmt_p_expr(mkr['p_value'])}). Significant positive autocorrelation at lag(s) {lags} increases the "
            f"variance of S by a factor of {hr['correction_factor']:.2f} (effective sample size ≈ "
            f"{hr['effective_n']:.1f} instead of {hr['n']} years), giving {fmt_p_expr(hr['p_value'])} for the adjusted test. "
        )
        if mkr["significant"] and not hr["significant"]:
            base += ("After accounting for autocorrelation, the adjusted test no longer identifies statistically "
                     f"significant evidence of a monotonic trend at α = {alpha}.")
        else:
            base += f"The conclusion at α = {alpha} is unchanged."
        out.append(base)

    # 3. Sen's slope and its interval
    if sen.get("ci_lower") is not None:
        includes = sen["ci_lower"] <= 0 <= sen["ci_upper"]
        out.append(
            f"The estimated Sen's slope is {fmt_signed(sen['slope'])} {unit}, with a 95% confidence interval "
            f"between {fmt_signed(sen['ci_lower'])} and {fmt_signed(sen['ci_upper'])} {unit}"
            + (" — the interval includes zero." if includes else " — the interval excludes zero.")
            + " This non-parametric interval is based on ranks of the pairwise slopes and assumes independent years."
        )

    # 4. OLS vs HAC
    out.append(
        f"Ordinary least squares gives a slope of {fmt_signed(reg['slope'])} {unit} with {fmt_p_expr(reg['p_value'])}, "
        "assuming independent, equally variable, normally distributed residuals. With Newey–West (HAC) "
        f"standard errors ({hac['max_lags']} lag(s)), which allow for autocorrelation and unequal variance, the "
        f"same slope has a standard error of {fmt_num(hac['std_err'])} (vs {fmt_num(reg['std_err'])}), "
        f"a 95% interval of {fmt_signed(hac['ci_lower'])} to {fmt_signed(hac['ci_upper'])} and {fmt_p_expr(hac['p_value'])}. "
        "HAC errors are approximate for short records."
    )

    # 5. Combined autocorrelation-aware evidence
    rob = adv["robust_evidence"]
    ev = stats["evidence"]
    if rob["category"] == ev["category"]:
        out.append(f"Autocorrelation-aware evidence: {rob['label']} — the same conclusion as the standard tests.")
    else:
        out.append(
            f"Autocorrelation-aware evidence: {rob['label']}, whereas the standard tests indicate "
            f"“{ev['label'].lower()}”. The difference arises because the adjusted methods widen the uncertainty "
            "to reflect year-to-year dependence. The autocorrelation-aware evidence is designed to be the more "
            "cautious reading: it never reports a result as more significant than the standard tests."
        )
    out.append("Statistical trends describe how values changed; they do not by themselves identify the cause of the change.")
    return out
