"""Live smoke test against the real NASA POWER and Nominatim services.

Run from the backend folder (internet required):

    python scripts/live_smoke_test.py

1. Verifies the variable catalogue against NASA's parameter manager
   (MONTHLY availability and communities).
2. Runs the full analysis pipeline for 8 cities on every inhabited continent
   for every variable, plus an ocean point for soil wetness.
3. Performs one real location search and one reverse lookup.

Requests are made one at a time to respect the services' usage policies.
Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from app.core.catalog import VARIABLES  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.analysis_service import build_analysis_response  # noqa: E402
from app.services.geocoding import Geocoder  # noqa: E402
from app.services.nasa_power import NasaPowerClient  # noqa: E402
from app.utils.errors import EarthScopeError  # noqa: E402
from app.utils.validators import AnalysisQuery  # noqa: E402

LOCATIONS = [
    ("Colombo", 6.9271, 79.8612),
    ("New York", 40.7128, -74.0060),
    ("London", 51.5072, -0.1276),
    ("Tokyo", 35.6762, 139.6503),
    ("Nairobi", -1.2921, 36.8219),
    ("Sydney", -33.8688, 151.2093),
    ("Sao Paulo", -23.5505, -46.6333),
    ("Reykjavik", 64.1466, -21.9426),
]

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        failures.append(label)


def main() -> int:
    settings = get_settings()
    start, end = 2001, settings.default_end_year

    print("1. Catalogue vs NASA parameter manager")
    for v in VARIABLES:
        r = requests.get(f"https://power.larc.nasa.gov/api/system/manager/parameters/{v.parameter}", timeout=60)
        monthly = r.json()[v.parameter]["temporal"].get("MONTHLY", {})
        comms = monthly.get("communities", [])
        check(bool(monthly), f"{v.parameter} offered at MONTHLY resolution")
        check(v.community in comms, f"{v.parameter} community {v.community} in NASA list {comms}")

    print(f"\n2. Analysis pipeline, {start}-{end}")
    client = NasaPowerClient(settings)
    for name, lat, lon in LOCATIONS:
        for v in VARIABLES:
            try:
                res = build_analysis_response(AnalysisQuery(v, lat, lon, start, end), client, settings)
                s = res["statistics"]
                m = res["metadata"]
                ok = s is not None and res["summary"]["n_monthly_valid"] > 0
                detail = (
                    f"slope {s['regression']['slope']:+.4f} {m['rate_unit']}, MK p={s['mann_kendall']['p_value']:.3f}, "
                    f"{s['evidence']['label']}; grid {m['latitude_returned']},{m['longitude_returned']}"
                    if s else res["analysis_message"]
                )
                check(ok, f"{name:<10} {v.parameter:<8} {detail}")
            except EarthScopeError as exc:
                check(False, f"{name:<10} {v.parameter:<8} {exc.error}: {exc.message}")

    print("\n3. Soil wetness over the Pacific Ocean must be refused")
    soil = next(v for v in VARIABLES if v.land_only)
    try:
        build_analysis_response(AnalysisQuery(soil, 0.0, -140.0, start, end), client, settings)
        check(False, "ocean soil wetness was not refused")
    except EarthScopeError as exc:
        check(exc.error == "LOCATION_NOT_SUPPORTED", f"ocean soil wetness -> {exc.error}, suggests {exc.suggested_variables}")

    print("\n4. Location search (Nominatim)")
    geo = Geocoder(settings)
    results = geo.search("Nairobi, Kenya")
    check(bool(results) and results[0]["country"] == "Kenya", f"search 'Nairobi, Kenya' -> {results[:1]}")
    place = geo.reverse(35.6762, 139.6503)
    check(place is not None and place["country"] == "Japan", f"reverse Tokyo -> {place and place['display_name']}")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
