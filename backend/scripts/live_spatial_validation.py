"""LIVE validation of the per-grid-cell Spatial Trend Explorer (internet required).

For each region the script calls the real API endpoint (/api/regional/spatial-trends,
exactly the JSON the frontend draws and exports) and, separately, downloads the raw
NASA POWER regional JSON with plain `requests`, then independently:
  * determines which returned cells overlap the box (spherical overlap > 0) and,
    for soil wetness, which are water/ice (constant 1.0);
  * computes every cell's day-weighted annual means (>= 10 valid months);
  * recomputes OLS, Mann-Kendall (reference formulas) and Sen's slope per cell;
  * applies its own Benjamini-Hochberg correction to its own Mann-Kendall p-values
    and checks every q-value and map classification;
  * checks Benjamini-Yekutieli on the canonical Hamed-Rao p-values against statsmodels;
  * checks the per-cell detail endpoint's annual series.

No synthetic data is used. Run from the backend folder:
    python scripts/live_spatial_validation.py
"""

from __future__ import annotations

import calendar
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_statistical_validation import ref_mann_kendall, ref_ols  # noqa: E402

R = 6371.0088
REGIONS = [
    ("Sri Lanka", "T2M", (6.0, 9.5, 79.5, 82.0)),
    ("India (Indo-Gangetic Plain)", "T2M", (25.0, 29.0, 77.0, 83.0)),
    ("Kenya (equator-crossing) soil wetness", "GWETTOP", (-3.0, 1.0, 35.0, 39.0)),
    ("Brazil (Central Amazon) humidity", "RH2M", (-6.0, -2.0, -64.0, -58.0)),
    ("South-eastern Australia", "T2M", (-36.0, -32.0, 142.0, 148.0)),
]
failures: list[str] = []


def close(a, b, rel=1e-9, abs_=1e-9):
    return a is not None and b is not None and abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def check(cond, label):
    if not cond:
        failures.append(label)
        print("    FAIL", label)


def area(la0, la1, lo0, lo1):
    if la1 <= la0 or lo1 <= lo0:
        return 0.0
    return R * R * math.radians(lo1 - lo0) * (math.sin(math.radians(la1)) - math.sin(math.radians(la0)))


def independent_cells(raw, param, box, start, end, land_only):
    la0, la1, lo0, lo1 = box
    fill = raw["header"]["fill_value"]
    out = {}
    for f in raw["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        cid = f"{lat:.3f}_{lon:.4f}"
        w = area(max(lat - 0.25, la0), min(lat + 0.25, la1), max(lon - 0.3125, lo0), min(lon + 0.3125, lo1))
        if w <= 0 or cid in out:
            continue
        s = f["properties"]["parameter"][param]
        vals = {(y, m): (None if s.get(f"{y}{m:02d}") in (None, fill) else float(s[f"{y}{m:02d}"]))
                for y in range(start, end + 1) for m in range(1, 13)}
        valid = [v for v in vals.values() if v is not None]
        water = land_only and bool(valid) and all(abs(v - 1.0) < 1e-9 for v in valid)
        annual = []
        for y in range(start, end + 1):
            ok = [(vals[(y, m)], calendar.monthrange(y, m)[1]) for m in range(1, 13) if vals[(y, m)] is not None]
            if len(ok) >= 10:
                annual.append((y, sum(v * d for v, d in ok) / sum(d for _, d in ok)))
        out[cid] = {"overlap": w, "water": water, "annual": annual}
    return out


def own_bh(p):
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * m / rank)
        q[i] = min(1.0, running)
    return q


