"""Background jobs: lifecycle, durability, idempotency, NASA retrieval, budgets, science equality, security.

Infrastructure is real code with test doubles at the edges: SQLite (same
SQLAlchemy models and compare-and-set updates as PostgreSQL), fakeredis (the
real WATCH/MULTI limiter code), a temporary artifact directory, and a fake NASA
session that answers any regional box (from test_polygon_analysis). Worker
crashes are simulated with a BaseException that escapes the worker like a
killed process would: no failure is recorded, the lease simply stops being
renewed.
"""

from __future__ import annotations

import gzip
import json
import math
import threading
import time
from datetime import timedelta
from pathlib import Path

import fakeredis
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from statsmodels.stats.multitest import multipletests

from app.core.catalog import get_variable
from app.core.config import get_settings
from app.jobs import pipeline as jp
from app.jobs import queue as jq
from app.jobs import reconciler as jrec
from app.jobs import resources as jres
from app.jobs.artifacts import ArtifactStore, StorageFullError, get_store
from app.jobs.coordination import GlobalNasaLimiter
from app.jobs.db import ensure_schema, get_engine, get_sessionmaker, with_db_retry
from app.jobs.models import AnalysisJob, JobEvent, JobStatus, JobTile, TileStatus, utcnow
from app.main import app
from app.services import area_analysis as aa
from app.services import area_geometry as ag
from app.services import boundaries
from app.services import regional_analysis as ran
from app.services import spatial_trend_analysis as sta
from app.services.nasa_power import NasaPowerClient
from app.services.regional_tiling import Tile, plan_tiles, validate_tile_payload
from app.utils.errors import NasaPowerResponseError
from tests.test_polygon_analysis import TileSession, noise, poly

START, END = 2001, 2016
# 12° × 3° quadrilateral: 2 NASA tiles, ~130 cells, partial cells along the sloped edge.
AREA = poly([(70.0, 6.0), (82.0, 6.0), (82.0, 9.0), (70.0, 8.0)])


def value_fn(la, lo, y, m):
    return 20 + (0.04 if lo < 76 else -0.03) * (y - START) + 2 * math.sin(m) + noise(la, lo, y, m, 0.4)


class Crash(BaseException):
    """Simulates the worker process dying (escapes every `except Exception`)."""


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #

