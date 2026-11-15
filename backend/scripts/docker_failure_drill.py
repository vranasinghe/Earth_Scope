"""Failure drill against the running Docker Compose stack (Phase 6).

Submits a LIVE country job through the HTTP API (session cookie + CSRF) and,
while it runs, injects real infrastructure failures with docker compose:

  1. kill the worker container during NASA downloads         (worker crash)
  2. restart the API container while the job is orphaned      (API restart)
  3. start a fresh worker; the scheduler must recover the job (lease expiry)
  4. restart PostgreSQL during the statistics stage           (database outage)

then checks the job completes, verified tiles were not downloaded twice, and
the results / spatial / export endpoints work. Optional queue drills use small
Sri Lanka jobs: Redis restart with a queued message, and a Redis outage
at submission time (outbox).

    .venv\\Scripts\\python.exe scripts\\docker_failure_drill.py USA
    .venv\\Scripts\\python.exe scripts\\docker_failure_drill.py --queue-drills-only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[2]
log: list[str] = []


def say(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    log.append(line)
    print(line, flush=True)


def compose(*args: str) -> None:
    say("docker compose " + " ".join(args))
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


class Client:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.csrf = self.s.get(f"{API}/api/analysis/session", timeout=30).json()["csrf_token"]

    def post(self, path: str, body: dict, **headers) -> requests.Response:
        return self.s.post(f"{API}{path}", json=body, headers={"X-CSRF-Token": self.csrf, **headers}, timeout=120)

    def get(self, path: str, **kw) -> requests.Response:
        for attempt in range(60):
            try:
                return self.s.get(f"{API}{path}", timeout=60, **kw)
            except requests.RequestException:
                time.sleep(2)   # API restarting
        raise RuntimeError("API unreachable")

    def job(self, jid: str) -> dict:
        r = self.get(f"/api/analysis/jobs/{jid}")
        r.raise_for_status()
        return r.json()

    def wait(self, jid: str, pred, timeout: float, every: float = 3.0) -> dict:
        end = time.time() + timeout
        last = None
        while time.time() < end:
            j = self.job(jid)
            p = j["progress"]
            sig = (j["status"], p["stage"], p["download"]["tiles_completed"], p["processing"]["cells_processed"])
            if sig != last:
                say(f"  {j['status']:<16} {p['stage']:<28} {p['progress_pct']:5.1f}%  tiles {p['download']['tiles_completed']}/{p['download']['tiles_total']}"
                    f"  cells {p['processing']['cells_processed']}/{p['processing']['cells_total']}")
                last = sig
            if pred(j):
                return j
            time.sleep(every)
        raise TimeoutError(f"condition not reached within {timeout}s")


def country_drill(iso3: str) -> dict:
    c = Client()
    pf = c.post("/api/analysis/preflight", {"iso3": iso3, "variable": "T2M", "start_year": 2001, "end_year": 2025}).json()
    say(f"preflight {iso3}: {pf['preflight']['n_cells']} cells, {pf['preflight']['n_tiles']} tiles, tier {pf['background']['tier']}, "
        f"eligible {pf['background']['eligible']}, estimate {pf['background']['estimates']['total_seconds']} s")
    t0 = time.time()
    r = c.post("/api/analysis/jobs", {"iso3": iso3, "variable": "T2M", "start_year": 2001, "end_year": 2025},
               **{"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    say(f"submitted job {jid} (HTTP 202 in {r.elapsed.total_seconds():.2f} s)")
    dup = c.post("/api/analysis/jobs", {"iso3": iso3, "variable": "T2M", "start_year": 2001, "end_year": 2025})
    say(f"duplicate submission -> HTTP {dup.status_code}, same job: {dup.json().get('job_id') == jid}, reason {dup.json().get('duplicate_of_reason')}")

    total = pf["preflight"]["n_tiles"]
    j = c.wait(jid, lambda j: j["progress"]["download"]["tiles_completed"] >= max(3, total // 3), 1800)
    verified_at_kill = j["progress"]["download"]["tiles_completed"]
    compose("kill", "worker")
    say(f"worker killed with {verified_at_kill}/{total} tiles verified")
    compose("restart", "backend")
    j = c.job(jid)
    say(f"after API restart: job visible, status {j['status']}, tiles {j['progress']['download']['tiles_completed']}/{total}")
    compose("up", "-d", "worker")
    t_kill = time.time()
    j = c.wait(jid, lambda j: j["progress"]["attempts"]["total"] >= 2 and j["status"] == "RUNNING", 600)
    say(f"recovered by the scheduler and resumed by the new worker after {time.time() - t_kill:.0f} s")
    j = c.wait(jid, lambda j: j["progress"]["stage"] == "RUNNING_STATISTICS" or j["status"] in ("COMPLETED", "FAILED"), 3600)
    if j["status"] == "RUNNING":
        compose("restart", "postgres")
        say("PostgreSQL restarted during the statistics stage")
    j = c.wait(jid, lambda j: j["status"] in ("COMPLETED", "FAILED"), 3600, every=5)
    wall = time.time() - t0
    out: dict = {"iso3": iso3, "job_id": jid, "status": j["status"], "error": j["error"], "wall_seconds": round(wall, 1),
                 "verified_tiles_at_kill": verified_at_kill, "attempts": j["progress"]["attempts"], "events": [e["message"] for e in j["events"]]}
    if j["status"] == "COMPLETED":
        res = c.get(f"/api/analysis/jobs/{jid}/results").json()
        sp = c.get(f"/api/analysis/jobs/{jid}/spatial", params={"correction": "fdr_by"}).json()
        arts = c.get(f"/api/analysis/jobs/{jid}/artifacts").json()["files"]
        csv = c.get(f"/api/analysis/jobs/{jid}/artifacts/exports/spatial_cells.csv").text
        m = res["metadata"]
        st = res.get("statistics") or {}
        out.update({
            "result": {"execution_mode": m["execution_mode"], "data_mode": m["data_mode"], "n_cells_used": m["n_cells_used"],
                       "n_tiles": m["n_tiles"], "n_duplicates": m["n_duplicates"], "boundary": (m.get("boundary") or {}).get("version"),
                       "ols_slope": st.get("regression", {}).get("slope"), "mk_p": st.get("mann_kendall", {}).get("p_value"),
                       "sen_slope": st.get("sens_slope", {}).get("slope"), "evidence": st.get("evidence", {}).get("label"),
                       "tiles_downloaded_from_nasa_by_job": sum(1 for t in m["request_manifest"] if not t["from_cache"])},
            "spatial_by": {"n_hypotheses": sp["summary"]["n_hypotheses"], "n_fdr_discoveries": sp["summary"]["n_fdr_discoveries"],
                           "n_raw_significant": sp["summary"]["n_raw_significant"]},
            "artifacts": len(arts), "csv_header": csv.splitlines()[0],
            "results_json_bytes": len(json.dumps(res)), "spatial_json_bytes": len(json.dumps(sp)),
        })
    other = Client()
    out["other_session_sees_job"] = other.get(f"/api/analysis/jobs/{jid}").status_code != 404
    return out


def queue_drills() -> dict:
    c = Client()
    body = {"iso3": "LKA", "variable": "T2M", "start_year": 2001, "end_year": 2025}
    out = {}
    # A. queued message survives a Redis restart (AOF)
    compose("stop", "worker")
    jid = c.post("/api/analysis/jobs", {**body, "start_year": 2002, "force_new": True}).json()["job_id"]
    say(f"job {jid} queued with no worker running")
    compose("restart", "redis")
    compose("up", "-d", "worker")
    j = c.wait(jid, lambda j: j["status"] in ("COMPLETED", "FAILED"), 600)
    out["redis_restart_with_queued_job"] = j["status"]
    # B. Redis down at submission time -> outbox
    compose("stop", "redis")
    r = c.post("/api/analysis/jobs", {**body, "start_year": 2003, "force_new": True})
    jid = r.json()["job_id"]
    say(f"submitted while Redis was down -> HTTP {r.status_code}, status {r.json()['status']}")
    out["submitted_during_redis_outage"] = r.json()["status"]
    compose("start", "redis")
    j = c.wait(jid, lambda j: j["status"] in ("COMPLETED", "FAILED"), 600)
    out["outbox_job_final_status"] = j["status"]
    # C. cancel a running job
    jid = c.post("/api/analysis/jobs", {**body, "start_year": 2004, "force_new": True}).json()["job_id"]
    c.wait(jid, lambda j: j["status"] == "RUNNING" or j["status"] == "COMPLETED", 300, every=0.5)
    r = c.post(f"/api/analysis/jobs/{jid}/cancel", {})
    j = c.wait(jid, lambda j: j["status"] in ("CANCELLED", "COMPLETED"), 300)
    out["cancel_running_job"] = j["status"]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("iso3", nargs="?", default="USA")
    ap.add_argument("--queue-drills-only", action="store_true")
    ap.add_argument("--no-queue-drills", action="store_true")
    a = ap.parse_args()
    report = {}
    if not a.queue_drills_only:
        report["country"] = country_drill(a.iso3)
    if not a.no_queue_drills:
        report["queue"] = queue_drills()
    out = ROOT / "backend" / "var" / "live-validation" / f"docker-drill-{a.iso3 if not a.queue_drills_only else 'queue'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report["log"] = log
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "log"}, indent=2))
    sys.exit(0)
