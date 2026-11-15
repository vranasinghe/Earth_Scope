"""Country boundaries: catalogue, download-on-demand from pinned URLs, caching.

Default source: geoBoundaries gbOpen ADM0 simplified geometries, each pinned to a
geoBoundaries Git commit (reproducible) and carrying its own licence. Fallback:
Natural Earth 1:50m Admin-0 v5.1.2 (public domain) for codes gbOpen lacks (e.g.
India) — always labelled. A missing boundary is an error, never a rectangle.

Security: geometry URLs come only from the bundled catalogue
(app/data/country_index.json) and must start with an allow-listed prefix; the
final host after redirects must also be allow-listed. User input selects an ISO
code from that catalogue — it never supplies a URL.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import shapely

from app.core.config import get_settings
from app.services import area_geometry as ag
from app.utils.errors import BoundarySourceUnavailableError, CountryNotFoundError

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
INDEX_PATH = DATA_DIR / "country_index.json"
ALLOWED_PREFIXES = (
    "https://github.com/wmgeolab/geoBoundaries/raw/",
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/",
)
ALLOWED_FINAL_HOSTS = {"github.com", "raw.githubusercontent.com", "media.githubusercontent.com", "objects.githubusercontent.com"}
MAX_DOWNLOAD_BYTES = 40_000_000
_lock = threading.Lock()


@lru_cache
def _index() -> dict[str, dict[str, Any]]:
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {c["iso3"]: c for c in data["countries"]}


def list_countries() -> list[dict[str, Any]]:
    return sorted(_index().values(), key=lambda c: c["name"])


def country_meta(iso3: str) -> dict[str, Any]:
    code = (iso3 or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code) or code not in _index():
        raise CountryNotFoundError(f"No boundary is available for country code '{iso3}'.",
                                   ["Use an ISO 3166-1 alpha-3 code from /api/boundaries/countries."])
    return _index()[code]


def _cache_dir() -> Path:
    s = get_settings()
    d = Path(s.boundary_cache_dir) if s.boundary_cache_dir else DATA_DIR / "boundary_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_bytes(url: str) -> bytes:
    """Download a catalogue URL (allow-listed, size-limited). Tests replace this function."""
    if not url.startswith(ALLOWED_PREFIXES):
        raise BoundarySourceUnavailableError("The boundary URL is not on the allow-list.")
    try:
        with requests.get(url, timeout=get_settings().boundary_timeout_seconds, stream=True, allow_redirects=True) as r:
            host = urlparse(r.url).hostname or ""
            if host not in ALLOWED_FINAL_HOSTS:
                raise BoundarySourceUnavailableError("The boundary download was redirected to an unexpected host.")
            if r.status_code != 200:
                raise BoundarySourceUnavailableError(f"The boundary provider answered HTTP {r.status_code}.")
            chunks, size = [], 0
            for chunk in r.iter_content(1 << 16):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise BoundarySourceUnavailableError("The boundary file is larger than allowed.")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as exc:
        logger.warning("Boundary download failed: %s", exc)
        raise BoundarySourceUnavailableError(
            "The country boundary could not be downloaded. Check the internet connection and try again."
        ) from exc


def _raw_geojson(meta: dict[str, Any]) -> dict[str, Any]:
    cache = _cache_dir()
    if meta["source"] == "Natural Earth":
        path = cache / "ne_50m_admin_0_countries_v5.1.2.geojson"
    else:
        path = cache / f"geoBoundaries_{meta['iso3']}_{meta['boundary_id']}.geojson"
    with _lock:
        if not path.exists():
            path.write_bytes(fetch_bytes(meta["geometry_url"]))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        path.unlink(missing_ok=True)
        raise BoundarySourceUnavailableError("The cached boundary file was unreadable; please retry.") from exc
    if meta["source"] == "Natural Earth":
        feats = [f for f in data.get("features", []) if f.get("properties", {}).get("ADM0_A3") == meta.get("ne_feature")]
        if not feats:
            raise BoundarySourceUnavailableError(f"Natural Earth has no feature for {meta['iso3']}.")
        return {"type": "FeatureCollection", "features": feats}
    return data


@lru_cache(maxsize=24)
def country_geometry(iso3: str) -> tuple[Any, list[str]]:
    """(validated shapely geometry used for calculations, notes)."""
    meta = country_meta(iso3)
    s = get_settings()
    geom, notes = ag.parse_geometry(_raw_geojson(meta), ag.GeometryLimits(s.country_max_vertices, 100_000), repair=True)
    shapely.prepare(geom)
    return geom, notes


def country_summary(iso3: str) -> dict[str, Any]:
    meta = country_meta(iso3)
    geom, notes = country_geometry(meta["iso3"])
    b = ag.bbox_of(geom)
    return {
        "meta": meta,
        "geometry": geom,
        "display": ag.display_geojson(geom),
        "bbox": {"lat_min": b.lat_min, "lat_max": b.lat_max, "lon_min": b.lon_min, "lon_max": b.lon_max},
        "area_km2": float(ag.equal_area_km2(geom)),
        "geodesic_area_km2": ag.geodesic_area_km2(geom),
        "n_components": ag.n_components(geom),
        "n_vertices": ag.n_vertices(geom),
        "geometry_id": ag.geometry_id(geom),
        "notes": notes,
    }
