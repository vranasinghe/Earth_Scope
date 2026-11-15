"""Worldwide location search via OpenStreetMap Nominatim.

Geocoding only converts a place name into coordinates (and coordinates into
a readable place name). NASA data is always retrieved by coordinates, so the
analysis never depends on the geocoder.

Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/)
is respected by design:

* requests go through this backend, never directly from browsers;
* at most one request per second (process-wide throttle);
* an identifying User-Agent (configurable);
* no autocomplete — the frontend searches only when the user submits;
* results are cached (searches and reverse lookups) to avoid repeats;
* attribution ("© OpenStreetMap contributors") is shown in the UI.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import requests

from app.core.config import Settings
from app.services.nasa_power import TTLCache
from app.utils.errors import GeocoderUnavailableError, InvalidRequestError

logger = logging.getLogger(__name__)

# "40.7128, -74.0060" or "40.7128 -74.0060"
_COORD_RE = re.compile(r"^\s*([-+]?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*([-+]?\d{1,3}(?:\.\d+)?)\s*$")


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` if ``text`` is a valid "lat, lon" pair, else ``None``."""
    m = _COORD_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _place_from_nominatim(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    display = str(item.get("display_name") or "")
    name = (
        item.get("name")
        or address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("state")
        or address.get("country")
        or display.split(",")[0]
    )
    region = address.get("state") or address.get("region") or address.get("county")
    return {
        "name": str(name or "Unnamed place"),
        "display_name": display,
        "country": address.get("country"),
        "country_code": (address.get("country_code") or "").upper() or None,
        "region": region if region and region != name else None,
        "place_type": item.get("addresstype") or item.get("type"),
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "source": "OpenStreetMap Nominatim",
    }


class Geocoder:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": settings.geocoder_user_agent, "Accept-Language": settings.geocoder_language}
        )
        self.cache = TTLCache(settings.geocoder_cache_ttl_seconds, 512)
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _throttled_get(self, url: str, params: dict[str, Any]) -> Any:
        # Serialise requests and keep >= min_interval between them (policy: 1 req/s).
        with self._lock:
            wait = self.settings.geocoder_min_interval_seconds - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, params=params, timeout=self.settings.geocoder_timeout_seconds)
            except requests.RequestException as exc:
                logger.warning("Geocoder network error: %s", exc)
                raise GeocoderUnavailableError(
                    "Location search is unavailable right now. You can still click the map or type coordinates."
                ) from exc
            finally:
                self._last_request = time.monotonic()
        if response.status_code == 429 or response.status_code >= 500:
            raise GeocoderUnavailableError(
                "Location search is busy right now. Please wait a moment, or click the map / type coordinates."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GeocoderUnavailableError("Location search returned an unexpected response.") from exc

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = " ".join((query or "").split())
        if len(q) < 2:
            raise InvalidRequestError("Type at least 2 characters to search.")
        if len(q) > 200:
            raise InvalidRequestError("Search text is too long (maximum 200 characters).")

        coords = parse_coordinates(q)
        if coords is not None:
            lat, lon = coords
            return [
                {
                    "name": f"{lat:.4f}, {lon:.4f}",
                    "display_name": "Coordinates entered directly",
                    "country": None,
                    "country_code": None,
                    "region": None,
                    "place_type": "coordinates",
                    "latitude": round(lat, 4),
                    "longitude": round(lon, 4),
                    "source": "Coordinates",
                }
            ]

        key = ("search", q.lower(), limit)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        body = self._throttled_get(
            self.settings.geocoder_search_url,
            {"q": q, "format": "jsonv2", "addressdetails": 1, "limit": limit},
        )
        if not isinstance(body, list):
            raise GeocoderUnavailableError("Location search returned an unexpected response.")
        places = [p for p in (_place_from_nominatim(i) for i in body if isinstance(i, dict)) if p]
        self.cache.set(key, places)
        return places

    def reverse(self, latitude: float, longitude: float) -> dict[str, Any] | None:
        """Readable name for a point, or ``None`` (e.g. open ocean)."""
        lat, lon = round(latitude, 3), round(longitude, 3)
        key = ("reverse", lat, lon)
        cached = self.cache.get(key)
        if cached is not None:
            return cached or None
        body = self._throttled_get(
            self.settings.geocoder_reverse_url,
            {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10, "addressdetails": 1},
        )
        place = _place_from_nominatim(body) if isinstance(body, dict) and "error" not in body else None
        self.cache.set(key, place or {})  # cache "no place" too, to avoid repeat lookups
        return place
