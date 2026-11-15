"""LIVE regional cross-validation (internet required).

For each region the script runs the application's regional pipeline AND,
separately, downloads the raw NASA POWER regional JSON with plain `requests`,
then independently:
  * parses the grid (centres, -999 fill values, YYYY13 annual keys ignored);
  * computes each cell's spherical overlap area with the box;
  * computes area-weighted monthly means and coverage;
  * computes day-weighted annual means (>= 10 valid months);
  * recomputes OLS and Mann-Kendall with the reference formulas from
    tests/test_statistical_validation.py;
and compares everything, plus provenance (request URL, units, sources).

Run from the backend folder:  python scripts/live_regional_validation.py
"""

from __future__ import annotations

import calendar
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from app.core.catalog import get_variable  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services import regional_analysis as ran  # noqa: E402
from app.services.nasa_power import NasaPowerClient  # noqa: E402
from app.services.regional_grid import validate_bbox  # noqa: E402
from app.utils.errors import EarthScopeError  # noqa: E402
from tests.test_statistical_validation import ref_mann_kendall, ref_ols  # noqa: E402

R = 6371.0088
REGIONS = [
    ("Sri Lanka", "T2M", (6.0, 9.5, 79.5, 82.0)),
    ("India (Indo-Gangetic)", "T2M", (25.0, 29.0, 77.0, 83.0)),
    ("Brazil (Amazon)", "RH2M", (-6.0, -2.0, -64.0, -58.0)),
    ("Kenya (equator-crossing)", "GWETTOP", (-3.0, 1.0, 35.0, 39.0)),
    ("Australia (SE)", "T2M", (-36.0, -32.0, 142.0, 148.0)),
    ("Europe (central)", "T2M", (47.0, 52.0, 8.0, 16.0)),
    ("North America (Corn Belt)", "GWETTOP", (40.0, 43.0, -95.0, -88.0)),
    ("High latitude (N Scandinavia)", "T2M", (66.0, 70.0, 16.0, 25.0)),
    ("Mixed land/ocean (Sri Lanka coast) soil", "GWETTOP", (5.0, 9.0, 78.0, 82.0)),
]
OCEAN = ("Ocean only (S Atlantic) soil", "GWETTOP", (-50.0, -46.0, -30.0, -26.0))
failures: list[str] = []


def close(a, b, rel=1e-9, abs_=1e-9):
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def check(cond, label):
    if not cond:
        failures.append(label)
        print("    FAIL", label)


def area(la0, la1, lo0, lo1):
    if la1 <= la0 or lo1 <= lo0:
        return 0.0
    return R * R * math.radians(lo1 - lo0) * (math.sin(math.radians(la1)) - math.sin(math.radians(la0)))


