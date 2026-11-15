"""Orchestration: retrieve → parse/clean → aggregate → analyse → interpret.

The API routes call ``build_data_response`` / ``build_analysis_response``.
Each step lives in its own module so it can be tested independently.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.catalog import POWER_MONTHLY_DOCS, POWER_PARAMETER_DOCS, VariableDefinition
from app.core.config import Settings
from app.services import data_processing as dp
from app.services.interpretation import build_interpretation, fmt_p_expr, fmt_signed
from app.services.nasa_power import NasaPowerClient
from app.services.trend_analysis import run_trend_analysis
from app.utils.errors import EarthScopeError, StatisticsError
from app.utils.grid import merra2_cell
from app.utils.validators import AnalysisQuery

logger = logging.getLogger(__name__)


def _none_if_nan(v: Any) -> Any:
    try:
        return None if v is None or v != v else v  # NaN != NaN
    except TypeError:
        return v


def build_data_response(
    query: AnalysisQuery, client: NasaPowerClient, settings: Settings
) -> dict[str, Any]:
    var = query.variable
    fetched = client.fetch_monthly(
        var, query.latitude, query.longitude, query.start_year, query.end_year
    )
    payload, retrieved_at = fetched.payload, fetched.retrieved_at
    request_url, from_cache = fetched.request_url, fetched.from_cache

    parsed = dp.parse_power_response(payload, var, query.start_year, query.end_year)
    monthly_df = parsed.monthly
    annual_df = dp.aggregate_annual(monthly_df, settings.min_valid_months_per_year)
    latest_full = dp.latest_complete_year(monthly_df)
    meta = parsed.metadata
    warnings = list(parsed.warnings)

    incomplete = annual_df[annual_df["status"] != "complete"]["year"].tolist()
    if incomplete:
        shown = ", ".join(str(y) for y in incomplete[:8]) + ("…" if len(incomplete) > 8 else "")
        warnings.append(
            f"{len(incomplete)} year(s) have fewer than {settings.min_valid_months_per_year} valid "
            f"months and are excluded from the trend tests: {shown}."
        )
    if latest_full is not None and latest_full < query.end_year:
        warnings.append(
            f"The latest year with all 12 months available at this point is {latest_full}. "
            "NASA POWER publishes monthly values with a short delay, so recent months may be missing."
        )

    metadata = {
        "data_mode": "LIVE",
        "provider": "NASA POWER (Prediction Of Worldwide Energy Resources), NASA Langley Research Center",
        "dataset_title": meta.dataset_title,
        "api_version": meta.api_version,
        "variable_id": var.id,
        "variable_name": var.name,
        "parameter": var.parameter,
        "long_name": meta.long_name,
        "community": var.community,
        "sources": meta.sources,
        "units_raw": meta.units_raw,
        "unit_display": var.unit_display if (meta.units_raw in (None, var.expected_unit)) else meta.units_raw,
        "rate_unit": var.rate_unit if (meta.units_raw in (None, var.expected_unit)) else f"{meta.units_raw}/year",
        "latitude_requested": query.latitude,
        "longitude_requested": query.longitude,
        "latitude_returned": meta.latitude,
        "longitude_returned": meta.longitude,
        "elevation_m": meta.elevation_m,
        # The POWER response geometry echoes the requested point; the values come from
        # the MERRA-2 cell containing it (verified live), so report that cell explicitly.
        "grid_cell": merra2_cell(query.latitude, query.longitude),
        "spatial_resolution": var.spatial_resolution,
        "temporal_resolution": "monthly",
        "time_standard": meta.time_standard,
        "start_year": query.start_year,
        "end_year": query.end_year,
        "fill_value": meta.fill_value,
        "latest_complete_year": latest_full,
        "retrieved_at": retrieved_at,
        "served_from_cache": from_cache,
        "request_url": request_url,
        "documentation_url": POWER_MONTHLY_DOCS,
        "parameter_docs_url": POWER_PARAMETER_DOCS,
        "source_note": var.source_note,
    }

    monthly = [
        {
            "date": r.date,
            "year": int(r.year),
            "month": int(r.month),
            "value": _none_if_nan(r.value),
            "status": r.status,
        }
        for r in monthly_df.itertuples(index=False)
    ]
    annual = [
        {
            "year": int(r.year),
            "value": _none_if_nan(r.value),
            "valid_months": int(r.valid_months),
            "total_months": 12,
            "status": r.status,
            "used_in_trend": bool(r.used_in_trend),
        }
        for r in annual_df.itertuples(index=False)
    ]
    n_valid = sum(1 for m in monthly if m["status"] == "valid")
    summary = {
        "n_monthly_total": len(monthly),
        "n_monthly_valid": n_valid,
        "n_monthly_missing": len(monthly) - n_valid,
        "n_annual_total": len(annual),
        "n_annual_complete": sum(1 for a in annual if a["status"] == "complete"),
        "n_annual_used": sum(1 for a in annual if a["used_in_trend"]),
        "min_valid_months_per_year": settings.min_valid_months_per_year,
    }
    return {
        "metadata": metadata,
        "monthly": monthly,
        "annual": annual,
        "summary": summary,
        "warnings": warnings,
        "_annual_df": annual_df,  # internal, stripped before returning
    }


def build_analysis_response(
    query: AnalysisQuery, client: NasaPowerClient, settings: Settings
) -> dict[str, Any]:
    data = build_data_response(query, client, settings)
    annual_df = data.pop("_annual_df")

    statistics: dict[str, Any] | None = None
    analysis_message: str | None = None
    analysis_error: str | None = None
    try:
        statistics = run_trend_analysis(
            annual_df,
            alpha=settings.significance_alpha,
            confidence_level=settings.confidence_level,
            min_records=settings.min_annual_records,
        )
    except StatisticsError as exc:
        analysis_message = str(exc)
        analysis_error = exc.code
    except Exception:  # pragma: no cover - defensive: never leak internals
        logger.exception("Unexpected failure in trend analysis")
        analysis_message = "The statistical analysis failed unexpectedly for this dataset."
        analysis_error = "ANALYSIS_FAILED"

    n_excluded = data["summary"]["n_annual_total"] - data["summary"]["n_annual_used"]
    data["statistics"] = statistics
    data["analysis_message"] = analysis_message
    data["analysis_error"] = analysis_error
    data["interpretation"] = build_interpretation(
        query.variable,
        statistics,
        query.latitude,
        query.longitude,
        query.start_year,
        query.end_year,
        n_excluded,
        analysis_message,
    )
    return data


# --------------------------------------------------------------------------- #
# Multi-location comparison
# --------------------------------------------------------------------------- #

def build_comparison_response(
    variable: VariableDefinition,
    locations: list[tuple[float, float, str]],
    start_year: int,
    end_year: int,
    client: NasaPowerClient,
    settings: Settings,
) -> dict[str, Any]:
    """Analyse the same variable and period at up to N locations.

    Locations are fetched concurrently, at most ``compare_max_concurrency`` NASA
    requests at a time (respectful usage); the shared cache makes repeats cheap. A failure at
    one location (e.g. soil wetness over the ocean) is reported for that
    location only — the others are still analysed.
    """
    def analyse_one(point: tuple[float, float, str]) -> dict[str, Any]:
        lat, lon, label = point
        query = AnalysisQuery(variable, lat, lon, start_year, end_year)
        entry: dict[str, Any] = {"label": label, "latitude": lat, "longitude": lon}
        try:
            result = build_analysis_response(query, client, settings)
            entry.update(
                ok=True,
                error=None,
                metadata=result["metadata"],
                annual=result["annual"],
                summary=result["summary"],
                statistics=result["statistics"],
                analysis_message=result["analysis_message"],
                analysis_error=result["analysis_error"],
                warnings=result["warnings"],
            )
        except EarthScopeError as exc:
            entry.update(
                ok=False,
                error={
                    "error": exc.error,
                    "message": exc.message,
                    "details": exc.details,
                    "retryable": exc.retryable,
                    "suggested_variables": exc.suggested_variables,
                },
                metadata=None,
                annual=[],
                summary=None,
                statistics=None,
                analysis_message=None,
                analysis_error=None,
                warnings=[],
            )
        return entry

    # Fetch the locations concurrently (bounded, like the polygon tiles) instead of
    # one after another; pool.map keeps the input order.
    workers = max(1, min(len(locations), settings.compare_max_concurrency))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        entries: list[dict[str, Any]] = list(pool.map(analyse_one, locations))

    return {
        "data_mode": "LIVE",
        "variable_id": variable.id,
        "variable_name": variable.name,
        "parameter": variable.parameter,
        "unit_display": variable.unit_display,
        "rate_unit": variable.rate_unit,
        "start_year": start_year,
        "end_year": end_year,
        "alpha": settings.significance_alpha,
        "locations": entries,
        "summary": _comparison_summary(variable, entries, settings.significance_alpha),
    }


def _comparison_summary(variable: VariableDefinition, entries: list[dict[str, Any]], alpha: float) -> dict[str, Any]:
    lines: list[str] = []
    analysed = [e for e in entries if e["ok"] and e["statistics"]]
    for e in entries:
        if not e["ok"]:
            lines.append(f"{e['label']}: could not be analysed — {e['error']['message']}")
        elif not e["statistics"]:
            lines.append(f"{e['label']}: data retrieved, but trend tests could not run — {e['analysis_message']}")
        else:
            s = e["statistics"]
            reg, mk = s["regression"], s["mann_kendall"]
            lines.append(
                f"{e['label']}: {fmt_signed(reg['slope'])} {variable.rate_phrase} "
                f"(95% CI {fmt_signed(reg['ci_lower'])} to {fmt_signed(reg['ci_upper'])}; "
                f"Mann-Kendall {fmt_p_expr(mk['p_value'])}) — {s['evidence']['label'].lower()}."
            )

    if len(analysed) >= 2:
        significant = [e["label"] for e in analysed if e["statistics"]["evidence"]["category"].startswith("significant_")]
        fastest = max(analysed, key=lambda e: abs(e["statistics"]["regression"]["slope"]))
        lines.append(
            f"{len(significant)} of {len(analysed)} locations show a statistically significant trend "
            f"(both tests, α = {alpha})" + (f": {', '.join(significant)}." if significant else ".")
        )
        lines.append(
            f"The largest estimated rate of change is at {fastest['label']} "
            f"({fmt_signed(fastest['statistics']['regression']['slope'])} {variable.rate_phrase}). "
            "Differences between rates are descriptive; overlapping confidence intervals mean the "
            "rates may not differ meaningfully."
        )

    caveats = [
        "This compares rates of change (trends), not absolute levels: a place that is warmer or wetter is not necessarily changing faster.",
        "Each result describes a single NASA POWER grid cell, not the whole city, country or region.",
        "All locations use the same variable, units, period and statistical methods.",
    ]
    return {"lines": lines, "caveats": caveats}
