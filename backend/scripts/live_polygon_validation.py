"""LIVE validation of country / custom-polygon analysis (internet required).

For each area the script calls the real API (/api/polygon/analyze and
/api/polygon/spatial-trends — exactly what the frontend shows and exports) and,
separately, downloads every NASA tile URL in the request manifest with plain
`requests`, then independently:
  * merges the tiles itself (cells keyed by rounded centre) and counts duplicates;
  * computes every cell's overlap with the area with its own spherical
    equal-area code (and checks the weights against WGS84 pyproj.Geod areas);
  * computes the polygon-weighted monthly means with the coverage rule, the
    day-weighted annual means, OLS and Mann-Kendall (reference formulas);
  * recomputes per-cell Mann-Kendall p-values and its own Benjamini-Hochberg q-values.

Only the tested extents are validated — a sub-region polygon does not validate a whole country.
Run from the backend folder:  python scripts/live_polygon_validation.py
"""

from __future__ import annotations

import calendar
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import requests  # noqa: E402
import shapely  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pyproj import Geod  # noqa: E402
from shapely.geometry import box, shape  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import boundaries  # noqa: E402
from tests.test_statistical_validation import ref_mann_kendall, ref_ols  # noqa: E402

R = 6371.0088
GEOD = Geod(ellps="WGS84")


def poly(*pts):
    return {"type": "Polygon", "coordinates": [[list(p) for p in pts] + [list(pts[0])]]}


AREAS = [
    ("Sri Lanka — whole country (geoBoundaries)", "T2M", {"iso3": "LKA"}),
    ("India — Indo-Gangetic Plain polygon (sub-region)", "T2M", {"geometry": poly((76.5, 30.8), (80.2, 28.0), (85.6, 26.6), (88.0, 25.2), (84.0, 24.6), (79.0, 26.0), (75.8, 28.9)), "name": "Indo-Gangetic Plain"}),
    ("Kenya — polygon across the equator (sub-region)", "GWETTOP", {"geometry": poly((35.0, 1.6), (37.9, 1.2), (38.6, -1.9), (37.0, -3.4), (34.6, -1.2)), "name": "Central Kenya"}),
    ("Brazil — Amazon polygon spanning several tiles (sub-region)", "RH2M", {"geometry": poly((-66.0, -1.5), (-55.0, -0.8), (-51.5, -6.0), (-58.0, -11.5), (-67.5, -8.0)), "name": "Central Amazon"}),
    ("Australia — south-east polygon (sub-region)", "T2M", {"geometry": poly((141.0, -34.0), (145.5, -31.5), (149.5, -33.0), (148.0, -37.2), (142.5, -37.0)), "name": "Murray-Darling south"}),
]
failures: list[str] = []


def check(cond, label):
    if not cond:
        failures.append(label)
        print("    FAIL", label)


