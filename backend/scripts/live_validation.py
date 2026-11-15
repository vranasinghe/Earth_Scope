"""LIVE cross-validation: application output vs an independent recomputation
from the raw NASA POWER response (internet required).

For each city and variable this script
  1. runs the application's full pipeline (NasaPowerClient -> parsing -> stats);
  2. separately downloads the raw NASA POWER JSON with plain `requests`;
  3. independently cleans the raw monthly values (drops -999 and the YYYY13
     annual key), computes day-weighted annual means (>= 10 valid months) and
     recomputes OLS / Mann-Kendall / Sen's slope with the reference formulas in
     tests/test_statistical_validation.py (no scipy.stats.linregress, no
     pymannkendall);
  4. compares everything, plus units, missing-value handling and coordinates.

Run from the backend folder:  python scripts/live_validation.py
"""

from __future__ import annotations

import calendar
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from app.core.catalog import VARIABLES  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.analysis_service import build_analysis_response  # noqa: E402
from app.services.nasa_power import NasaPowerClient  # noqa: E402
from app.utils.validators import AnalysisQuery  # noqa: E402
from tests.test_statistical_validation import ref_mann_kendall, ref_ols, ref_sen  # noqa: E402
from tests.test_advanced_statistics import ref_hamed_rao_gap_aware, ref_sen_ci  # noqa: E402

import numpy as np  # noqa: E402
import pymannkendall as pmk  # noqa: E402
import statsmodels.api as sm  # noqa: E402

CITIES = [
    ("Colombo", 6.9271, 79.8612),
    ("New York", 40.7128, -74.0060),
    ("Tokyo", 35.6762, 139.6503),
    ("Nairobi", -1.2921, 36.8219),
    ("Sydney", -33.8688, 151.2093),
    ("Sao Paulo", -23.5505, -46.6333),
    ("Reykjavik", 64.1466, -21.9426),
]
URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
failures: list[str] = []


