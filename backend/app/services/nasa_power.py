"""NASA POWER monthly point API client.

Responsibilities:
* build the request URL from the variable catalogue entry and user inputs;
* call the API with a timeout;
* translate network / HTTP failures into ``EarthScopeError`` subclasses;
* cache successful raw JSON responses in memory (historical monthly data does
  not change between requests, so repeated identical requests are served
  locally).

Parsing of the JSON into time series lives in ``data_processing``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from app.core.catalog import VariableDefinition
from app.core.config import Settings
from app.utils.errors import (
    NasaPowerResponseError,
    NasaPowerUnavailableError,
    nasa_rejection,
)

logger = logging.getLogger(__name__)


@dataclass
class PowerFetchResult:
    payload: dict[str, Any]
    request_url: str
    retrieved_at: str
    from_cache: bool


class TTLCache:
    """Small thread-safe in-memory LRU cache with time-to-live."""

    def __init__(self, ttl_seconds: int, max_entries: int):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            stored_at, value = item
            if time.monotonic() - stored_at > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class NasaPowerClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "EarthScope/0.1 (educational trend analysis)"})
        self.cache = TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)

    def build_params(
        self,
        variable: VariableDefinition,
        latitude: float,
        longitude: float,
        start_year: int,
        end_year: int,
    ) -> dict[str, str]:
        return {
            "parameters": variable.parameter,
            "community": variable.community,
            "longitude": f"{longitude:.4f}",
            "latitude": f"{latitude:.4f}",
            "start": str(start_year),
            "end": str(end_year),
            "format": "JSON",
        }

    def build_url(self, *args: Any, **kwargs: Any) -> str:
        params = self.build_params(*args, **kwargs)
        return f"{self.settings.nasa_power_monthly_url}?{urlencode(params)}"

    def fetch_monthly(
        self,
        variable: VariableDefinition,
        latitude: float,
        longitude: float,
        start_year: int,
        end_year: int,
    ) -> PowerFetchResult:
        params = self.build_params(variable, latitude, longitude, start_year, end_year)
        url = f"{self.settings.nasa_power_monthly_url}?{urlencode(params)}"
        # Key = endpoint (temporal resolution) + every request input. Only successful
        # responses are stored, so failures are never served from the cache.
        cache_key = (self.settings.nasa_power_monthly_url, *sorted(params.items()))

        cached = self.cache.get(cache_key)
        if cached is not None:
            payload, retrieved_at = cached
            return PowerFetchResult(payload, url, retrieved_at, from_cache=True)

        try:
            response = self.session.get(
                self.settings.nasa_power_monthly_url,
                params=params,
                timeout=self.settings.nasa_timeout_seconds,
            )
        except requests.Timeout as exc:
            logger.warning("NASA POWER timeout: %s", exc)
            raise NasaPowerUnavailableError(
                "NASA POWER did not respond in time. The service may be busy — please try again.",
            ) from exc
        except requests.RequestException as exc:
            logger.warning("NASA POWER network error: %s", exc)
            raise NasaPowerUnavailableError(
                "Could not connect to NASA POWER. Check your internet connection and try again.",
            ) from exc

        payload = self._decode(response)
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Only cache genuine datasets. A 200 response without time-series data
        # (e.g. an error message payload) must not be served again from the cache.
        properties = payload.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("parameter"), dict):
            self.cache.set(cache_key, (payload, retrieved_at))
        return PowerFetchResult(payload, url, retrieved_at, from_cache=False)

    def fetch_regional(
        self,
        variable: VariableDefinition,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        start_year: int,
        end_year: int,
    ) -> PowerFetchResult:
        """Monthly REGIONAL request (one parameter per request, as NASA requires)."""
        params = {
            "parameters": variable.parameter,
            "community": variable.community,
            "latitude-min": f"{lat_min:.4f}",
            "latitude-max": f"{lat_max:.4f}",
            "longitude-min": f"{lon_min:.4f}",
            "longitude-max": f"{lon_max:.4f}",
            "start": str(start_year),
            "end": str(end_year),
            "format": "JSON",
        }
        url = f"{self.settings.nasa_power_regional_url}?{urlencode(params)}"
        cache_key = (self.settings.nasa_power_regional_url, *sorted(params.items()))
        cached = self.cache.get(cache_key)
        if cached is not None:
            payload, retrieved_at = cached
            return PowerFetchResult(payload, url, retrieved_at, from_cache=True)
        try:
            response = self.session.get(
                self.settings.nasa_power_regional_url,
                params=params,
                timeout=self.settings.nasa_regional_timeout_seconds,
            )
        except requests.Timeout as exc:
            logger.warning("NASA POWER regional timeout: %s", exc)
            raise NasaPowerUnavailableError(
                "NASA POWER did not respond in time to the regional request. Please try again, or select a smaller region.",
            ) from exc
        except requests.RequestException as exc:
            logger.warning("NASA POWER regional network error: %s", exc)
            raise NasaPowerUnavailableError(
                "Could not connect to NASA POWER. Check your internet connection and try again.",
            ) from exc
        payload = self._decode(response)
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Cache only genuine gridded datasets, never error payloads.
        if isinstance(payload.get("features"), list) and payload["features"]:
            self.cache.set(cache_key, (payload, retrieved_at))
        return PowerFetchResult(payload, url, retrieved_at, from_cache=False)

    @staticmethod
    def _messages(body: Any) -> list[str]:
        if isinstance(body, dict):
            msgs = body.get("messages") or body.get("errors") or []
            if isinstance(msgs, str):
                msgs = [msgs]
            if isinstance(msgs, list):
                return [str(m) for m in msgs if m][:10]
        return []

    def _decode(self, response: requests.Response) -> dict[str, Any]:
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None

        if status == 429:
            exc = NasaPowerUnavailableError(
                "NASA POWER is rate-limiting requests right now. Please wait a minute and try again."
            )
            exc.http_status, exc.retry_after = status, _retry_after(response)
            raise exc
        if status >= 500:
            logger.warning("NASA POWER server error %s", status)
            exc = NasaPowerUnavailableError(
                f"NASA POWER returned a server error (HTTP {status}). Please try again later."
            )
            exc.http_status, exc.retry_after = status, _retry_after(response)
            raise exc
        if 400 <= status < 500:
            # Classified into LOCATION_NOT_SUPPORTED / TEMPORAL_RANGE_UNAVAILABLE / ...
            raise nasa_rejection(self._messages(body) or [f"HTTP {status}"])
        if not isinstance(body, dict):
            raise NasaPowerResponseError("NASA POWER returned a response that is not valid JSON.")
        return body


def _retry_after(response: requests.Response) -> float | None:
    """Seconds from a numeric ``Retry-After`` header (HTTP-date values are ignored), capped at 10 minutes."""
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return max(0.0, min(600.0, float(raw))) if raw is not None else None
    except (TypeError, ValueError):
        return None