class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.enqueued: list[str] = []
        self.enqueue_fail = False
        self.redis = fakeredis.FakeRedis()

    def enqueuer(self, job_id: str) -> str:
        if self.enqueue_fail:
            raise ConnectionError("redis down")
        self.enqueued.append(job_id)
        return f"rq-{job_id}-{len(self.enqueued)}"

    @property
    def sm(self):
        return get_sessionmaker()

    def job(self, job_id: str) -> AnalysisJob:
        with self.sm() as s:
            j = s.get(AnalysisJob, job_id)
            s.expunge(j)
            return j

    def set(self, job_id: str, **values) -> None:
        with self.sm() as s:
            s.execute(update(AnalysisJob).where(AnalysisJob.id == job_id).values(**values))
            s.commit()

    def tiles(self, job_id: str) -> list[JobTile]:
        with self.sm() as s:
            rows = list(s.scalars(select(JobTile).where(JobTile.job_id == job_id).order_by(JobTile.tile_key)))
            for r in rows:
                s.expunge(r)
            return rows

    def run(self, job_id: str, session=None, worker="w1", limiter=None, settings=None) -> str:
        session = session or TileSession(value_fn)
        st = settings or get_settings()
        lim = limiter or GlobalNasaLimiter(self.redis, st.nasa_global_max_concurrency, 300, 0)
        client = NasaPowerClient(st, session=session)
        return jp.execute(job_id, f"{worker}:1:x", st, get_sessionmaker(), get_store(), lambda: lim, lambda: client)

    def expire_lease(self, job_id: str) -> None:
        self.set(job_id, lease_expires_at=utcnow() - timedelta(seconds=5))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHSCOPE_DATABASE_URL", f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    monkeypatch.setenv("EARTHSCOPE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("EARTHSCOPE_JOB_MIN_FREE_DISK_MB", "0")
    monkeypatch.setenv("EARTHSCOPE_JOB_CELL_CHUNK_SIZE", "37")
    monkeypatch.setenv("EARTHSCOPE_JOB_TILE_BACKOFF_SECONDS", "0.01")
    monkeypatch.setenv("EARTHSCOPE_JOB_TILE_BACKOFF_MAX_SECONDS", "0.05")
    monkeypatch.setenv("EARTHSCOPE_NASA_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("EARTHSCOPE_JOB_HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("EARTHSCOPE_JOB_MAX_SUBMISSIONS_PER_HOUR", "50")
    for f in (get_settings, get_engine, get_sessionmaker, get_store):
        f.cache_clear()
    ensure_schema()
    e = Env(tmp_path)
    jq.set_enqueuer(e.enqueuer)
    ran._results_cache.clear()
    sta._cell_cache.clear()
    from app.jobs import results as jr

    jr._cache.clear()
    yield e
    jq.set_enqueuer(jq.Enqueuer())
    get_engine().dispose()
    for f in (get_settings, get_engine, get_sessionmaker, get_store):
        f.cache_clear()
    app.dependency_overrides.clear()


def client_for() -> tuple[TestClient, dict[str, str]]:
    c = TestClient(app)
    r = c.get("/api/analysis/session")
    assert r.status_code == 200
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def body(**kw):
    b = {"geometry": AREA, "name": "Test area", "variable": "T2M", "start_year": START, "end_year": END}
    b.update(kw)
    return b


def submit(c, h, **kw):
    hdr = dict(h)
    if "idem" in kw:
        hdr["Idempotency-Key"] = kw.pop("idem")
    return c.post("/api/analysis/jobs", json=body(**kw), headers=hdr)


def same(a, b, path="$"):
    """Exact structural equality with NaN == NaN (JSON round-trips floats exactly)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{path}: keys {set(a) ^ set(b)}"
        for k in a:
            same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            assert a is b, f"{path}: {a} != {b}"
        elif math.isnan(a):
            assert math.isnan(b), f"{path}: NaN != {b}"
        else:
            assert a == b, f"{path}: {a!r} != {b!r}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


def norm(x):
    return json.loads(json.dumps(x, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


# --------------------------------------------------------------------------- #
# A. Lifecycle
# --------------------------------------------------------------------------- #

def test_submission_returns_202_records_and_queues(env):
    c, h = client_for()
    r = submit(c, h)
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["created"] and d["status"] == "QUEUED" and d["status_url"] == f"/api/analysis/jobs/{d['job_id']}"
    assert d["accepted_configuration"]["data_mode"] == "LIVE" and d["job"]["tier"] == "SMALL"
    assert env.enqueued == [d["job_id"]]
    j = env.job(d["job_id"])
    assert j.tiles_total == 2 and j.cells_total > 100 and j.progress_pct == 0
    assert "coordinates" not in json.dumps(d["job"])        # polygon coordinates are not echoed in job metadata


def test_full_live_job_completes_and_results_load_in_the_standard_schemas(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    assert env.run(jid) == "completed"
    st = c.get(f"/api/analysis/jobs/{jid}").json()
    assert st["status"] == "COMPLETED" and st["progress"]["progress_pct"] == 100 and st["has_results"]
    assert st["progress"]["download"] == {"tiles_completed": 2, "tiles_total": 2, "tiles_retrying": 0, "tiles_failed": 0}
    assert st["progress"]["processing"]["cells_processed"] == st["progress"]["processing"]["cells_total"]
    res = c.get(f"/api/analysis/jobs/{jid}/results").json()
    m = res["metadata"]
    assert m["execution_mode"] == "background" and m["job_id"] == jid and m["data_mode"] == "LIVE" and m["n_tiles"] == 2
    assert len(m["request_manifest"]) == 2 and res["statistics"]["regression"]["slope"] is not None
    sp = c.get(f"/api/analysis/jobs/{jid}/spatial").json()
    assert sp["summary"]["n_hypotheses"] == len([x for x in sp["cells"] if x["in_family"]]) > 50
    cid = sp["cells"][3]["id"]
    cell = c.get(f"/api/analysis/jobs/{jid}/spatial/cell", params={"cell_id": cid}).json()
    assert cell["cell"]["id"] == cid and len(cell["annual"]) == END - START + 1
    arts = c.get(f"/api/analysis/jobs/{jid}/artifacts").json()["files"]
    names = {a["name"] for a in arts}
    assert {"regional.json.gz", "cells.json.gz", "spatial_default.json.gz", "exports/annual.csv", "exports/provenance.json"} <= names
    csv_text = c.get(f"/api/analysis/jobs/{jid}/artifacts/exports/annual.csv").text
    assert csv_text.startswith("# LIVE NASA POWER DATA") and "used_in_trend" in csv_text
    prov = c.get(f"/api/analysis/jobs/{jid}/artifacts/exports/provenance.json").json()
    assert prov["fdr"]["n_hypotheses"] == sp["summary"]["n_hypotheses"] and len(prov["request_manifest"]) == 2
    # work checkpoints are removed after publication; the shared tile cache stays
    store = get_store()
    assert not store.exists(f"jobs/{jid}/work") and store.exists(f"jobs/{jid}/result/manifest.json")
    assert all(store.verify(store.blob_ref(t.blob_sha256), t.blob_sha256) for t in env.tiles(jid))


def test_results_are_refused_until_the_job_is_complete(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    r = c.get(f"/api/analysis/jobs/{jid}/results")
    assert r.status_code == 409 and r.json()["error"] == "JOB_NOT_READY"


def test_progress_is_monotonic_and_reaches_100_only_after_publication(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    seen = []
    orig = jp.JobContext._write

    def spy(self, values, statuses=(JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)):
        if "progress_pct" in values:
            seen.append((values["progress_pct"], values.get("status")))
        return orig(self, values, statuses)

    jp.JobContext._write = spy
    try:
        env.run(jid)
    finally:
        jp.JobContext._write = orig
    pcts = [p for p, _ in seen]
    assert pcts == sorted(pcts) and pcts[-1] == 100
    assert all(p < 100 for p, s in seen if s != JobStatus.COMPLETED)


# --------------------------------------------------------------------------- #
# F. Scientific equality: synchronous == background == resumed
# --------------------------------------------------------------------------- #

def _sync_results(method="mann_kendall", correction="fdr_bh", alpha=0.05):
    s = get_settings()
    a = aa.area_from_request(None, AREA, "Test area", s)
    q = ran.RegionalQuery(get_variable("T2M"), a.bbox, START, END, 0.8, a)
    client = NasaPowerClient(s, session=TileSession(value_fn))
    reg = ran.build_regional_response(q, client, s, analyze=True)
    sp = sta.build_spatial_response(q, client, s, method, correction, alpha)
    return norm(reg), norm(sp)


def _compare(sync_reg, sync_sp, bg_reg, bg_sp):
    for k in ("monthly", "annual", "summary", "cells", "cell_years", "statistics", "warnings", "interpretation"):
        same(sync_reg[k], bg_reg[k], f"regional.{k}")
    for k in ("n_cells_used", "n_tiles", "n_duplicates", "polygon_area_km2", "aggregation_method", "grid_representability",
              "returned_extent", "units_raw", "geometry_id", "n_cells_returned", "n_cells_outside"):
        same(sync_reg["metadata"][k], bg_reg["metadata"][k], f"metadata.{k}")
    for k in ("cells", "summary", "config", "regional_aggregate", "years", "available", "interpretation", "warnings"):
        same(sync_sp[k], bg_sp[k], f"spatial.{k}")


def test_background_results_equal_synchronous_results_exactly(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    bg_reg = c.get(f"/api/analysis/jobs/{jid}/results").json()
    bg_sp = c.get(f"/api/analysis/jobs/{jid}/spatial").json()
    sync_reg, sync_sp = _sync_results()
    # compare through the same response models the API uses
    from app.models.regional_schemas import RegionalAnalysisResponse
    from app.models.spatial_trend_schemas import SpatialTrendResponse

    sync_reg = norm(RegionalAnalysisResponse.model_validate(sync_reg).model_dump(mode="json"))
    sync_sp = norm(SpatialTrendResponse.model_validate(sync_sp).model_dump(mode="json"))
    _compare(sync_reg, sync_sp, bg_reg, bg_sp)
    # other test / correction recomputed from stored p-values over the complete family
    sync_reg2, sync_sp2 = _sync_results("hamed_rao_canonical", "fdr_by", 0.1)
    bg_sp2 = c.get(f"/api/analysis/jobs/{jid}/spatial", params={"method": "hamed_rao_canonical", "correction": "fdr_by", "alpha": 0.1}).json()
    sync_sp2 = norm(SpatialTrendResponse.model_validate(sync_sp2).model_dump(mode="json"))
    for k in ("cells", "summary", "config"):
        same(sync_sp2[k], bg_sp2[k], f"spatial2.{k}")
    fam = [x for x in bg_sp2["cells"] if x["in_family"]]
    ref = multipletests([x["raw_p_value"] for x in fam], method="fdr_by")[1]
    assert [x["adjusted_p_value"] for x in fam] == pytest.approx(list(ref), rel=1e-12)


def test_resumed_job_after_crash_during_statistics_matches_and_reuses_checkpoints(env, monkeypatch):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    calls = {"n": 0}
    orig = sta.compute_cell_rows

    def crashing(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return orig(*a, **kw)

    monkeypatch.setattr(sta, "compute_cell_rows", crashing)
    with pytest.raises(Crash):
        env.run(jid)
    j = env.job(jid)
    assert j.status == "RUNNING" and j.stage == "RUNNING_STATISTICS" and sum(k.startswith("chunk:") for k in j.checkpoints) == 2
    # the reconciler notices the expired lease and requeues the job
    env.expire_lease(jid)
    out = jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)
    assert out["recovered_orphans"] == 1 and env.job(jid).status == "RETRYING"
    out = jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)
    assert out["enqueued_retry"] == 1 and env.job(jid).status == "QUEUED"
    session = TileSession(value_fn)
    calls["n"] = -1000
    assert env.run(jid, session=session) == "completed"
    assert session.calls == []                                   # no NASA tile downloaded again
    n_chunks = math.ceil(env.job(jid).cells_total / 37)
    assert calls["n"] == -1000 + (n_chunks - 2)                  # only the missing chunks were computed
    j = env.job(jid)
    assert j.attempt_count == 2 and j.status == "COMPLETED"
    sync_reg, sync_sp = _sync_results()
    from app.models.regional_schemas import RegionalAnalysisResponse
    from app.models.spatial_trend_schemas import SpatialTrendResponse

    _compare(norm(RegionalAnalysisResponse.model_validate(sync_reg).model_dump(mode="json")),
             norm(SpatialTrendResponse.model_validate(sync_sp).model_dump(mode="json")),
             c.get(f"/api/analysis/jobs/{jid}/results").json(), c.get(f"/api/analysis/jobs/{jid}/spatial").json())


# --------------------------------------------------------------------------- #
# B. Durability
# --------------------------------------------------------------------------- #

def test_worker_crash_during_download_resumes_without_refetching_verified_tiles(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    st = get_settings().model_copy(update={"nasa_global_max_concurrency": 1})
    crash_session = TileSession(value_fn, fail=lambda n, p: Crash() if n == 2 else None)
    with pytest.raises(Crash):
        env.run(jid, session=crash_session, settings=st)
    tiles = env.tiles(jid)
    assert [t.status for t in tiles].count(TileStatus.VERIFIED) == 1
    env.expire_lease(jid)
    jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)
    jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)
    fresh = TileSession(value_fn)
    assert env.run(jid, session=fresh, worker="w2") == "completed"
    assert len(fresh.calls) == 1                                  # only the unverified tile
    ev = [e.message for e in _events(env, jid)]
    assert any("stopped sending heartbeats" in m for m in ev) and any("already verified" in m for m in ev)


def _events(env, jid):
    with env.sm() as s:
        return list(s.scalars(select(JobEvent).where(JobEvent.job_id == jid).order_by(JobEvent.id)))


def test_api_restart_keeps_jobs_and_frontend_can_reconnect(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    cookies = dict(c.cookies)
    # "restart": drop every in-process cache and connection pool, new client with the same browser cookies
    get_engine().dispose()
    for f in (get_engine, get_sessionmaker, get_store):
        f.cache_clear()
    from app.jobs import results as jr

    jr._cache.clear()
    c2 = TestClient(app, cookies=cookies)
    assert c2.get(f"/api/analysis/jobs/{jid}").json()["status"] == "COMPLETED"
    assert c2.get(f"/api/analysis/jobs/{jid}/results").status_code == 200


def test_crash_after_publication_does_not_publish_twice(env, monkeypatch):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    orig = jp.complete_job
    monkeypatch.setattr(jp, "complete_job", lambda *a, **k: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        env.run(jid)
    store = get_store()
    first = store.path(f"jobs/{jid}/result/manifest.json").read_bytes()
    monkeypatch.setattr(jp, "complete_job", orig)
    env.expire_lease(jid)
    jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)
    session = TileSession(value_fn)
    assert env.run(jid, session=session) == "completed" and session.calls == []
    assert store.path(f"jobs/{jid}/result/manifest.json").read_bytes() == first
    assert any("already been published" in e.message for e in _events(env, jid))
    assert not list(store.path(f"jobs/{jid}").glob("staging-*"))


def test_duplicate_delivery_only_one_worker_claims(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    st = get_settings()
    assert jp.claim(env.sm, jid, "a:1:1", st) is True
    assert jp.claim(env.sm, jid, "b:1:1", st) is False            # lease still valid
    env.expire_lease(jid)
    assert jp.claim(env.sm, jid, "b:1:1", st) is True             # orphan takeover
    ctx = jp.JobContext(jid, "a:1:1", st, env.sm, get_store(), None)
    with pytest.raises(jp.LeaseLost):                              # the old worker can no longer write
        ctx.set_stage("PREPARING_GEOMETRY", "x")
    env.set(jid, status="QUEUED", lease_owner=None, lease_expires_at=None)
    assert env.run(jid) == "completed"
    assert env.run(jid, worker="w9") == "not_claimable"


def test_outbox_job_survives_queue_outage(env):
    c, h = client_for()
    env.enqueue_fail = True
    r = submit(c, h)
    assert r.status_code == 202 and r.json()["status"] == "PENDING"
    jid = r.json()["job_id"]
    assert jrec.reconcile_once(env.sm, get_settings(), get_store())["enqueued_pending"] == 0   # too recent; still down
    env.enqueue_fail = False
    env.set(jid, updated_at=utcnow() - timedelta(minutes=5))
    assert jrec.reconcile_once(env.sm, get_settings(), get_store())["enqueued_pending"] == 1
    assert env.job(jid).status == "QUEUED" and env.enqueued == [jid]


def test_lost_queue_message_is_requeued(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.set(jid, queued_at=utcnow() - timedelta(hours=1))
    assert jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: "queued")["requeued_lost"] == 0
    assert jrec.reconcile_once(env.sm, get_settings(), get_store(), rq_state=lambda _: None)["requeued_lost"] == 1
    assert len(env.enqueued) == 2


def test_repeated_worker_loss_fails_with_checkpoints_kept(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.set(jid, status="RUNNING", lease_owner="x", lease_expires_at=utcnow() - timedelta(seconds=1), auto_attempts=3)
    assert jrec.reconcile_once(env.sm, get_settings(), get_store())["failed_orphans"] == 1
    j = env.job(jid)
    assert j.status == "FAILED" and j.error_code == "WORKER_LOST" and j.error_retryable


def test_redis_outage_at_worker_start_is_a_transient_failure(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]

    def down():
        raise ConnectionError("redis unreachable")

    st = get_settings()
    out = jp.execute(jid, "w:1:1", st, env.sm, get_store(), down, lambda: None)
    assert out == "retrying" and env.job(jid).status == "RETRYING" and env.job(jid).error_code == "INFRASTRUCTURE_UNAVAILABLE"


def test_database_outage_is_retried_then_succeeds():
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 3:
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))
        return "ok"

    assert with_db_retry(flaky, tolerance_seconds=30, sleep=lambda s: None) == "ok" and n["i"] == 3
    with pytest.raises(OperationalError):
        with_db_retry(lambda: (_ for _ in ()).throw(OperationalError("x", {}, Exception("down"))), tolerance_seconds=0, sleep=lambda s: None)


def test_storage_full_during_publication_never_publishes(env, monkeypatch):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    store = get_store()
    orig = ArtifactStore.write_bytes

    def full(self, rel, data):
        if "/staging-" in rel and rel.endswith("cells.json.gz"):
            raise StorageFullError("disk full")
        return orig(self, rel, data)

    monkeypatch.setattr(ArtifactStore, "write_bytes", full)
    assert env.run(jid) == "retrying"
    j = env.job(jid)
    assert j.status == "RETRYING" and j.error_code == "STORAGE_FULL" and j.result_ref is None
    assert not store.exists(f"jobs/{jid}/result")
    monkeypatch.setattr(ArtifactStore, "write_bytes", orig)
    env.set(jid, next_attempt_at=None)
    assert env.run(jid) == "completed"


def test_per_job_storage_budget_is_enforced(env, monkeypatch):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    st = get_settings().model_copy(update={"job_max_storage_mb": 0})
    assert env.run(jid, settings=st) == "failed"
    j = env.job(jid)
    assert j.error_code == "STORAGE_BUDGET_EXCEEDED" and not get_store().exists(f"jobs/{jid}/result")


# --------------------------------------------------------------------------- #
# C. Idempotency & duplicates
# --------------------------------------------------------------------------- #

def test_double_click_returns_the_same_job(env):
    c, h = client_for()
    a, b = submit(c, h), submit(c, h)
    assert a.status_code == 202 and b.status_code == 200
    assert b.json()["job_id"] == a.json()["job_id"] and b.json()["duplicate_of_reason"] == "active_duplicate"
    assert len(env.enqueued) == 1


def test_idempotency_key_and_completed_duplicates(env):
    c, h = client_for()
    a = submit(c, h, idem="k1")
    assert submit(c, h, idem="k1").json()["duplicate_of_reason"] in ("idempotency_key", "active_duplicate")
    r = submit(c, h, idem="k1", end_year=END - 1)
    assert r.status_code == 409 and r.json()["error"] == "IDEMPOTENCY_KEY_REUSED"
    env.run(a.json()["job_id"])
    again = submit(c, h)
    assert again.status_code == 200 and again.json()["duplicate_of_reason"] == "completed_duplicate"
    fresh = submit(c, h, force_new=True)
    assert fresh.status_code == 202 and fresh.json()["job_id"] != a.json()["job_id"]


def test_database_rejects_two_active_jobs_with_the_same_configuration(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    j = env.job(jid)
    with env.sm() as s:
        clone = AnalysisJob(**{k: getattr(j, k) for k in AnalysisJob.__table__.columns.keys() if k != "id"}, id="00000000-0000-4000-8000-000000000000")
        s.add(clone)
        with pytest.raises(IntegrityError):
            s.commit()


def test_different_sessions_never_share_jobs(env):
    c1, h1 = client_for()
    c2, h2 = client_for()
    a, b = submit(c1, h1).json()["job_id"], submit(c2, h2).json()["job_id"]
    assert a != b


# --------------------------------------------------------------------------- #
# D. NASA retrieval
# --------------------------------------------------------------------------- #

class StatusSession(TileSession):
    """Returns given HTTP statuses for the first calls, then real tiles."""

    def __init__(self, statuses, headers=None):
        super().__init__(value_fn)
        self.statuses, self.hdrs = list(statuses), headers or {}

    def get(self, url, params=None, timeout=None):
        if self.statuses:
            code = self.statuses.pop(0)
            self.calls.append(dict(params))
            hdrs = self.hdrs

            class Resp:
                status_code = code
                headers = hdrs

                def json(self_inner):
                    if code == 422:
                        return {"messages": ["Latitude out of range"]}
                    raise ValueError("html")

            return Resp()
        return super().get(url, params, timeout)


def test_transient_429_and_503_are_retried_with_backoff(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    session = StatusSession([429, 503], headers={"Retry-After": "0"})
    assert env.run(jid, session=session) == "completed"
    assert len(session.calls) == 4
    msgs = [e.message for e in _events(env, jid)]
    assert sum("retrying in" in m for m in msgs) == 2
    assert max(t.attempts for t in env.tiles(jid)) >= 2


def test_retry_after_header_is_respected():
    st = get_settings()
    assert jp._backoff(st, 0, 30.0) >= 30.0
    assert jp._backoff(st, 0, None) <= st.job_tile_backoff_seconds


def test_exhausted_tile_fails_job_and_manual_retry_fetches_only_that_tile(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    tiles = plan_tiles([(o.i, o.j) for o in ag.cell_overlaps(aa.area_from_request(None, AREA, "x", get_settings()).geometry, ag.MERRA2_GRID)],
                       ag.MERRA2_GRID)
    bad = tiles[1]
    always = TileSession(value_fn, fail=lambda n, p: requests.ConnectionError("down")
                         if float(p["longitude-min"]) == bad.lon_min else None)
    st = get_settings().model_copy(update={"job_max_attempts": 1, "job_tile_max_attempts": 3})
    assert env.run(jid, session=always, settings=st) == "failed"
    j = env.job(jid)
    assert j.status == "FAILED" and j.error_code == "INCOMPLETE_TILE_RETRIEVAL" and j.error_retryable
    assert [t.status for t in env.tiles(jid)] == [TileStatus.VERIFIED, TileStatus.FAILED]
    r = c.post(f"/api/analysis/jobs/{jid}/retry", headers=h)
    assert r.status_code == 200 and r.json()["resumable"]["verified_tiles"] == 1
    assert env.job(jid).status == "QUEUED"
    healthy = TileSession(value_fn)
    assert env.run(jid, session=healthy) == "completed" and len(healthy.calls) == 1


def test_invalid_input_errors_are_not_retried(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    assert env.run(jid, session=StatusSession([422, 422])) == "failed"
    j = env.job(jid)
    assert j.error_code == "LOCATION_NOT_SUPPORTED" and j.error_retryable is False and j.auto_attempts == 1
    r = c.post(f"/api/analysis/jobs/{jid}/retry", headers=h)
    assert r.status_code == 409 and "new analysis" in r.json()["message"]


def test_html_error_page_is_never_stored_as_data(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    session = StatusSession([200])   # 200 with an HTML body -> JSON decode fails -> invalid response
    assert env.run(jid, session=session) == "completed"
    assert any("NASA_API_UNAVAILABLE" in json.dumps(e.data or {}) or "retrying" in e.message for e in _events(env, jid))


def _payload(features, params=None):
    return {"features": features, "parameters": params or {"T2M": {"units": "C"}},
            "header": {"fill_value": -999.0, "sources": ["MERRA2"], "api": {"version": "v2"}}}


def _f(lat, lon, series, param="T2M"):
    return {"geometry": {"coordinates": [lon, lat]}, "properties": {"parameter": {param: series}}}


FULL = {f"2001{m:02d}": 20.0 for m in range(1, 13)}


def test_tile_validation_rejects_malformed_payloads():
    v, t, G = get_variable("T2M"), Tile("T01", 6, 8, 79, 81, 1), ag.MERRA2_GRID
    ok = validate_tile_payload(_payload([_f(7.0, 80.0, {**FULL, "200105": -999.0})]), v, t, 2001, 2001, G)
    assert ok["n_features"] == 1 and ok["n_missing_values"] == 1 and ok["units"] == "C"
    cases = [
        ("not a JSON object", "<html>"),
        ("no grid cells", _payload([])),
        ("parameters", _payload([_f(7.0, 80.0, FULL)], {"T2M": {}, "RH2M": {}})),
        ("wrong parameter", _payload([_f(7.0, 80.0, FULL, "RH2M")])),
        ("not on the", _payload([_f(7.1, 80.0, FULL)])),
        ("outside the requested box", _payload([_f(9.0, 80.0, FULL)])),
        ("absent", _payload([_f(7.0, 80.0, {k: v_ for k, v_ in FULL.items() if k != "200107"})])),
    ]
    for msg, p in cases:
        with pytest.raises(NasaPowerResponseError, match=msg):
            validate_tile_payload(p, v, t, 2001, 2001, G)
    # the current (incomplete) year may lack months
    validate_tile_payload(_payload([_f(7.0, 80.0, FULL)]), v, t, 2001, 2002, G, latest_partial_year=2002)


def test_verified_tiles_are_shared_between_jobs_of_different_users(env):
    c1, h1 = client_for()
    c2, h2 = client_for()
    j1 = submit(c1, h1).json()["job_id"]
    env.run(j1)
    j2 = submit(c2, h2).json()["job_id"]
    s2 = TileSession(value_fn)
    assert env.run(j2, session=s2) == "completed" and s2.calls == []
    assert all(t.from_cache for t in env.tiles(j2))
    assert c2.get(f"/api/analysis/jobs/{j1}").status_code == 404        # sharing raw NASA tiles never shares jobs


def test_global_nasa_concurrency_holds_across_workers():
    r = fakeredis.FakeRedis()
    workers = [GlobalNasaLimiter(r, 3, 60, 0, poll=0.001) for _ in range(4)]   # four worker processes
    active, peak, lock = [0], [0], threading.Lock()

    def request(lim):
        with lim.slot():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.01)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=request, args=(workers[i % 4],)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 3 and workers[0].in_use() == 0


def test_crashed_slot_holder_frees_its_slot_after_the_lease():
    r = fakeredis.FakeRedis()
    lim = GlobalNasaLimiter(r, 1, 0.2, 0, poll=0.01)
    assert lim.try_acquire("dead-worker")
    assert not lim.try_acquire("other")
    time.sleep(0.25)
    assert lim.try_acquire("other")


def test_request_start_rate_is_limited_globally():
    r = fakeredis.FakeRedis()
    a, b = GlobalNasaLimiter(r, 5, 60, 0.05, poll=0.001), GlobalNasaLimiter(r, 5, 60, 0.05, poll=0.001)
    starts = []
    for lim in (a, b, a, b):
        with lim.slot():
            starts.append(time.monotonic())
    gaps = np.diff(starts)
    assert (gaps >= 0.045).all()


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #

def test_cancel_queued_job(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    r = c.post(f"/api/analysis/jobs/{jid}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert env.run(jid) == "not_claimable"
    assert submit(c, h).json()["created"] is True               # a cancelled job does not block resubmission


def test_cancel_running_job_stops_cooperatively_and_keeps_shared_tiles(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    st = get_settings().model_copy(update={"nasa_global_max_concurrency": 1})

    def on_call(n, p):
        if n == 1:
            assert c.post(f"/api/analysis/jobs/{jid}/cancel", headers=h).json()["status"] == "CANCEL_REQUESTED"
            time.sleep(0.3)   # let the heartbeat pick it up
        return None

    session = TileSession(value_fn, fail=on_call)
    assert env.run(jid, session=session, settings=st) == "cancelled"
    j = env.job(jid)
    assert j.status == "CANCELLED" and j.result_ref is None and len(session.calls) == 1
    t = [x for x in env.tiles(jid) if x.status == TileStatus.VERIFIED]
    assert len(t) == 1 and get_store().verify(get_store().blob_ref(t[0].blob_sha256), t[0].blob_sha256)
    r = c.post(f"/api/analysis/jobs/{jid}/retry", headers=h)
    assert r.status_code == 200 and r.json()["resumable"]["verified_tiles"] == 1


def test_completed_job_cannot_be_cancelled(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    r = c.post(f"/api/analysis/jobs/{jid}/cancel", headers=h)
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# Expiry, boundary versions
# --------------------------------------------------------------------------- #

def test_expired_results_are_deleted_and_reported(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    env.set(jid, expires_at=utcnow() - timedelta(seconds=1))
    assert jrec.reconcile_once(env.sm, get_settings(), get_store(), gc_tiles=True)["expired"] == 1
    assert env.job(jid).status == "EXPIRED" and not get_store().exists(f"jobs/{jid}")
    r = c.get(f"/api/analysis/jobs/{jid}/results")
    assert r.status_code == 410 and r.json()["error"] == "JOB_EXPIRED"


def test_country_retry_refuses_a_changed_boundary_version(env, monkeypatch):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.set(jid, area_kind="country", iso3="LKA", boundary_version="gbOpen commit OLD", status="FAILED",
            error_code="INCOMPLETE_TILE_RETRIEVAL", error_retryable=True, active_dedupe_key=None)
    r = c.post(f"/api/analysis/jobs/{jid}/retry", headers=h)
    assert r.status_code == 409 and "boundary" in r.json()["message"]


# --------------------------------------------------------------------------- #
# E. Resource budgets
# --------------------------------------------------------------------------- #

def _pf(cells, tiles, months=300):
    return {"n_cells": cells, "n_tiles": tiles, "n_values": cells * months, "n_months": months}


@pytest.mark.parametrize("cells,tiles,tier,eligible", [
    (30, 1, "SMALL", True), (2462, 19, "SMALL", True), (4089, 44, "MEDIUM", True), (11182, 72, "LARGE", True),
    (25000, 160, "VERY_LARGE", False), (0, 0, "BLOCKED", False),
])
def test_resource_tiers(cells, tiles, tier, eligible):
    st = get_settings()
    pf = _pf(cells, tiles)
    est = jres.estimate_resources(pf, None, st)
    out = jres.classify(pf, est, st)
    assert (out["tier"], out["eligible"]) == (tier, eligible)
    if tier == "VERY_LARGE":
        big = st.model_copy(update={"job_allow_very_large": True, "job_daily_tile_budget_per_session": 1000, "job_max_storage_mb": 4096})
        assert jres.classify(pf, jres.estimate_resources(pf, None, big), big)["eligible"]


def test_estimated_memory_above_the_worker_budget_is_very_large():
    st = get_settings().model_copy(update={"job_max_memory_mb": 300})
    pf = _pf(11182, 72)
    out = jres.classify(pf, jres.estimate_resources(pf, None, st), st)
    assert out["tier"] == "VERY_LARGE" and not out["eligible"]


def test_preflight_endpoint_reports_tier_and_estimates(env):
    c, _ = client_for()
    r = c.post("/api/analysis/preflight", json=body())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["background"]["tier"] == "SMALL" and d["background"]["eligible"] and d["preflight"]["n_tiles"] == 2
    assert d["background"]["estimates"]["basis"].startswith("static benchmark") and len(d["background"]["stages"]) == 10


def test_oversized_and_over_budget_submissions_are_rejected(env, monkeypatch):
    c, h = client_for()
    monkeypatch.setenv("EARTHSCOPE_JOB_LARGE_MAX_CELLS", "50")
    monkeypatch.setenv("EARTHSCOPE_JOB_MEDIUM_MAX_CELLS", "40")
    monkeypatch.setenv("EARTHSCOPE_POLYGON_MAX_CELLS", "30")
    get_settings.cache_clear()
    r = submit(c, h)
    assert r.status_code == 422 and r.json()["error"] == "ANALYSIS_TOO_LARGE"
    assert env.enqueued == []


def test_session_limits(env, monkeypatch):
    monkeypatch.setenv("EARTHSCOPE_JOB_MAX_ACTIVE_PER_SESSION", "1")
    get_settings.cache_clear()
    c, h = client_for()
    assert submit(c, h).status_code == 202
    r = submit(c, h, end_year=END - 1)
    assert r.status_code == 429 and r.json()["error"] == "JOB_LIMIT_EXCEEDED"
    monkeypatch.setenv("EARTHSCOPE_JOB_MAX_ACTIVE_PER_SESSION", "5")
    monkeypatch.setenv("EARTHSCOPE_JOB_DAILY_TILE_BUDGET_PER_SESSION", "3")
    get_settings.cache_clear()
    r = submit(c, h, end_year=END - 2)
    assert r.status_code == 429 and "daily budget" in r.json()["message"]


def test_global_active_limit(env, monkeypatch):
    monkeypatch.setenv("EARTHSCOPE_JOB_MAX_GLOBAL_ACTIVE", "1")
    get_settings.cache_clear()
    c1, h1 = client_for()
    c2, h2 = client_for()
    assert submit(c1, h1).status_code == 202
    assert submit(c2, h2).status_code == 429


# --------------------------------------------------------------------------- #
# G. Security
# --------------------------------------------------------------------------- #

def test_jobs_are_private_to_their_session(env):
    c1, h1 = client_for()
    c2, h2 = client_for()
    jid = submit(c1, h1).json()["job_id"]
    env.run(jid)
    for path in ("", "/progress", "/results", "/spatial", "/artifacts", "/artifacts/exports/annual.csv"):
        r = c2.get(f"/api/analysis/jobs/{jid}{path}")
        assert r.status_code == 404 and r.json()["error"] == "JOB_NOT_FOUND", path
    assert c2.post(f"/api/analysis/jobs/{jid}/cancel", headers=h2).status_code == 404
    assert c2.post(f"/api/analysis/jobs/{jid}/retry", headers=h2).status_code == 404
    assert c2.get("/api/analysis/jobs").json()["jobs"] == []
    assert [j["job_id"] for j in c1.get("/api/analysis/jobs").json()["jobs"]] == [jid]


def test_session_and_csrf_are_required(env):
    anon = TestClient(app)
    assert anon.get("/api/analysis/jobs").status_code == 401
    assert anon.post("/api/analysis/jobs", json=body()).status_code == 401
    c, h = client_for()
    r = c.post("/api/analysis/jobs", json=body())                        # no CSRF header
    assert r.status_code == 403 and r.json()["error"] == "CSRF_CHECK_FAILED"
    r = c.post("/api/analysis/jobs", json=body(), headers={"X-CSRF-Token": "x" * 43})
    assert r.status_code == 403
    r = c.post("/api/analysis/jobs", json=body(), headers={**h, "Origin": "https://evil.example"})
    assert r.status_code == 403
    bad = TestClient(app, cookies={"es_session": "not a token!"})
    assert bad.get("/api/analysis/jobs").status_code == 401


def test_malformed_ids_geometries_and_payloads(env):
    c, h = client_for()
    for jid in ("1", "../../etc/passwd", "00000000-0000-4000-8000-00000000000g", "x" * 300):
        assert c.get(f"/api/analysis/jobs/{jid}").status_code == 404
    r = submit(c, h, geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]})
    assert r.status_code == 422 and r.json()["error"] == "INVALID_GEOMETRY"
    r = c.post("/api/analysis/jobs", content=b"{" + b" " * 3_100_000 + b"}",
               headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"] == "GEOMETRY_TOO_COMPLEX"
    r = submit(c, h, method="t_test")
    assert r.status_code == 422


def test_ops_summary_requires_a_token(env, monkeypatch):
    c, _ = client_for()
    assert c.get("/api/analysis/ops").status_code == 403
    monkeypatch.setenv("EARTHSCOPE_OPS_TOKEN", "s3cret-token")
    get_settings.cache_clear()
    assert c.get("/api/analysis/ops", headers={"X-Ops-Token": "wrong"}).status_code == 403
    assert c.get("/api/analysis/ops", headers={"X-Ops-Token": "s3cret-token"}).json()["jobs_by_status"] == {}


# --------------------------------------------------------------------------- #
# Large-map viewport
# --------------------------------------------------------------------------- #

def test_viewport_filter_never_changes_the_fdr_family(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    full = c.get(f"/api/analysis/jobs/{jid}/spatial").json()
    part = c.get(f"/api/analysis/jobs/{jid}/spatial", params={"lat_min": 6, "lat_max": 9, "lon_min": 70, "lon_max": 74}).json()
    assert 0 < len(part["cells"]) < len(full["cells"])
    assert part["summary"] == full["summary"]
    by_id = {x["id"]: x for x in full["cells"]}
    assert all(x["adjusted_p_value"] == by_id[x["id"]]["adjusted_p_value"] for x in part["cells"])
    assert c.get(f"/api/analysis/jobs/{jid}/spatial", params={"lat_min": 6}).status_code == 422


def test_artifacts_stored_compressed_and_checksummed(env):
    c, h = client_for()
    jid = submit(c, h).json()["job_id"]
    env.run(jid)
    store = get_store()
    man = json.loads(store.path(f"jobs/{jid}/result/manifest.json").read_bytes())
    for name, f in man["files"].items():
        assert store.verify(f"jobs/{jid}/result/{name}", f["sha256"]), name
    p = store.path(f"jobs/{jid}/result/regional.json.gz")
    raw = bytearray(p.read_bytes())
    raw[-10] ^= 0xFF
    p.write_bytes(bytes(raw))
    from app.jobs import results as jr

    jr._cache.clear()
    r = c.get(f"/api/analysis/jobs/{jid}/results")
    assert r.status_code == 503 and r.json()["error"] == "ARTIFACT_CORRUPT"     # a tampered file is never served
    assert json.loads(gzip.decompress(store.path(f"jobs/{jid}/result/cells.json.gz").read_bytes()))["cells"]