def main() -> int:
    settings = get_settings()
    start, end = 2001, settings.default_end_year
    api = TestClient(app)
    print(f"Live spatial trend validation {start}-{end} (real NASA POWER data)\n")
    for name, param, box in REGIONS:
        print(f"== {name} [{param}] box {box}")
        params = dict(variable=param, lat_min=box[0], lat_max=box[1], lon_min=box[2], lon_max=box[3], start_year=start, end_year=end)
        t0 = time.perf_counter()
        r = api.get("/api/regional/spatial-trends", params=params)
        t1 = time.perf_counter()
        if r.status_code != 200:
            check(False, f"{name}: HTTP {r.status_code} {r.text[:200]}")
            continue
        res = r.json()
        meta = res["metadata"]
        check(meta["data_mode"] == "LIVE" and meta["request_url"], f"{name}: not live / no request URL")
        raw = requests.get(meta["request_url"], timeout=180).json()
        land_only = param == "GWETTOP"
        ind = independent_cells(raw, param, box, start, end, land_only)
        cells = {c["id"]: c for c in res["cells"]}
        check(set(cells) == set(ind), f"{name}: cell set differs ({len(cells)} vs {len(ind)})")

        own_p, own_ids = [], []
        n_checked = 0
        for cid, ic in ind.items():
            c = cells.get(cid)
            if c is None:
                continue
            check(close(c["overlap_area_km2"], ic["overlap"], rel=1e-9), f"{name} {cid}: overlap area")
            if ic["water"]:
                check(c["status"] == "excluded", f"{name} {cid}: water cell not excluded")
                continue
            check(c["valid_years"] == len(ic["annual"]), f"{name} {cid}: valid years {c['valid_years']} vs {len(ic['annual'])}")
            if len(ic["annual"]) < 10:
                check(c["status"] == "insufficient_data", f"{name} {cid}: should be insufficient")
                continue
            x = [float(y) for y, _ in ic["annual"]]
            y = [v for _, v in ic["annual"]]
            if max(y) - min(y) <= 1e-12 * max(1.0, max(abs(v) for v in y)):
                check(c["data_status"] == "no_variation", f"{name} {cid}: constant series")
                continue
            ols, mk = ref_ols(x, y), ref_mann_kendall(y)
            sen = statistics.median((y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x)))
            check(close(c["ols_slope"], ols["slope"], rel=1e-8), f"{name} {cid}: OLS slope {c['ols_slope']} vs {ols['slope']}")
            check(close(c["ols_p_value"], ols["p_value"], rel=1e-6, abs_=1e-10), f"{name} {cid}: OLS p")
            check(c["mk_s"] == mk["s"], f"{name} {cid}: MK S {c['mk_s']} vs {mk['s']}")
            check(close(c["mk_p_value"], mk["p_value"], rel=1e-8, abs_=1e-12), f"{name} {cid}: MK p {c['mk_p_value']} vs {mk['p_value']}")
            check(close(c["sen_slope"], sen, rel=1e-9, abs_=1e-12), f"{name} {cid}: Sen slope")
            own_p.append(mk["p_value"])
            own_ids.append(cid)
            n_checked += 1

        # Independent Benjamini-Hochberg on independently computed MK p-values.
        q = own_bh(own_p)
        check(res["summary"]["n_hypotheses"] == len(own_p), f"{name}: family size {res['summary']['n_hypotheses']} vs {len(own_p)}")
        for cid, qi, pi in zip(own_ids, q, own_p):
            c = cells[cid]
            check(close(c["adjusted_p_value"], qi, rel=1e-7, abs_=1e-12), f"{name} {cid}: BH q {c['adjusted_p_value']} vs {qi}")
            expect = ("significant_increasing" if c["mk_s"] > 0 else "significant_decreasing") if qi <= 0.05 else "not_significant"
            check(c["status"] == expect, f"{name} {cid}: status {c['status']} vs {expect}")
            raw_expect = ("significant_increasing" if c["mk_s"] > 0 else "significant_decreasing") if pi < 0.05 else "not_significant"
            check(c["raw_status"] == raw_expect, f"{name} {cid}: raw status")

        # A different test / correction / threshold: same NASA data, BY checked against statsmodels.
        r2 = api.get("/api/regional/spatial-trends", params={**params, "method": "hamed_rao_canonical", "correction": "fdr_by", "alpha": 0.1}).json()
        fam = [c for c in r2["cells"] if c["in_family"]]
        if fam:
            ref = multipletests([c["hr_canonical_p_value"] for c in fam], method="fdr_by")[1]
            check(all(close(c["adjusted_p_value"], qr, rel=1e-9, abs_=1e-12) for c, qr in zip(fam, ref)), f"{name}: BY q-values")
            check(all(c["status"].startswith("significant") == (c["adjusted_p_value"] <= 0.1) for c in fam), f"{name}: BY statuses")
        check(r2["metadata"]["served_from_cache"], f"{name}: second request was not served from cache")

        # Detail endpoint: annual series of three cells.
        for cid in own_ids[:: max(1, len(own_ids) // 3)][:3]:
            d = api.get("/api/regional/spatial-trends/cell", params={**params, "cell_id": cid}).json()
            app_annual = [(a["year"], a["value"]) for a in d["annual"] if a["used_in_trend"]]
            check(len(app_annual) == len(ind[cid]["annual"]) and all(ya == yb and close(va, vb, rel=1e-12) for (ya, va), (yb, vb) in zip(app_annual, ind[cid]["annual"])),
                  f"{name} {cid}: detail annual series")

        s = res["summary"]
        slopes = [c["sen_slope"] for c in res["cells"] if c["sen_slope"] is not None]
        reg = res["regional_aggregate"] or {}
        print(f"    cells {s['n_cells_total']} (excluded {s['n_cells_excluded']}), tested {s['n_hypotheses']}, independently re-checked {n_checked}")
        print(f"    raw p<0.05: {s['n_raw_significant']}, BH discoveries: {s['n_fdr_discoveries']}, BY(HR canonical, a=0.1): {r2['summary']['n_fdr_discoveries']}")
        print(f"    Sen slopes {min(slopes):+.4f} .. {max(slopes):+.4f} {meta['rate_unit']}; +{s['n_positive_slope']} / -{s['n_negative_slope']} / ~0 {s['n_near_zero_slope']}")
        print(f"    regional OLS slope {reg.get('ols_slope')}, area-weighted mean cell OLS slope {s['area_weighted_mean_ols_slope']} (identity exact: {s['slope_identity_exact']})")
        print(f"    first request {t1 - t0:.1f}s (incl. NASA download)\n")

    print("ALL LIVE SPATIAL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