def close(a, b, rel=1e-9, abs_=1e-9):
    return a is not None and b is not None and abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def cea_area(g) -> float:
    """Independent spherical equal-area area: densify, project x = Rλ, y = R sin φ, shoelace."""
    g = shapely.segmentize(g, 0.02)
    total = 0.0
    for p in getattr(g, "geoms", [g]):
        for ring_sign, ring in [(1, p.exterior)] + [(-1, r) for r in p.interiors]:
            xy = np.asarray(ring.coords)
            x = R * np.radians(xy[:, 0])
            y = R * np.sin(np.radians(xy[:, 1]))
            total += ring_sign * abs(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
    return float(total)


def cell_box(lat, lon):
    lo0, lo1 = lon - 0.3125, lon + 0.3125
    la0, la1 = max(-90, lat - 0.25), min(90, lat + 0.25)
    if lo0 < -180:
        return shapely.MultiPolygon([box(-180, la0, lo1, la1), box(lo0 + 360, la0, 180, la1)])
    return box(lo0, la0, lo1, la1)


def main() -> int:
    s = get_settings()
    start, end, thr = 2001, s.default_end_year, s.regional_coverage_threshold
    api = TestClient(app)
    print(f"Live country / polygon validation {start}-{end} (real NASA POWER data; tested extents only)\n")
    for name, param, area in AREAS:
        print(f"== {name} [{param}]")
        body = {**area, "variable": param, "start_year": start, "end_year": end}
        t0 = time.perf_counter()
        r = api.post("/api/polygon/analyze", json=body)
        t1 = time.perf_counter()
        if r.status_code != 200:
            check(False, f"{name}: HTTP {r.status_code} {r.text[:300]}")
            continue
        res = r.json()
        m = res["metadata"]
        check(m["data_mode"] == "LIVE" and m["request_manifest"], f"{name}: not live / no manifest")
        geom = boundaries.country_geometry(area["iso3"])[0] if "iso3" in area else shape(area["geometry"])

        # --- independent tile merge ---
        cells: dict[tuple[float, float], dict] = {}
        seen_count: dict[tuple[float, float], int] = {}
        for t in m["request_manifest"]:
            raw = requests.get(t["url"], timeout=180).json()
            fill = raw["header"]["fill_value"]
            for f in raw["features"]:
                lon, lat = f["geometry"]["coordinates"][:2]
                key = (round(lat, 4), round(lon, 4))
                ov = cell_box(lat, lon).intersection(geom)
                if ov.is_empty or ov.area <= 0:
                    continue
                a = cea_area(ov)
                if a <= 1e-6:
                    continue
                seen_count[key] = seen_count.get(key, 0) + 1
                ser = f["properties"]["parameter"][param]
                vals = {(y, mo): (None if ser.get(f"{y}{mo:02d}") in (None, fill) else float(ser[f"{y}{mo:02d}"]))
                        for y in range(start, end + 1) for mo in range(1, 13)}
                if key in cells:
                    check(cells[key]["vals"] == vals, f"{name} {key}: duplicate cell with different values")
                    continue
                cells[key] = {"w": a, "geod": abs(GEOD.geometry_area_perimeter(shapely.segmentize(ov, 0.02))[0]) / 1e6, "vals": vals}
        if param == "GWETTOP":
            cells = {k: c for k, c in cells.items() if not all(v is not None and abs(v - 1) < 1e-9 for v in c["vals"].values() if v is not None) or
                     all(v is None for v in c["vals"].values())}
        n_dup_ind = sum(c - 1 for k, c in seen_count.items() if k in cells)
        check(m["n_cells_used"] == len(cells), f"{name}: cells used {m['n_cells_used']} vs independent {len(cells)}")
        check(m["n_duplicates"] == n_dup_ind, f"{name}: duplicates {m['n_duplicates']} vs independent {n_dup_ind}")
        app_cells = {(round(c["latitude"], 4), round(c["longitude"], 4)): c for c in res["cells"] if c["status"] != "excluded"}
        check(set(app_cells) == set(cells), f"{name}: cell identities differ")
        worst_w = max(abs(app_cells[k]["overlap_area_km2"] - c["w"]) / c["w"] for k, c in cells.items() if k in app_cells)
        check(worst_w < 1e-7, f"{name}: overlap areas differ (max rel {worst_w:.2e})")
        wsum, gsum = sum(c["w"] for c in cells.values()), sum(c["geod"] for c in cells.values())
        worst_geod = max(abs(c["w"] / wsum - c["geod"] / gsum) / (c["w"] / wsum) for c in cells.values())
        check(worst_geod < 5e-3, f"{name}: normalised weights vs WGS84 geodesic differ by {worst_geod:.2e}")

        # --- independent polygon-weighted monthly + annual series ---
        area_km2 = sum(c["w"] for c in cells.values())
        annual = []
        for y in range(start, end + 1):
            months = []
            for mo in range(1, 13):
                valid = [(c["w"], c["vals"][(y, mo)]) for c in cells.values() if c["vals"][(y, mo)] is not None]
                vw = sum(w for w, _ in valid)
                if valid and vw / area_km2 >= thr - 1e-9:
                    months.append((sum(w * v for w, v in valid) / vw, calendar.monthrange(y, mo)[1]))
            if len(months) >= 10:
                annual.append((y, sum(v * d for v, d in months) / sum(d for _, d in months)))
        app_ann = [(a["year"], a["value"]) for a in res["annual"] if a["used_in_trend"]]
        check(len(app_ann) == len(annual) and all(ya == yb and close(va, vb, rel=1e-9) for (ya, va), (yb, vb) in zip(app_ann, annual)),
              f"{name}: annual polygon series differs")
        st = res["statistics"]
        x, yv = [float(a) for a, _ in annual], [b for _, b in annual]
        ols, mk = ref_ols(x, yv), ref_mann_kendall(yv)
        check(close(st["regression"]["slope"], ols["slope"], rel=1e-8), f"{name}: OLS slope")
        check(close(st["mann_kendall"]["p_value"], mk["p_value"], rel=1e-7, abs_=1e-12), f"{name}: MK p")

        # --- spatial: per-cell MK p and BH q ---
        t2 = time.perf_counter()
        sp = api.post("/api/polygon/spatial-trends", json=body).json()
        t3 = time.perf_counter()
        fam = [c for c in sp["cells"] if c["in_family"]]
        check(len(fam) == sp["summary"]["n_hypotheses"], f"{name}: family size")
        check({(round(c["latitude"], 4), round(c["longitude"], 4)) for c in sp["cells"] if c["status"] != "excluded"} == set(cells),
              f"{name}: spatial cells are not exactly the polygon cells")
        own = []
        for c in fam:
            k = (round(c["latitude"], 4), round(c["longitude"], 4))
            ann = []
            for y in range(start, end + 1):
                ok = [(cells[k]["vals"][(y, mo)], calendar.monthrange(y, mo)[1]) for mo in range(1, 13) if cells[k]["vals"][(y, mo)] is not None]
                if len(ok) >= 10:
                    ann.append(sum(v * d for v, d in ok) / sum(d for _, d in ok))
            p = ref_mann_kendall(ann)["p_value"]
            check(close(c["mk_p_value"], p, rel=1e-7, abs_=1e-12), f"{name} {k}: cell MK p")
            own.append(p)
        mfam = len(own)
        order = sorted(range(mfam), key=lambda i: own[i])
        q = [0.0] * mfam
        run = 1.0
        for rank in range(mfam, 0, -1):
            i = order[rank - 1]
            run = min(run, own[i] * mfam / rank)
            q[i] = min(1.0, run)
        check(all(close(c["adjusted_p_value"], qi, rel=1e-7, abs_=1e-12) for c, qi in zip(fam, q)), f"{name}: BH q-values")
        check(any(c["clip"] is not None for c in sp["cells"]), f"{name}: no clipped edge cells")

        tiles = m["request_manifest"]
        print(f"    tiles {len(tiles)} ({sum(t['cells_returned'] for t in tiles)} cells returned), cells used {m['n_cells_used']}, "
              f"excluded {m['n_cells_excluded']}, duplicates merged {m['n_duplicates']}, representability {m['grid_representability']:.6f}")
        print(f"    area {m['polygon_area_km2']:,.0f} km2 (geodesic {m['geodesic_area_km2']:,.0f}); weights vs WGS84 max diff {worst_geod:.1e}")
        print(f"    slope {st['regression']['slope']:+.5f} {m['rate_unit']}, MK p {st['mann_kendall']['p_value']:.4f}; "
              f"cells: raw p<0.05 {sp['summary']['n_raw_significant']}, BH discoveries {sp['summary']['n_fdr_discoveries']} of {mfam}")
        print(f"    timing: analysis {t1 - t0:.1f}s (incl. NASA download), spatial {t3 - t2:.1f}s\n")

    print("ALL LIVE POLYGON CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
