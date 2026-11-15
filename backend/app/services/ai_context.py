"""Trusted, compact analysis context for the AI assistant.

The context is built from Earth Scope's OWN results:

* synchronous analyses (point, compare, rectangle, country, polygon, spatial) are recomputed
  from the analysis reference with the same service functions the result pages use. Those
  functions are cached (NASA responses, regional and spatial results), so this normally costs
  no extra NASA request — and a browser cannot inject numbers, only parameters;
* background jobs are loaded from their published artifacts after the same session-ownership
  check as /api/analysis/jobs/{id} (another session's job id behaves like a missing job);
* job lists / statuses come from the job database for the caller's session only.

Only aggregate statistics are included (never thousands of grid-cell records), floats are
rounded, user-typed strings (place / polygon labels) are sanitised and the whole object is
size-bounded before it is sent to the model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError

from app.ai.errors import CONTEXT_MESSAGE, AiContextUnavailableError
from app.core.config import Settings
from app.models.ai_schemas import (
    CompareReference,
    JobReference,
    LearnReference,
    PointReference,
    RegionalReference,
)
from app.services.nasa_power import NasaPowerClient
from app.utils.errors import EarthScopeError, InvalidRequestError

logger = logging.getLogger("earthscope.ai")

PAGE_DESCRIPTIONS = {
    "home": "Earth Scope home page: overview of the platform (point, regional, country, polygon, spatial-trend and comparison analyses of NASA POWER monthly data). No analysis is shown.",
    "explore": "Explore page: the user is choosing a variable, a location and a period for a single-point analysis. No results yet.",
    "compare_setup": "Compare page (setup): the user is choosing 2–3 locations to compare. No results yet.",
    "regional_setup": "Regional Analysis page (setup): the user is choosing a rectangle, country or custom polygon. No results yet.",
    "jobs": "Analysis Jobs page: background (large-area) analyses submitted from this browser session.",
    "learn": "Learn page: plain-language explanations of time series, trends, regression, Mann-Kendall, Sen's slope, p-values, significance, confidence intervals, autocorrelation, FDR and causation.",
    "other": "A general Earth Scope page without analysis results.",
}

_CTRL = re.compile(r"[\x00-\x1f\x7f<>`]")


def clean_text(value: Any, limit: int = 80) -> str | None:
    """User-typed labels: no control chars / tags / backticks, single spaces, bounded length."""
    if value is None:
        return None
    s = _CTRL.sub(" ", str(value))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] or None


def r4(x: Any) -> Any:
    """Round floats to 4 significant figures (keeps the context compact and readable)."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, float):
        if x != x:  # NaN
            return None
        return float(f"{x:.4g}")
    if isinstance(x, dict):
        return {k: r4(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [r4(v) for v in x]
    return x


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


@dataclass
class ResolvedContext:
    page_type: str
    label: str
    has_results: bool
    data: dict[str, Any]
    context_id: str | None = None
    job_unfinished: bool = False
    notes: list[str] = field(default_factory=list)


def context_id_for(page_type: str, reference: dict[str, Any] | None) -> str:
    blob = json.dumps({"p": page_type, "r": reference or {}}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Compact statistics
# --------------------------------------------------------------------------- #

def compact_statistics(s: dict[str, Any] | None) -> dict[str, Any] | None:
    if not s:
        return None
    reg, mk, sen, ev = s.get("regression") or {}, s.get("mann_kendall") or {}, s.get("sens_slope") or {}, s.get("evidence") or {}
    out: dict[str, Any] = {
        "alpha": s.get("alpha"),
        "years_used": s.get("n_years"),
        "first_year": s.get("first_year"),
        "last_year": s.get("last_year"),
        "evidence": {"label": ev.get("label"), "explanation": ev.get("explanation")},
        "ols_regression": _drop_none({
            "slope_per_year": reg.get("slope"), "slope_per_decade": reg.get("slope_per_decade"),
            "ci_lower": reg.get("ci_lower"), "ci_upper": reg.get("ci_upper"), "confidence_level": reg.get("confidence_level"),
            "p_value": reg.get("p_value"), "r_squared": reg.get("r_squared"), "significant": reg.get("significant"),
            "direction": reg.get("direction"),
        }),
        "mann_kendall": _drop_none({
            "p_value": mk.get("p_value"), "tau": mk.get("tau"), "z": mk.get("z"), "trend": mk.get("trend"),
            "significant": mk.get("significant"),
        }),
        "sens_slope": _drop_none({
            "slope_per_year": sen.get("slope"), "slope_per_decade": sen.get("slope_per_decade"),
            "ci_lower": sen.get("ci_lower"), "ci_upper": sen.get("ci_upper"), "direction": sen.get("direction"),
        }),
    }
    adv = s.get("advanced") or {}
    if adv:
        mmk, yw, hac = adv.get("modified_mann_kendall") or {}, adv.get("yue_wang_sensitivity") or {}, adv.get("regression_hac") or {}
        ac, lb = adv.get("autocorrelation") or {}, (adv.get("autocorrelation") or {}).get("ljung_box") or {}
        out["autocorrelation_adjusted"] = _drop_none({
            "hamed_rao_canonical": _drop_none({"p_value": mmk.get("canonical_p_value"), "significant": mmk.get("canonical_significant")}),
            "hamed_rao_conservative": _drop_none({"p_value": mmk.get("p_value"), "significant": mmk.get("significant"),
                                                  "correction_applied": mmk.get("correction_applied"),
                                                  "note": mmk.get("reliability_note") or mmk.get("unavailable_reason")}),
            "yue_wang": _drop_none({"p_value": yw.get("canonical_p_value", yw.get("p_value")),
                                    "significant": yw.get("canonical_significant", yw.get("significant"))}),
            "hac_regression": _drop_none({"p_value": hac.get("p_value"), "significant": hac.get("significant"),
                                          "ci_lower": hac.get("ci_lower"), "ci_upper": hac.get("ci_upper")}),
            "ljung_box": _drop_none({"p_value": lb.get("p_value"), "significant_autocorrelation": lb.get("significant")}),
            "acf_lag1": next((p.get("value") for p in ac.get("acf") or [] if p.get("lag") == 1), None),
            "robust_evidence": (adv.get("robust_evidence") or {}).get("label"),
        })
    return r4(_drop_none(out))


def _annual(rows: list[dict[str, Any]] | None, limit: int = 60) -> list[list[Any]] | None:
    pts = [[a["year"], a.get("value")] for a in rows or [] if a.get("used_in_trend") and a.get("value") is not None]
    return r4(pts[-limit:]) or None


def _interpretation(i: dict[str, Any] | None) -> dict[str, Any] | None:
    if not i:
        return None
    return _drop_none({"headline": i.get("headline"), "caveats": (i.get("caveats") or [])[:6]})


def _provenance(m: dict[str, Any]) -> dict[str, Any]:
    return _drop_none({
        "data_mode": m.get("data_mode"), "provider": m.get("provider"), "dataset": m.get("dataset_title"),
        "sources": m.get("sources"), "community": m.get("community"), "retrieved_at": m.get("retrieved_at"),
    })


def _variable(m: dict[str, Any]) -> dict[str, Any]:
    return _drop_none({"name": m.get("variable_name"), "parameter": m.get("parameter"), "long_name": m.get("long_name"),
                       "unit": m.get("unit_display"), "rate_unit": m.get("rate_unit")})


# --------------------------------------------------------------------------- #
# Builders per page type
# --------------------------------------------------------------------------- #

def _point(ref: PointReference, client: NasaPowerClient, settings: Settings) -> ResolvedContext:
    from app.services.analysis_service import build_analysis_response
    from app.utils.validators import build_query

    q = build_query(ref.variable, ref.latitude, ref.longitude,
                    ref.start_year if ref.start_year is not None else settings.default_start_year,
                    ref.end_year if ref.end_year is not None else settings.default_end_year, settings)
    r = build_analysis_response(q, client, settings)
    m, summ = r["metadata"], r["summary"]
    place = clean_text(ref.place) or f"{ref.latitude:.3f}, {ref.longitude:.3f}"
    data = {
        "page_type": "point_results",
        "analysis_type": "point (one NASA POWER grid cell; not a regional average)",
        "variable": _variable(m),
        "location": _drop_none({"name": place, "latitude": ref.latitude, "longitude": ref.longitude,
                                "grid_cell": m.get("grid_cell"), "elevation_m": m.get("elevation_m"),
                                "spatial_resolution": m.get("spatial_resolution")}),
        "period": {"start_year": m["start_year"], "end_year": m["end_year"], "latest_complete_year": m.get("latest_complete_year")},
        "data_completeness": {"monthly_valid": summ["n_monthly_valid"], "monthly_total": summ["n_monthly_total"],
                              "years_used_in_trend": summ["n_annual_used"], "years_total": summ["n_annual_total"],
                              "min_valid_months_per_year": summ["min_valid_months_per_year"]},
        "statistics": compact_statistics(r.get("statistics")),
        "analysis_message": r.get("analysis_message"),
        "annual_means_used": _annual(r.get("annual")),
        "interpretation": _interpretation(r.get("interpretation")),
        "warnings": (r.get("warnings") or [])[:5],
        "source": _provenance(m),
    }
    label = f"{m.get('variable_name')} at {place}, {m['start_year']}–{m['end_year']}"
    return ResolvedContext("point_results", label, True, r4(_drop_none(data)))


def _compare(ref: CompareReference, client: NasaPowerClient, settings: Settings) -> ResolvedContext:
    from app.services.analysis_service import build_comparison_response
    from app.utils.validators import resolve_variable, validate_years

    var = resolve_variable(ref.variable)
    start, end = validate_years(ref.start_year if ref.start_year is not None else settings.default_start_year,
                                ref.end_year if ref.end_year is not None else settings.default_end_year,
                                settings, var.coverage_start_year)
    if len(ref.locations) > settings.max_compare_locations:
        raise InvalidRequestError(f"At most {settings.max_compare_locations} locations can be compared.")
    pts = [(l.latitude, l.longitude, clean_text(l.label) or f"{l.latitude:.2f}, {l.longitude:.2f}") for l in ref.locations]
    r = build_comparison_response(var, pts, start, end, client, settings)
    locs = []
    for e in r["locations"]:
        item: dict[str, Any] = {"label": e["label"], "latitude": e["latitude"], "longitude": e["longitude"], "ok": e["ok"]}
        if e["ok"]:
            summ = e.get("summary") or {}
            item.update(statistics=compact_statistics(e.get("statistics")), analysis_message=e.get("analysis_message"),
                        years_used=summ.get("n_annual_used"), years_total=summ.get("n_annual_total"),
                        grid_cell=(e.get("metadata") or {}).get("grid_cell"))
        else:
            item["error"] = (e.get("error") or {}).get("message")
        locs.append(_drop_none(item))
    data = {
        "page_type": "compare_results",
        "analysis_type": "comparison of separate point analyses (each location is one grid cell, tested independently)",
        "variable": {"name": r["variable_name"], "parameter": r["parameter"], "unit": r["unit_display"], "rate_unit": r["rate_unit"]},
        "period": {"start_year": r["start_year"], "end_year": r["end_year"]},
        "alpha": r["alpha"],
        "locations": locs,
        "comparison_summary": r.get("summary"),
        "source": {"data_mode": r["data_mode"], "provider": "NASA POWER"},
        "chart_note": "The chart can show each location's change relative to its own period mean, so slopes (not absolute levels) are compared.",
    }
    label = f"{r['variable_name']} compared at " + ", ".join(l["label"] for l in locs)
    return ResolvedContext("compare_results", label, True, r4(_drop_none(data)))


def _owner(request: Request, settings: Settings) -> str:
    from app.jobs.security import require_owner

    try:
        return require_owner(request, settings)
    except EarthScopeError:
        raise AiContextUnavailableError(CONTEXT_MESSAGE, ["No analysis session was found in this browser."]) from None


def _owned_job(job_id: str, request: Request, settings: Settings):
    from app.jobs import service as js
    from app.jobs.db import get_sessionmaker

    owner = _owner(request, settings)
    with get_sessionmaker()() as db:
        try:
            job = js.get_owned(db, job_id, owner)
        except EarthScopeError:
            raise AiContextUnavailableError(CONTEXT_MESSAGE) from None
        db.expunge(job)
        return job


def _area_block(m: dict[str, Any]) -> dict[str, Any]:
    mode = m.get("area_mode", "rectangle")
    b = m.get("boundary") or {}
    kind = {"rectangle": "rectangular region (area-weighted mean of the NASA grid cells inside the box)",
            "country": "country boundary (each cell weighted by its exact area inside the boundary)",
            "polygon": "custom polygon (each cell weighted by its exact area inside the polygon)"}[mode]
    return _drop_none({
        "kind": mode, "description": kind, "name": clean_text(m.get("area_name")), "iso3": m.get("iso3"),
        "bounds": m.get("bbox"),
        "area_km2": m.get("polygon_area_km2") or m.get("region_area_km2"),
        "analysed_area_km2": m.get("analysed_area_km2"),
        "land_fraction": m.get("land_fraction"),
        "boundary_dataset": _drop_none({"source": b.get("source"), "version": b.get("version"), "id": b.get("boundary_id")}) or None,
        "geometry_id": m.get("geometry_id"),
    })


def _regional_payload(r: dict[str, Any]) -> dict[str, Any]:
    m, summ = r["metadata"], r["summary"]
    return {
        "analysis_type": {"rectangle": "regional (rectangle)", "country": "country", "polygon": "custom polygon"}[m.get("area_mode", "rectangle")],
        "variable": _variable(m),
        "area": _area_block(m),
        "period": {"start_year": m["start_year"], "end_year": m["end_year"], "latest_complete_year": m.get("latest_complete_year")},
        "grid": _drop_none({"resolution": m.get("grid_resolution"), "cells_used": m.get("n_cells_used"),
                            "cells_excluded": m.get("n_cells_excluded"), "tiles": m.get("n_tiles"),
                            "aggregation_method": m.get("aggregation_method"),
                            "coverage_threshold": m.get("coverage_threshold")}),
        "data_completeness": {"mean_spatial_coverage": summ.get("mean_coverage"),
                              "monthly_valid": summ.get("n_monthly_valid"), "monthly_total": summ.get("n_monthly_total"),
                              "months_below_coverage": summ.get("n_monthly_insufficient"),
                              "years_used_in_trend": summ.get("n_annual_used"), "years_total": summ.get("n_annual_total")},
        "regional_statistics": compact_statistics(r.get("statistics")),
        "analysis_message": r.get("analysis_message"),
        "annual_regional_means_used": _annual(r.get("annual")),
        "interpretation": _interpretation(r.get("interpretation")),
        "warnings": (r.get("warnings") or [])[:5],
        "source": _drop_none({**_provenance(m), "execution_mode": m.get("execution_mode"), "job_id": m.get("job_id")}),
    }


def _spatial_payload(sp: dict[str, Any], ui: Any) -> dict[str, Any]:
    cfg, summ = sp.get("config") or {}, sp.get("summary") or {}
    cats = {k: _drop_none({"cells": v.get("count"), "pct_of_tested_cells": v.get("pct_of_tested_cells"),
                           "pct_of_tested_area": v.get("pct_of_tested_area")})
            for k, v in (summ.get("categories") or {}).items()}
    agg = sp.get("regional_aggregate") or {}
    out = {
        "available": sp.get("available"),
        "unavailable_reason": sp.get("unavailable_reason"),
        "test": cfg.get("method_label"), "test_description": cfg.get("method_description"),
        "multiple_testing_correction": cfg.get("correction_label"), "alpha": cfg.get("alpha"),
        "significance_rule": cfg.get("adjusted_rule") if cfg.get("correction") != "none" else cfg.get("raw_rule"),
        "direction_basis": cfg.get("direction_basis"),
        "cells": _drop_none({"total": summ.get("n_cells_total"), "included": summ.get("n_cells_included"),
                             "analysed": summ.get("n_cells_analysed"), "tested": summ.get("n_hypotheses"),
                             "raw_p_below_alpha": summ.get("n_raw_significant"),
                             "fdr_discoveries": summ.get("n_fdr_discoveries"),
                             "positive_slope": summ.get("n_positive_slope"), "negative_slope": summ.get("n_negative_slope"),
                             "near_zero_slope": summ.get("n_near_zero_slope")}),
        "categories": cats,
        "area_weighted_mean_ols_slope": summ.get("area_weighted_mean_ols_slope"),
        "regional_aggregate": _drop_none({"ols_slope": agg.get("ols_slope"), "ols_p_value": agg.get("ols_p_value"),
                                          "sen_slope": agg.get("sen_slope"), "mk_p_value": agg.get("mk_p_value"),
                                          "evidence": agg.get("evidence_label")}),
        "interpretation": (sp.get("interpretation") or [])[:4],
    }
    if ui is not None:
        layer_text = {
            "magnitude": "trend magnitude (colour = slope per year; red/warm = increase, blue/cool = decrease)",
            "direction": "trend direction (increase / decrease / near zero)",
            "significance": "statistical significance class of each cell",
            "availability": "data availability per cell",
        }
        out["map_display"] = _drop_none({
            "layer": layer_text.get(ui.layer) if ui.layer else None,
            "slope_estimator": {"sen": "Sen's slope", "ols": "OLS slope"}.get(ui.estimator or ""),
            "significance_basis": {"adjusted": "FDR-adjusted p-values (q)", "raw": "raw p-values"}.get(ui.basis or ""),
        })
    return out


def _cell_payload(cd: dict[str, Any]) -> dict[str, Any]:
    c = cd.get("cell") or {}
    keep = ("id", "latitude", "longitude", "overlap_fraction", "valid_years", "total_years", "period_mean", "data_status",
            "ols_slope", "ols_p_value", "ols_ci_lower", "ols_ci_upper", "sen_slope", "sen_ci_lower", "sen_ci_upper",
            "mk_p_value", "hr_canonical_p_value", "hr_conservative_p_value", "yw_canonical_p_value", "hac_p_value",
            "raw_p_value", "adjusted_p_value", "raw_status", "adjusted_status", "status", "status_reason", "direction_sen")
    return r4(_drop_none({k: c.get(k) for k in keep}))


def _regional(ref: RegionalReference, client: NasaPowerClient, settings: Settings, request: Request) -> ResolvedContext:
    from app.services import spatial_trend_analysis as sta

    spatial = ref.spatial
    if spatial is not None:
        sta.validate_settings(spatial.method, spatial.correction, spatial.alpha)
    if ref.job_id:
        from app.jobs import results as jr
        from app.jobs.artifacts import get_store
        from app.jobs.models import JobStatus

        job = _owned_job(ref.job_id, request, settings)
        if job.status != JobStatus.COMPLETED:
            return _job_status_context(job, settings)
        store = get_store()
        r = jr.regional(store, job)
        sp = jr.spatial(store, job, settings, spatial.method, spatial.correction, spatial.alpha, None) if spatial else None
        cell = None
        if spatial and spatial.selected_cell_id:
            try:
                cell = jr.cell_detail(store, job, settings, spatial.selected_cell_id, spatial.method, spatial.correction, spatial.alpha)
            except EarthScopeError:
                cell = None
    else:
        if not ref.variable or ref.area is None:
            raise InvalidRequestError("A regional reference needs a variable and an area (or a job id).")
        a = ref.area
        if a.kind == "rectangle":
            from app.api.routes.regional import _query as rect_query

            q = rect_query(settings, ref.variable, a.bbox.lat_min, a.bbox.lat_max, a.bbox.lon_min, a.bbox.lon_max,
                           ref.start_year, ref.end_year, ref.coverage_threshold)
        else:
            from app.api.routes.areas import _query as area_query
            from app.models.area_schemas import AreaRequest

            req = AreaRequest(iso3=a.iso3 if a.kind == "country" else None,
                              geometry=a.geometry if a.kind == "polygon" else None,
                              name=clean_text(a.name, 120) if a.kind == "polygon" else None,
                              variable=ref.variable, start_year=ref.start_year, end_year=ref.end_year,
                              coverage_threshold=ref.coverage_threshold)
            q = area_query(req, settings)
        from app.services.regional_analysis import build_regional_response

        r = build_regional_response(q, client, settings, analyze=True)
        sp = sta.build_spatial_response(q, client, settings, spatial.method, spatial.correction, spatial.alpha) if spatial else None
        cell = None
        if spatial and spatial.selected_cell_id:
            try:
                cell = sta.build_cell_detail(q, client, settings, spatial.selected_cell_id, spatial.method, spatial.correction, spatial.alpha)
            except EarthScopeError:
                cell = None
    data: dict[str, Any] = {"page_type": "regional_results", **_regional_payload(r)}
    if sp is not None:
        data["spatial_trend_explorer"] = _spatial_payload(sp, spatial)
    if spatial and spatial.selected_cell_id:
        data["selected_cell"] = _cell_payload(cell) if cell else {"id": spatial.selected_cell_id, "note": "Selected cell is not available."}
    m = r["metadata"]
    where = clean_text(m.get("area_name")) or "the selected rectangle"
    label = f"{m.get('variable_name')} for {where}, {m['start_year']}–{m['end_year']}"
    return ResolvedContext("regional_results", label, True, r4(_drop_none(data)))


def _job_status_context(job: Any, settings: Settings) -> ResolvedContext:
    from app.jobs import service as js

    p = js.progress_dict(job)
    data = {
        "page_type": "job_details",
        "analysis_type": "background analysis job (large country / polygon)",
        "job": _drop_none({
            "status": job.status, "stage": p["stage_label"], "activity": p.get("activity"),
            "progress_pct": p["progress_pct"], "tier": job.tier,
            "area": clean_text(job.area_name), "iso3": job.iso3, "variable_id": job.variable_id, "parameter": job.parameter,
            "period": f"{job.start_year}–{job.end_year}",
            "tiles": p["download"], "cells": p["processing"],
            "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
            "results_ready": job.status == "COMPLETED",
            "stages": [{"stage": s.get("label") or s.get("id"), "state": s.get("state")} for s in p.get("stages") or []][:14],
        }),
        "note": "Scientific results exist only after the job is COMPLETED. Never describe results for an unfinished job.",
    }
    label = f"Background job: {clean_text(job.area_name) or job.iso3} ({job.status})"
    return ResolvedContext("job_details", label, False, r4(data), job_unfinished=job.status != "COMPLETED")


def _job_details(ref: JobReference, settings: Settings, request: Request) -> ResolvedContext:
    job = _owned_job(ref.job_id, request, settings)
    ctx = _job_status_context(job, settings)
    if job.status == "COMPLETED":
        from app.jobs import results as jr
        from app.jobs.artifacts import get_store

        try:
            ctx.data["completed_result"] = r4(_drop_none(_regional_payload(jr.regional(get_store(), job))))
            ctx.has_results = True
        except EarthScopeError:
            ctx.notes.append("Results could not be loaded.")
    return ctx


def _jobs(settings: Settings, request: Request) -> ResolvedContext:
    from app.jobs import service as js
    from app.jobs.db import get_sessionmaker
    from app.jobs.security import require_owner

    jobs_out: list[dict[str, Any]] = []
    try:
        owner = require_owner(request, settings)
        with get_sessionmaker()() as db:
            for j in js.list_owned(db, owner, 10):
                p = js.progress_dict(j)
                jobs_out.append(_drop_none({"area": clean_text(j.area_name), "variable_id": j.variable_id, "status": j.status,
                                            "stage": p["stage_label"], "progress_pct": p["progress_pct"],
                                            "error": j.error_code}))
    except EarthScopeError:
        pass
    except Exception:  # noqa: BLE001 - job database down: the page explanation still works
        logger.warning("ai context: job list unavailable")
    data = {"page_type": "jobs", "description": PAGE_DESCRIPTIONS["jobs"], "jobs": jobs_out,
            "lifecycle": "PENDING → QUEUED → RUNNING → COMPLETED (or RETRYING / FAILED / CANCELLED; results expire after the retention period)"}
    return ResolvedContext("jobs", "Analysis Jobs", False, r4(data))


def _parse(model: type[BaseModel], reference: dict[str, Any] | None) -> Any:
    try:
        return model.model_validate(reference or {})
    except ValidationError as exc:
        raise InvalidRequestError("The analysis reference is invalid.",
                                  [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()][:6]) from None


def resolve_context(page_type: str, reference: dict[str, Any] | None, *, client: NasaPowerClient, settings: Settings,
                    request: Request) -> ResolvedContext:
    """Authoritative context for the page. Raises EarthScopeError (incl. AiContextUnavailableError)."""
    if page_type == "point_results":
        ctx = _point(_parse(PointReference, reference), client, settings)
    elif page_type == "compare_results":
        ctx = _compare(_parse(CompareReference, reference), client, settings)
    elif page_type == "regional_results":
        ctx = _regional(_parse(RegionalReference, reference), client, settings, request)
    elif page_type == "job_details":
        ctx = _job_details(_parse(JobReference, reference), settings, request)
    elif page_type == "jobs":
        ctx = _jobs(settings, request)
    elif page_type == "learn":
        topic = clean_text(_parse(LearnReference, reference).topic, 80)
        ctx = ResolvedContext("learn", f"Learn: {topic}" if topic else "Learn", False,
                              {"page_type": "learn", "description": PAGE_DESCRIPTIONS["learn"], "selected_topic": topic})
    else:
        pt = page_type if page_type in PAGE_DESCRIPTIONS else "other"
        ctx = ResolvedContext(pt, pt.replace("_", " ").title(), False,
                              {"page_type": pt, "description": PAGE_DESCRIPTIONS[pt], "has_results": False})
    ctx.context_id = context_id_for(page_type, reference)
    return ctx


def fit_context(data: dict[str, Any], limit: int) -> dict[str, Any]:
    """Drop low-priority detail until the serialised context fits the size budget."""
    def size(d: dict[str, Any]) -> int:
        return len(json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str))

    if size(data) <= limit:
        return data
    d = json.loads(json.dumps(data, default=str))
    paths = [("warnings",), ("interpretation",), ("completed_result", "warnings"), ("completed_result", "interpretation"),
             ("spatial_trend_explorer", "interpretation"), ("annual_means_used",), ("annual_regional_means_used",),
             ("completed_result", "annual_regional_means_used"), ("comparison_summary",), ("job", "stages"),
             ("spatial_trend_explorer", "test_description")]
    for path in paths:
        node = d
        for key in path[:-1]:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and path[-1] in node:
            node.pop(path[-1])
            if size(d) <= limit:
                return d
    # Last resort: keep the identifying header only.
    keep = {k: d[k] for k in ("page_type", "analysis_type", "variable", "location", "area", "period", "statistics",
                              "regional_statistics", "source") if k in d}
    keep["note"] = "Context truncated to fit the size limit."
    return keep