def independent(raw, param, box, start, end, thr, land_only):
    la0, la1, lo0, lo1 = box
    fill = raw["header"]["fill_value"]
    cells = {}
    for f in raw["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        w = area(max(lat - 0.25, la0), min(lat + 0.25, la1), max(lon - 0.3125, lo0), min(lon + 0.3125, lo1))
        if w <= 0 or (lat, lon) in cells:
            continue
        s = f["properties"]["parameter"][param]
        vals = {}
        for y in range(start, end + 1):
            for m in range(1, 13):
                v = s.get(f"{y}{m:02d}")
                vals[(y, m)] = None if v is None or v == fill else float(v)
        if land_only:
            valid = [v for v in vals.values() if v is not None]
            if valid and all(abs(v - 1.0) < 1e-9 for v in valid):
                continue  # water / ice cell
        cells[(lat, lon)] = (w, vals)
    total = sum(w for w, _ in cells.values()) if land_only else area(la0, la1, lo0, lo1)
    monthly = {}
    for y in range(start, end + 1):
        for m in range(1, 13):
            num = den = 0.0
            for w, vals in cells.values():
                if vals[(y, m)] is not None:
                    num += w * vals[(y, m)]
                    den += w
            monthly[(y, m)] = num / den if den > 0 and den / total >= thr - 1e-12 else None
    annual = []
    for y in range(start, end + 1):
        ok = [(monthly[(y, m)], calendar.monthrange(y, m)[1]) for m in range(1, 13) if monthly[(y, m)] is not None]
        if len(ok) >= 10:
            annual.append((y, sum(v * d for v, d in ok) / sum(d for _, d in ok)))
    return len(cells), monthly, annual


def main() -> int:
    settings = get_settings()
    start, end, thr = 2001, settings.default_end_year, settings.regional_coverage_threshold
    client = NasaPowerClient(settings)
    print(f"Live regional validation {start}-{end}, coverage threshold {thr:.0%}\n")
    for name, param, box in REGIONS + [OCEAN]:
        var = get_variable(param)
        bbox = validate_bbox(*box, settings.regional_min_span_deg, settings.regional_max_span_deg)
        q = ran.RegionalQuery(var, bbox, start, end, thr)
        try:
            res = ran.build_regional_response(q, client, settings, "live")
        except EarthScopeError as exc:
            expected_reject = (name, param, box) == OCEAN
            check(expected_reject and exc.error == "LOCATION_NOT_SUPPORTED", f"{name}: {exc.error} {exc.message}")
            print(f"  ok  {name:<40} rejected as expected: {exc.error} (suggests {exc.suggested_variables})" if expected_reject else "")
            continue
        m = res["metadata"]
        raw = requests.get(m["request_url"], timeout=180).json()
        n_cells, monthly, annual = independent(raw, param, box, start, end, thr, var.land_only)
        check(m["data_mode"] == "LIVE" and m["request_url"].startswith(settings.nasa_power_regional_url), f"{name} provenance URL")
        check(m["units_raw"] == raw["parameters"][param]["units"] and m["sources"] == raw["header"]["sources"], f"{name} units/sources")
        check(m["n_cells_used"] == n_cells, f"{name} cell count {m['n_cells_used']} vs {n_cells}")
        mism = [r["date"] for r in res["monthly"]
                if (r["value"] is None) != (monthly[(r["year"], r["month"])] is None)
                or (r["value"] is not None and not close(r["value"], monthly[(r["year"], r["month"])], rel=1e-10))]
        check(not mism, f"{name} monthly regional means ({len(mism)} mismatches, e.g. {mism[:3]})")
        app_annual = [(a["year"], a["value"]) for a in res["annual"] if a["used_in_trend"]]
        check(len(app_annual) == len(annual) and all(ya == yb and close(va, vb, rel=1e-10) for (ya, va), (yb, vb) in zip(app_annual, annual)),
              f"{name} annual means")
        s = res["statistics"]
        check(s is not None, f"{name} statistics present")
        if s:
            ols = ref_ols([float(y) for y, _ in annual], [v for _, v in annual])
            mk = ref_mann_kendall([v for _, v in annual])
            check(close(s["regression"]["slope"], ols["slope"], rel=1e-8) and close(s["regression"]["p_value"], ols["p_value"], rel=1e-6, abs_=1e-12), f"{name} OLS")
            check(s["mann_kendall"]["s"] == mk["s"] and close(s["mann_kendall"]["p_value"], mk["p_value"], rel=1e-8, abs_=1e-14), f"{name} Mann-Kendall")
            hr = s["advanced"]["modified_mann_kendall"]
            print(f"  ok  {name:<40} {param:<7} cells {m['n_cells_used']:>3} (+{m['n_cells_excluded']} excl) | "
                  f"cov {res['summary']['mean_coverage']:.0%} | slope {s['regression']['slope']:+.5f} {m['rate_unit']} | "
                  f"MK p {s['mann_kendall']['p_value']:.4f} | HR p {hr['p_value']:.4f} (canonical {hr['canonical_p_value'] if hr['canonical_p_value'] is None else round(hr['canonical_p_value'], 4)}) | "
                  f"Sen [{s['sens_slope']['ci_lower']:+.4f}, {s['sens_slope']['ci_upper']:+.4f}] | {s['evidence']['label']} / {s['advanced']['robust_evidence']['label']}")
    print(f"\n{'ALL LIVE REGIONAL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
