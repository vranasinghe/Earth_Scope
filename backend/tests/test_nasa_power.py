"""Tests for the NASA POWER client: URL construction, caching and error mapping.

A fake ``requests`` session is used so no network access is needed.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app.core.catalog import VARIABLES, get_variable
from app.services.nasa_power import NasaPowerClient, TTLCache
from app.utils.errors import (
    InvalidRequestError,
    LocationNotSupportedError,
    NasaPowerResponseError,
    NasaPowerUnavailableError,
    TemporalRangeError,
    UnsupportedVariableError,
    nasa_rejection,
)
from tests.conftest import make_power_payload


class FakeResponse:
    def __init__(self, status_code=200, body=None, raise_json=False):
        self.status_code = status_code
        self._body = body
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.response


def test_catalogue_uses_valid_communities_and_monthly_params():
    # Verified against NASA's parameter manager: AG/RE/SB only; HY is rejected.
    for v in VARIABLES:
        assert v.community in {"AG", "RE", "SB"}
    assert {v.parameter for v in VARIABLES} == {"T2M", "RH2M", "GWETTOP"}
    assert get_variable("t2m").id == "air_temperature"
    assert get_variable("soil_wetness").parameter == "GWETTOP"
    assert get_variable("nope") is None


def test_build_url_contains_all_required_parameters(settings, t2m):
    client = NasaPowerClient(settings, session=FakeSession())
    url = client.build_url(t2m, 6.9271, 79.8612, 2001, 2025)
    parsed = urlparse(url)
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert url.startswith("https://power.larc.nasa.gov/api/temporal/monthly/point?")
    assert qs == {
        "parameters": "T2M",
        "community": "AG",
        "longitude": "79.8612",
        "latitude": "6.9271",
        "start": "2001",
        "end": "2025",
        "format": "JSON",
    }


def test_successful_fetch_and_cache_hit(settings, t2m):
    session = FakeSession(FakeResponse(200, make_power_payload()))
    client = NasaPowerClient(settings, session=session)
    first = client.fetch_monthly(t2m, 6.9271, 79.8612, 2001, 2012)
    second = client.fetch_monthly(t2m, 6.9271, 79.8612, 2001, 2012)
    assert first.from_cache is False
    assert second.from_cache is True
    assert len(session.calls) == 1, "identical request should be served from cache"
    assert session.calls[0]["timeout"] == settings.nasa_timeout_seconds
    assert second.retrieved_at == first.retrieved_at
    # A different location is a different cache entry.
    client.fetch_monthly(t2m, 7.0, 80.0, 2001, 2012)
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "exc",
    [requests.Timeout("slow"), requests.ConnectionError("down")],
)
def test_network_failures_are_unavailable_and_retryable(settings, t2m, exc):
    client = NasaPowerClient(settings, session=FakeSession(exc=exc))
    with pytest.raises(NasaPowerUnavailableError) as info:
        client.fetch_monthly(t2m, 0, 0, 2001, 2012)
    assert info.value.retryable is True
    assert info.value.status_code == 503
    assert info.value.error == "NASA_API_UNAVAILABLE"


def test_nasa_422_messages_are_passed_through_and_classified(settings, t2m):
    body = {"header": "failed", "messages": ["Please provide a correct latitude value."]}
    client = NasaPowerClient(settings, session=FakeSession(FakeResponse(422, body)))
    with pytest.raises(LocationNotSupportedError) as info:
        client.fetch_monthly(t2m, 0, 0, 2001, 2012)
    assert info.value.details == ["Please provide a correct latitude value."]
    assert info.value.error == "LOCATION_NOT_SUPPORTED"


@pytest.mark.parametrize(
    "message,cls,code",
    [
        ("Please provide a correct longitude value.", LocationNotSupportedError, "LOCATION_NOT_SUPPORTED"),
        ("Your start date out of range. The data starts at 1981/01/01.", TemporalRangeError, "TEMPORAL_RANGE_UNAVAILABLE"),
        ("Please provide a correct user community value.", UnsupportedVariableError, "PARAMETER_NOT_AVAILABLE"),
        ("Something unexpected", InvalidRequestError, "INVALID_REQUEST"),
    ],
)
def test_nasa_rejection_classification(message, cls, code):
    err = nasa_rejection([message])
    assert isinstance(err, cls) and err.error == code and err.details == [message]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_errors_and_rate_limits_are_unavailable(settings, t2m, status):
    client = NasaPowerClient(settings, session=FakeSession(FakeResponse(status, None, raise_json=True)))
    with pytest.raises(NasaPowerUnavailableError):
        client.fetch_monthly(t2m, 0, 0, 2001, 2012)


def test_non_json_success_is_unexpected_response(settings, t2m):
    client = NasaPowerClient(settings, session=FakeSession(FakeResponse(200, None, raise_json=True)))
    with pytest.raises(NasaPowerResponseError):
        client.fetch_monthly(t2m, 0, 0, 2001, 2012)


def test_failed_requests_are_not_cached(settings, t2m):
    session = FakeSession(exc=requests.Timeout("slow"))
    client = NasaPowerClient(settings, session=session)
    for _ in range(2):
        with pytest.raises(NasaPowerUnavailableError):
            client.fetch_monthly(t2m, 0, 0, 2001, 2012)
    assert len(session.calls) == 2
    assert len(client.cache) == 0


def test_ttl_cache_expiry_and_lru_eviction(monkeypatch):
    cache = TTLCache(ttl_seconds=10, max_entries=2)
    now = [1000.0]
    monkeypatch.setattr("app.services.nasa_power.time.monotonic", lambda: now[0])
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") == 2
    now[0] += 11
    assert cache.get("b") is None  # expired
