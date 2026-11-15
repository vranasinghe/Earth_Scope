"""Live NASA POWER validation of the background-job pipeline (Phase 6).

Runs the REAL worker code (claim, lease/heartbeat, checkpointed stages, NASA
tile download through the Redis-style global limiter, publication) against the
live NASA POWER API, then checks the published result:

1. Synchronous equality — the synchronous country/polygon pipeline is run on
   the SAME verified tile payloads (served from the job's checkpoints, so NASA
   is not asked twice) and every monthly, annual, statistical and per-cell
   number must be identical.
2. Independent recomputation — a sample of regional monthly means (Σ v·w / Σ w),
   cell annual means (day-weighted) and OLS slopes (numpy.polyfit) recomputed
   directly from the raw tile payloads; BH/BY adjusted p-values recomputed with
   statsmodels over the complete family.
3. Completeness — every needed cell present, duplicate cells identical.

Usage (from backend/, uses SQLite + an in-process Redis double; the Docker
Compose stack is NOT needed — see README for the Docker variant)::

    .venv\\Scripts\\python.exe scripts\\live_job_validation.py LKA
    .venv\\Scripts\\python.exe scripts\\live_job_validation.py USA --crash-after-tiles 10
    .venv\\Scripts\\python.exe scripts\\live_job_validation.py RUS --preflight-only

Reports are written to var/live-validation/<ISO3>-report.json.
"""

from __future__ import annotations

import argparse
import calendar
import ctypes
import json
import math
import os
import random
import sys
import time
from datetime import timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "var" / "live-validation"
OUT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("EARTHSCOPE_DATABASE_URL", f"sqlite:///{(OUT / 'jobs.db').as_posix()}")
os.environ.setdefault("EARTHSCOPE_ARTIFACT_DIR", str(OUT / "artifacts"))
os.environ.setdefault("EARTHSCOPE_JOB_DAILY_TILE_BUDGET_PER_SESSION", "1000")
os.environ.setdefault("EARTHSCOPE_JOB_MAX_SUBMISSIONS_PER_HOUR", "100")
os.environ.setdefault("EARTHSCOPE_JOB_MAX_SUBMISSIONS_PER_IP_PER_DAY", "1000")
sys.path.insert(0, str(BACKEND))

import fakeredis  # noqa: E402
import numpy as np  # noqa: E402
from sqlalchemy import select, update  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.jobs import pipeline as jp  # noqa: E402
from app.jobs import queue as jq  # noqa: E402
from app.jobs import reconciler as jrec  # noqa: E402
from app.jobs import results as jr  # noqa: E402
from app.jobs import service as js  # noqa: E402
from app.jobs.artifacts import ArtifactStore, get_store  # noqa: E402
from app.jobs.coordination import GlobalNasaLimiter  # noqa: E402
from app.jobs.db import ensure_schema, get_sessionmaker  # noqa: E402
from app.jobs.models import AnalysisJob, JobTile, utcnow  # noqa: E402
from app.services import area_analysis as aa  # noqa: E402
from app.services import regional_analysis as ran  # noqa: E402
from app.services import spatial_trend_analysis as sta  # noqa: E402
from app.services.nasa_power import NasaPowerClient  # noqa: E402


def peak_rss_mb() -> float | None:
    if os.name == "nt":
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return round(c.PeakWorkingSetSize / 1e6, 1)
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM"):
                return round(int(line.split()[1]) / 1e3, 1)
    except OSError:
        return None
    return None


class Crash(BaseException):
    pass


