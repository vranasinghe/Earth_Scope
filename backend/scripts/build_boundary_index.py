"""Build app/data/country_index.json — the reproducible country-boundary catalogue.

Primary source: geoBoundaries gbOpen ADM0 (https://www.geoboundaries.org/), one
record per country with its own licence, source, year represented and a download
URL pinned to a geoBoundaries Git commit (reproducible).

Fallback: Natural Earth 1:50m Admin-0 countries v5.1.2 (public domain) — used
ONLY for codes that gbOpen does not provide (for example India), and labelled
as such. Geometries are not stored here; app/services/boundaries.py downloads
them on demand from the pinned URLs (allow-listed hosts) and caches them.

Usage (from backend/):
    python scripts/build_boundary_index.py                 # fetch the gbOpen index
    python scripts/build_boundary_index.py path/to/raw.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
GB_INDEX_URL = "https://www.geoboundaries.org/api/current/gbOpen/ALL/ADM0/"
NE_VERSION = "v5.1.2"
NE_URL = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_VERSION}/geojson/ne_50m_admin_0_countries.geojson"
NE_CACHE = DATA / "boundary_cache" / f"ne_50m_admin_0_countries_{NE_VERSION}.geojson"


def ne_code(props: dict) -> str | None:
    for k in ("ISO_A3", "ISO_A3_EH", "ADM0_A3"):
        v = props.get(k)
        if isinstance(v, str) and re.fullmatch(r"[A-Z]{3}", v):
            return v
    return None


def main() -> int:
    if len(sys.argv) > 1:
        raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        raw = requests.get(GB_INDEX_URL, timeout=120).json()
    out: dict[str, dict] = {}
    for r in raw:
        iso = r["boundaryISO"]
        url = r["simplifiedGeometryGeoJSON"]
        commit = re.search(r"/raw/([0-9a-f]+)/", url)
        out[iso] = {
            "iso3": iso,
            "name": r["boundaryName"],
            "source": "geoBoundaries",
            "dataset": "geoBoundaries gbOpen ADM0 (simplified geometry)",
            "version": f"gbOpen commit {commit.group(1)}" if commit else "gbOpen (unpinned)",
            "boundary_id": r["boundaryID"],
            "year_represented": r.get("boundaryYearRepresented"),
            "license": r.get("boundaryLicense"),
            "license_source": r.get("licenseSource"),
            "upstream_source": r.get("boundarySource"),
            "build_date": r.get("buildDate"),
            "reported_area_km2": float(r["meanAreaSqKM"]) if r.get("meanAreaSqKM") else None,
            "geometry_url": url,
            "attribution": f"Boundary: geoBoundaries gbOpen ({r['boundaryID']}), source {r.get('boundarySource')}, "
            f"licence {r.get('boundaryLicense')}. Runfola et al. (2020) geoBoundaries, PLoS ONE 15(4): e0231866.",
            "status": "country",
        }

    if not NE_CACHE.exists():
        NE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        NE_CACHE.write_bytes(requests.get(NE_URL, timeout=180).content)
    ne = json.loads(NE_CACHE.read_text(encoding="utf-8"))
    for f in ne["features"]:
        p = f["properties"]
        code = ne_code(p)
        if not code or code in out:
            continue
        out[code] = {
            "iso3": code,
            "name": p.get("NAME_LONG") or p.get("NAME") or code,
            "source": "Natural Earth",
            "dataset": "Natural Earth 1:50m Cultural Vectors — Admin 0 Countries (fallback: not in geoBoundaries gbOpen)",
            "version": f"Natural Earth {NE_VERSION}",
            "boundary_id": f"NE50m-{p.get('ADM0_A3', code)}",
            "year_represented": None,
            "license": "Public Domain (Natural Earth terms of use)",
            "license_source": "https://www.naturalearthdata.com/about/terms-of-use/",
            "upstream_source": "Natural Earth (de facto boundaries, 1:50m generalisation)",
            "build_date": None,
            "reported_area_km2": None,
            "geometry_url": NE_URL,
            "ne_feature": p.get("ADM0_A3", code),
            "attribution": "Boundary: Made with Natural Earth (public domain), Admin 0 Countries 1:50m v5.1.2.",
            "status": (p.get("TYPE") or "country").lower(),
        }

    items = sorted(out.values(), key=lambda x: x["name"])
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "country_index.json").write_text(json.dumps({"generated_from": [GB_INDEX_URL, NE_URL], "countries": items}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(items)} countries ({sum(1 for i in items if i['source'] == 'geoBoundaries')} geoBoundaries, "
          f"{sum(1 for i in items if i['source'] == 'Natural Earth')} Natural Earth fallback)")
    print("Natural Earth fallback:", ", ".join(f"{i['iso3']} {i['name']}" for i in items if i["source"] == "Natural Earth"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
