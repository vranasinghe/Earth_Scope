"""Reading published job results (owner checks happen in the API layer).

The manifest checksum recorded in PostgreSQL is verified on every request; each
result file is verified against the manifest when first loaded and then kept
in a small in-process cache keyed by that checksum.

Spatial results for any test / correction / α are recomputed from the stored
per-cell p-values over the COMPLETE cell family of the area. A viewport filter
only trims which cells are returned — it never changes the family, the
adjusted p-values or the summary.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings
from app.jobs.artifacts import ArtifactCorruptError, ArtifactStore
from app.jobs.models import AnalysisJob
from app.services import spatial_trend_analysis as sta
from app.services.nasa_power import TTLCache
from app.utils.errors import InvalidRequestError

_cache = TTLCache(ttl_seconds=3600, max_entries=12)


def manifest(store: ArtifactStore, job: AnalysisJob) -> dict[str, Any]:
    if not job.result_ref or not job.result_sha256:
        raise ArtifactCorruptError("This job has no published result.")
    key = ("manifest", job.id, job.result_sha256)
    hit = _cache.get(key)
    if hit is None:
        hit = json.loads(store.read_bytes(f"{job.result_ref}/manifest.json", job.result_sha256))
        _cache.set(key, hit)
    return hit


def _load(store: ArtifactStore, job: AnalysisJob, name: str) -> Any:
    m = manifest(store, job)
    f = m["files"].get(name)
    if f is None:
        raise ArtifactCorruptError("A result file is missing from the manifest.", [name])
    key = ("file", job.id, f["sha256"])
    hit = _cache.get(key)
    if hit is None:
        hit = store.read_json_gz(f"{job.result_ref}/{name}", f["sha256"])
        _cache.set(key, hit)
    return hit


def regional(store: ArtifactStore, job: AnalysisJob) -> dict[str, Any]:
    return _load(store, job, "regional.json.gz")


def _in_bbox(c: dict[str, Any], bbox: tuple[float, float, float, float] | None) -> bool:
    if bbox is None:
        return True
    la0, la1, lo0, lo1 = bbox
    return c["lat_max"] >= la0 and c["lat_min"] <= la1 and c["lon_max"] >= lo0 and c["lon_min"] <= lo1


def spatial(store: ArtifactStore, job: AnalysisJob, settings: Settings, method: str, correction: str, alpha: float,
            bbox: tuple[float, float, float, float] | None = None) -> dict[str, Any]:
    sta.validate_settings(method, correction, alpha)
    if (method, correction) == (job.method, job.correction) and abs(alpha - job.alpha) < 1e-12:
        out = _load(store, job, "spatial_default.json.gz")
    else:
        key = ("spatial", job.id, job.result_sha256, method, correction, round(alpha, 6))
        out = _cache.get(key)
        if out is None:
            cs_raw = _load(store, job, "cells.json.gz")
            cs = sta.CellTrendSet(cs_raw["cells"], {}, cs_raw["years"], cs_raw["metadata"], cs_raw["warnings"], cs_raw["complete_records"])
            reg = sta.regional_aggregate_from(regional(store, job))
            out = sta.spatial_response_from_set(cs_raw["metadata"]["variable_name"], cs, reg, settings, method, correction, alpha)
            _cache.set(key, out)
    if bbox is not None:
        out = {**out, "cells": [c for c in out["cells"] if _in_bbox(c, bbox)]}
    return out


def cell_detail(store: ArtifactStore, job: AnalysisJob, settings: Settings, cid: str, method: str, correction: str,
                alpha: float) -> dict[str, Any]:
    cs_raw = _load(store, job, "cells.json.gz")
    k = cs_raw["detail_index"].get(cid)
    if k is None:
        raise InvalidRequestError(f"Grid cell '{cid}' is not part of this analysis.", ["Use a cell id from the spatial results."])
    details = _load(store, job, f"details/chunk-{int(k):05d}.json.gz")[cid]
    sp = spatial(store, job, settings, method, correction, alpha)
    cell = next(c for c in sp["cells"] if c["id"] == cid)
    reg = regional(store, job)
    return {
        "metadata": sp["metadata"], "config": sp["config"], "cell": cell, "annual": details["annual"],
        "statistics": details["statistics"],
        "regional_annual": [{"year": a["year"], "value": a["value"], "used_in_trend": a["used_in_trend"]} for a in reg["annual"]],
    }


def artifact_list(store: ArtifactStore, job: AnalysisJob) -> list[dict[str, Any]]:
    m = manifest(store, job)
    return [{"name": n, "bytes": f["bytes"], "sha256": f["sha256"], "content_type": f["content_type"],
             "downloadable": n.startswith("exports/") or n in ("regional.json.gz", "spatial_default.json.gz")}
            for n, f in sorted(m["files"].items())]


def artifact_bytes(store: ArtifactStore, job: AnalysisJob, name: str) -> tuple[bytes, str]:
    m = manifest(store, job)
    f = m["files"].get(name)
    if f is None:
        raise ArtifactCorruptError("No such result file.", [name])
    return store.read_bytes(f"{job.result_ref}/{name}", f["sha256"]), f["content_type"]