def close(a: float, b: float, rel: float = 1e-6, abs_: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def check(cond: bool, label: str) -> None:
    if not cond:
        failures.append(label)
        print("    FAIL", label)


def independent(raw: dict, param: str, start: int, end: int):
    series = raw["properties"]["parameter"][param]
    fill = raw["header"]["fill_value"]
    annual = []
    n_missing = 0
    for y in range(start, end + 1):
        vals = []
        for m in range(1, 13):
            v = series.get(f"{y}{m:02d}")
            if v is None or v == fill:
                n_missing += 1
                continue
            vals.append((float(v), calendar.monthrange(y, m)[1]))
        if len(vals) >= 10:
            annual.append((y, sum(v * d for v, d in vals) / sum(d for _, d in vals)))
    return annual, n_missing


def main() -> int:
    settings = get_settings()
    start, end = 2001, settings.default_end_year
    client = NasaPowerClient(settings)
    print(f"Live validation {start}-{end}: {len(CITIES)} cities x {len(VARIABLES)} variables\n")
    for name, lat, lon in CITIES:
        for v in VARIABLES:
            res = build_analysis_response(AnalysisQuery(v, lat, lon, start, end), client, settings)
            raw = requests.get(URL, params=dict(parameters=v.parameter, community=v.community, latitude=lat,
                                                longitude=lon, start=start, end=end, format="JSON"), timeout=90).json()
            annual, n_missing = independent(raw, v.parameter, start, end)
            years = [float(y) for y, _ in annual]
            vals = [val for _, val in annual]
            s = res["statistics"]
            m = res["metadata"]
            ols, mk, sen = ref_ols(years, vals), ref_mann_kendall(vals), ref_sen(years, vals)
            tag = f"{name}/{v.parameter}"

            check(m["units_raw"] == raw["parameters"][v.parameter]["units"], f"{tag} units")
            check(m["sources"] == raw["header"]["sources"], f"{tag} sources")
            check(res["summary"]["n_monthly_missing"] == n_missing, f"{tag} missing-month count")
            check(all(r["value"] is None for r in res["monthly"] if r["status"] != "valid"), f"{tag} gaps not zero-filled")
            check(close(m["latitude_requested"], lat) and close(m["longitude_requested"], lon), f"{tag} requested coords")
            app_annual = [(a["year"], a["value"]) for a in res["annual"] if a["used_in_trend"]]
            check(len(app_annual) == len(annual) and all(ya == yb and close(va, vb) for (ya, va), (yb, vb) in zip(app_annual, annual)),
                  f"{tag} annual means")
            check(s is not None, f"{tag} statistics present")
            if s:
                r, k = s["regression"], s["mann_kendall"]
                for key in ("slope", "intercept", "std_err", "r_squared", "ci_lower", "ci_upper"):
                    check(close(r[key], ols[key], rel=1e-6, abs_=1e-10), f"{tag} OLS {key}")
                check(close(r["p_value"], ols["p_value"], rel=1e-5, abs_=1e-12), f"{tag} OLS p")
                check(k["s"] == mk["s"] and close(k["var_s"], mk["var_s"]) and close(k["z"], mk["z"]), f"{tag} MK S/var/Z")
                check(close(k["p_value"], mk["p_value"], rel=1e-8, abs_=1e-14), f"{tag} MK p")
                check(close(s["sens_slope"]["slope"], sen, rel=1e-9), f"{tag} Sen")

                # --- Advanced statistics -------------------------------------------------
                a = s["advanced"]
                hr, yw, hac = a["modified_mann_kendall"], a["yue_wang_sensitivity"], a["regression_hac"]
                arr = np.asarray(vals)
                with np.errstate(invalid="ignore"):
                    ref_hr = pmk.hamed_rao_modification_test(arr, lag=3)
                    ref_yw = pmk.yue_wang_modification_test(arr, lag=1)
                factor, p_ref = ref_hamed_rao_gap_aware(np.asarray(years), arr)
                # Raw (unfloored) factor must reproduce both references exactly...
                check(close(hr["raw_correction_factor"] * hr["var_s_original"], ref_hr.var_s, rel=1e-9), f"{tag} Hamed-Rao raw vs pymannkendall")
                check(close(hr["raw_correction_factor"], factor), f"{tag} Hamed-Rao raw vs reference")
                check(close(yw["raw_correction_factor"] * yw["var_s_original"], ref_yw.var_s, rel=1e-9), f"{tag} Yue-Wang raw")
                # ...and the applied test follows the conservative floor at 1.
                expected_p = ref_hr.p if factor >= 1 else k["p_value"]
                check(hr["available"] and close(hr["p_value"], expected_p, rel=1e-8, abs_=1e-14), f"{tag} Hamed-Rao applied p")
                check(hr["p_value"] >= k["p_value"] - 1e-15, f"{tag} adjusted p never below original")
                lo, hi = ref_sen_ci(years, vals)
                check(close(s["sens_slope"]["ci_lower"], lo) and close(s["sens_slope"]["ci_upper"], hi), f"{tag} Sen CI")
                fit = sm.OLS(arr, sm.add_constant(np.asarray(years))).fit(
                    cov_type="HAC", cov_kwds={"maxlags": hac["max_lags"], "use_correction": True}, use_t=True)
                check(close(hac["std_err"], float(fit.bse[1]), rel=1e-7) and close(hac["p_value"], float(fit.pvalues[1]), rel=1e-6), f"{tag} HAC")
                print(f"  ok  {tag:<20} slope {r['slope']:+.5f} {m['rate_unit']:<23} | r1 {a['autocorrelation']['lag1']:+.2f} "
                      f"| MK p {k['p_value']:.4f} -> HR p {hr['p_value']:.4f} (x{hr['correction_factor']:.2f}, raw {hr['raw_correction_factor']:.2f}) "
                      f"| Sen CI [{s['sens_slope']['ci_lower']:+.4f}, {s['sens_slope']['ci_upper']:+.4f}] "
                      f"| HAC p {hac['p_value']:.4f} | {s['evidence']['label']} / {a['robust_evidence']['label']}")
    print(f"\n{'ALL LIVE CROSS-CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