class CountingClient(NasaPowerClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = 0
        self.failures: list[str] = []

    def fetch_regional(self, *a, **kw):
        self.calls += 1
        try:
            return super().fetch_regional(*a, **kw)
        except Exception as exc:
            self.failures.append(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")
            raise


class BlobSession:
    """Serves NASA regional requests from the job's verified tile blobs (no network)."""

    def __init__(self, store: ArtifactStore, rows: list[JobTile]):
        self.store = store
        self.by_box = {(f"{r.lat_min:.4f}", f"{r.lat_max:.4f}", f"{r.lon_min:.4f}", f"{r.lon_max:.4f}"): r.blob_sha256 for r in rows}
        self.headers: dict = {}
        self.served = 0

    def get(self, url, params=None, timeout=None):
        key = tuple(params[k] for k in ("latitude-min", "latitude-max", "longitude-min", "longitude-max"))
        payload = self.store.get_tile_blob(self.by_box[key])
        self.served += 1

        class Resp:
            status_code = 200
            headers: dict = {}

            def json(self_inner):
                return payload

        return Resp()


def norm(x):
    return json.loads(json.dumps(x, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def diff(a, b, path="$", out=None):
    out = out if out is not None else {"mismatches": [], "n_numbers": 0, "max_abs": 0.0}
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b:
                out["mismatches"].append(f"{path}.{k}: missing on one side")
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out["mismatches"].append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        out["n_numbers"] += 1
        if not (a == b or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))):
            out["max_abs"] = max(out["max_abs"], abs(a - b))
            out["mismatches"].append(f"{path}: {a!r} vs {b!r}")
    elif a != b:
        out["mismatches"].append(f"{path}: {str(a)[:60]!r} vs {str(b)[:60]!r}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("iso3")
    ap.add_argument("--variable", default="T2M")
    ap.add_argument("--start", type=int, default=2001)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--crash-after-tiles", type=int, default=0, help="simulate a worker crash after N verified tiles, then resume")
    ap.add_argument("--no-sync-compare", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    ensure_schema()
    sm, store = get_sessionmaker(), get_store()
    jq.set_enqueuer(lambda jid: f"local-{jid}")
    report: dict = {"iso3": args.iso3, "variable": args.variable, "period": [args.start, args.end], "kind": "LIVE NASA, full country boundary"}

    req = js.JobRequest(args.iso3, None, None, args.variable, args.start, args.end, None, "live", "mann_kendall", "fdr_bh", 0.05)
    t0 = time.monotonic()
    with sm() as db:
        plan = js.build_plan(req, s, db)
    report["preflight"] = {"seconds": round(time.monotonic() - t0, 2), "boundary": plan.area.boundary, "area_km2": plan.area.area_km2,
                           **{k: plan.preflight[k] for k in ("n_cells", "n_tiles", "n_values")}, "classification": plan.classification,
                           "estimates": plan.estimates}
    print(json.dumps(report["preflight"], indent=1, default=str))
    if args.preflight_only or not plan.classification["eligible"]:
        (OUT / f"{args.iso3}-preflight.json").write_text(json.dumps(report, indent=2, default=str))
        return

    owner = js.canonical_hash({"validation": args.iso3, "t": time.time()})
    with sm() as db:
        job, _, _ = js.submit(db, plan, owner, None, None, True, s, store)
        jid = job.id
    report["job_id"] = jid
    limiter = GlobalNasaLimiter(fakeredis.FakeRedis(), s.nasa_global_max_concurrency, s.nasa_slot_lease_seconds,
                                s.nasa_min_request_interval_seconds)
    client = CountingClient(s.model_copy(update={"cache_max_entries": 1}))
    t_run = time.monotonic()

    if args.crash_after_tiles:
        orig = ArtifactStore.put_tile_blob
        n = {"i": 0}

        def crashing(self, payload):
            n["i"] += 1
            if n["i"] > args.crash_after_tiles:
                raise Crash()
            return orig(self, payload)

        ArtifactStore.put_tile_blob = crashing
        try:
            jp.execute(jid, "validator-A:1:x", s, sm, store, lambda: limiter, lambda: client)
        except Crash:
            pass
        ArtifactStore.put_tile_blob = orig
        time.sleep(1.0)  # let in-flight tile threads of the "dead" worker settle
        with sm() as db:
            verified_before = sum(1 for t in db.scalars(select(JobTile).where(JobTile.job_id == jid)) if t.status == "VERIFIED")
            db.execute(update(AnalysisJob).execution_options(synchronize_session=False).where(AnalysisJob.id == jid)
                       .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
            db.commit()
        rec = jrec.reconcile_once(sm, s, store, rq_state=lambda _: None)
        calls_before = client.calls
        report["crash_simulation"] = {"crashed_after_tiles": args.crash_after_tiles, "verified_before_crash": verified_before,
                                      "reconciler": {k: v for k, v in rec.items() if v}}
    outcome = jp.execute(jid, "validator-B:1:y", s, sm, store, lambda: limiter, lambda: client)
    run_s = time.monotonic() - t_run
    with sm() as db:
        job = db.get(AnalysisJob, jid)
        rows = list(db.scalars(select(JobTile).where(JobTile.job_id == jid).order_by(JobTile.tile_key)))
        for r in rows:
            db.expunge(r)
        db.expunge(job)
    if args.crash_after_tiles:
        report["crash_simulation"]["nasa_requests_after_resume"] = client.calls - calls_before
        report["crash_simulation"]["tiles_needing_download_after_resume"] = len(rows) - report["crash_simulation"]["verified_before_crash"]
    report["run"] = {"outcome": outcome, "status": job.status, "error": [job.error_code, job.error_message], "wall_seconds": round(run_s, 1),
                     "nasa_requests": client.calls, "nasa_request_failures": client.failures[:10], "metrics": job.metrics,
                     "attempts": job.attempt_count, "peak_rss_mb": peak_rss_mb(), "result_mb": round((job.result_bytes or 0) / 1e6, 2),
                     "tile_blob_mb": round(sum(r.blob_bytes or 0 for r in rows) / 1e6, 1),
                     "tiles": [{"tile": r.tile_key, "attempts": r.attempts, "from_cache": r.from_cache, "features": r.n_features} for r in rows]}
    print(json.dumps({k: v for k, v in report["run"].items() if k != "tiles"}, indent=1, default=str))
    if job.status != "COMPLETED":
        (OUT / f"{args.iso3}-report.json").write_text(json.dumps(report, indent=2, default=str))
        sys.exit(f"Job did not complete: {job.status} {job.error_code}")

    reg = jr.regional(store, job)
    sp = jr.spatial(store, job, s, "mann_kendall", "fdr_bh", 0.05)
    m = reg["metadata"]
    checks: dict = {}

    # --- completeness and duplicates -------------------------------------------------
    # Cells are identified by integer grid indices (NASA returns e.g. -0.0 for equator centres,
    # so formatted coordinate strings are not a safe key).
    from app.services import area_geometry as ag

    grid = ag.grid_for(plan.variable)
    cells = {c["id"]: c for c in sp["cells"]}
    needed = {grid.index(c["latitude"], c["longitude"]): cid for cid, c in cells.items()}
    raw: dict[str, dict] = {}
    dup_conflicts = n_dup = 0
    for r in rows:
        payload = store.get_tile_blob(r.blob_sha256)
        for f in payload["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            cid = needed.get(grid.index(float(lat), float(lon)))
            if cid is None:
                continue                       # outside the area (tile padding)
            series = f["properties"]["parameter"][args.variable]
            if cid in raw:
                n_dup += 1
                dup_conflicts += raw[cid] != series
            else:
                raw[cid] = series
        del payload
    missing = [cid for cid in cells if cid not in raw]
    checks["completeness"] = {"cells_needed": len(cells), "cells_missing": len(missing), "tiles": len(rows),
                              "all_tiles_verified": all(r.status == "VERIFIED" for r in rows),
                              "duplicate_cells_seen": n_dup, "duplicate_conflicts": dup_conflicts,
                              "metadata_n_duplicates": m["n_duplicates"], "grid_representability": m.get("grid_representability")}

    # --- independent recomputation -------------------------------------------------
    fill = -999.0
    w = {cid: (c["overlap_area_km2"] if c["data_status"] != "excluded" else 0.0) for cid, c in cells.items()}
    month_checks = []
    for rec_m in random.Random(1).sample([x for x in reg["monthly"] if x["computed_mean"] is not None], 8):
        key = f"{rec_m['year']}{rec_m['month']:02d}"
        num = den = 0.0
        for cid, wt in w.items():
            v = raw.get(cid, {}).get(key)
            if v is None or v == fill or wt == 0:
                continue
            num += v * wt
            den += wt
        month_checks.append(abs(num / den - rec_m["computed_mean"]))
    cell_checks = []
    for cid in random.Random(2).sample([c for c, x in cells.items() if x["data_status"] == "analysed"], 6):
        series = raw[cid]
        yrs, vals = [], []
        for y in range(args.start, args.end + 1):
            mv = [(series.get(f"{y}{mm:02d}"), calendar.monthrange(y, mm)[1]) for mm in range(1, 13)]
            ok = [(v, d) for v, d in mv if v is not None and v != fill]
            if len(ok) >= s.min_valid_months_per_year:
                yrs.append(y)
                vals.append(sum(v * d for v, d in ok) / sum(d for _, d in ok))
        slope = float(np.polyfit(yrs, vals, 1)[0])
        detail = jr.cell_detail(store, job, s, cid, "mann_kendall", "fdr_bh", 0.05)
        ann = {a["year"]: a["value"] for a in detail["annual"] if a["used_in_trend"]}
        cell_checks.append({"cell": cid, "annual_max_abs": max(abs(ann[y] - v) for y, v in zip(yrs, vals)),
                            "ols_slope_abs_diff": abs(slope - cells[cid]["ols_slope"])})
    fam = [c for c in sp["cells"] if c["in_family"]]
    bh = multipletests([c["raw_p_value"] for c in fam], method="fdr_bh")[1]
    by_sp = jr.spatial(store, job, s, "mann_kendall", "fdr_by", 0.05)
    fam_by = [c for c in by_sp["cells"] if c["in_family"]]
    by = multipletests([c["raw_p_value"] for c in fam_by], method="fdr_by")[1]
    checks["independent"] = {
        "regional_monthly_mean_max_abs_diff": max(month_checks),
        "cells": cell_checks,
        "bh_family_size": len(fam), "bh_max_abs_diff": float(np.max(np.abs(np.array([c["adjusted_p_value"] for c in fam]) - bh))) if fam else None,
        "by_max_abs_diff": float(np.max(np.abs(np.array([c["adjusted_p_value"] for c in fam_by]) - by))) if fam_by else None,
        "n_raw_significant": sp["summary"]["n_raw_significant"], "n_fdr_discoveries": sp["summary"]["n_fdr_discoveries"],
    }

    # --- synchronous equality on the same payloads -----------------------------------
    if not args.no_sync_compare:
        big = s.model_copy(update={"polygon_max_cells": 10**6, "polygon_max_tiles": 10**4, "polygon_max_values": 10**9})
        session = BlobSession(store, rows)
        sync_client = NasaPowerClient(big, session=session)
        area = aa.area_from_request(args.iso3, None, None, big)
        q = ran.RegionalQuery(plan.variable, area.bbox, args.start, args.end, plan.coverage, area)
        ran._results_cache.clear()
        sta._cell_cache.clear()
        t1 = time.monotonic()
        sreg = norm(ran.build_regional_response(q, sync_client, big, "live", analyze=True))
        ssp = norm(sta.build_spatial_response(q, sync_client, big, "live", "mann_kendall", "fdr_bh", 0.05))
        sync_s = time.monotonic() - t1
        from app.models.regional_schemas import RegionalAnalysisResponse
        from app.models.spatial_trend_schemas import SpatialTrendResponse

        sreg = norm(RegionalAnalysisResponse.model_validate(sreg).model_dump(mode="json"))
        ssp = norm(SpatialTrendResponse.model_validate(ssp).model_dump(mode="json"))
        breg = norm(RegionalAnalysisResponse.model_validate(reg).model_dump(mode="json"))
        bsp = norm(SpatialTrendResponse.model_validate(sp).model_dump(mode="json"))
        d1 = diff({k: sreg[k] for k in ("monthly", "annual", "summary", "cells", "statistics")},
                  {k: breg[k] for k in ("monthly", "annual", "summary", "cells", "statistics")})
        d2 = diff({k: ssp[k] for k in ("cells", "summary", "config", "regional_aggregate")},
                  {k: bsp[k] for k in ("cells", "summary", "config", "regional_aggregate")})
        checks["synchronous_equality"] = {
            "sync_seconds_same_payloads": round(sync_s, 1), "payload_requests_served_from_checkpoints": session.served,
            "regional_numbers_compared": d1["n_numbers"], "regional_mismatches": d1["mismatches"][:10],
            "spatial_numbers_compared": d2["n_numbers"], "spatial_mismatches": d2["mismatches"][:10],
            "identical": not d1["mismatches"] and not d2["mismatches"],
        }
    s_reg = reg.get("statistics") or {}
    report["result"] = {
        "data_mode": m["data_mode"], "n_cells_used": m["n_cells_used"], "n_tiles": m["n_tiles"], "boundary": (m.get("boundary") or {}).get("version"),
        "ols_slope_per_year": (s_reg.get("regression") or {}).get("slope"), "mk_p": (s_reg.get("mann_kendall") or {}).get("p_value"),
        "sen_slope": (s_reg.get("sens_slope") or {}).get("slope"), "evidence": (s_reg.get("evidence") or {}).get("label"),
        "n_years": s_reg.get("n_years"), "warnings": reg["warnings"][:5],
    }
    report["checks"] = checks
    (OUT / f"{args.iso3}-report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"checks": checks, "result": report["result"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
