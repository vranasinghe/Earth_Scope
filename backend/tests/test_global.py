"""Global coverage tests: locations on every continent, both hemispheres,
the equator, polar regions and the International Date Line, plus invalid
coordinates, location search and multi-location comparison.

NASA POWER and Nominatim are mocked here (no network). See
``scripts/live_smoke_test.py`` for the equivalent live checks.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.deps import get_geocoder, get_nasa_client
from app.core.config import Settings, get_settings
from app.main import app
from app.services.geocoding import Geocoder, parse_coordinates
from app.services.nasa_power import NasaPowerClient
from app.utils.errors import GeocoderUnavailableError, InvalidRequestError
from tests.conftest import make_power_payload

GLOBAL_LOCATIONS = [
    ("Colombo", 6.9271, 79.8612),
    ("New York", 40.7128, -74.0060),
    ("London", 51.5072, -0.1276),
    ("Tokyo", 35.6762, 139.6503),
    ("Nairobi", -1.2921, 36.8219),
    ("Sydney", -33.8688, 151.2093),
    ("São Paulo", -23.5505, -46.6333),
    ("Reykjavik", 64.1466, -21.9426),
]
EDGE_LOCATIONS = [
    ("Equator / prime meridian", 0.0, 0.0),
    ("Date line east", -17.7, 179.99),
    ("Date line west", -17.7, -179.99),
    ("Longitude +180", 10.0, 180.0),
    ("Longitude -180", 10.0, -180.0),
    ("North Pole", 90.0, 0.0),
    ("South Pole", -90.0, 0.0),
]


class RecordingSession:
    """Fake requests.Session for NASA POWER: echoes the requested point back."""

    def __init__(self, value_fn=None, parameter="T2M", units="C"):
        self.calls: list[dict] = []
        self.headers: dict = {}
        self.value_fn = value_fn
        self.parameter = parameter
        self.units = units

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        payload = make_power_payload(
            parameter=params["parameters"],
            units=self.units,
            start_year=int(params["start"]),
            end_year=int(params["end"]),
            value_fn=self.value_fn,
        )
        payload["geometry"]["coordinates"] = [float(params["longitude"]), float(params["latitude"]), 10.0]

        class R:
            status_code = 200

            def json(self_inner):
                return payload

        return R()


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def client_with_nasa(session) -> TestClient:
    nasa = NasaPowerClient(get_settings(), session=session)
    app.dependency_overrides[get_nasa_client] = lambda: nasa
    return TestClient(app)


def trend_values(y, m):
    return 15 + 0.04 * (y - 2001) + 3 * ((m % 12) / 12)


# --- Every continent / hemisphere -------------------------------------------------

@pytest.mark.parametrize("name,lat,lon", GLOBAL_LOCATIONS + EDGE_LOCATIONS)
def test_analysis_works_worldwide_and_uses_selected_coordinates(name, lat, lon):
    session = RecordingSession(value_fn=trend_values)
    c = client_with_nasa(session)
    r = c.get("/api/analyze", params={"variable": "T2M", "latitude": lat, "longitude": lon,
                                       "start_year": 2001, "end_year": 2015})
    assert r.status_code == 200, (name, r.json())
    body = r.json()
    # The NASA request used exactly the user's coordinates (nothing hard-coded).
    sent = session.calls[0]
    assert float(sent["latitude"]) == pytest.approx(lat)
    assert float(sent["longitude"]) == pytest.approx(lon)
    assert sent["parameters"] == "T2M" and sent["community"] == "AG"
    # Requested and returned grid coordinates are both reported.
    m = body["metadata"]
    assert m["latitude_requested"] == pytest.approx(lat)
    assert m["longitude_requested"] == pytest.approx(lon)
    assert m["latitude_returned"] == pytest.approx(lat)
    # Statistics computed with the known synthetic slope.
    assert body["statistics"]["regression"]["slope"] == pytest.approx(0.04, rel=1e-6)
    assert len(body["monthly"]) == 15 * 12


@pytest.mark.parametrize("lat,lon", [(95, 0), (-95, 0), (0, 200), (0, -200), (90.0001, 0), (0, 180.5)])
def test_out_of_range_coordinates_are_rejected_without_calling_nasa(lat, lon):
    session = RecordingSession()
    c = client_with_nasa(session)
    r = c.get("/api/analyze", params={"variable": "T2M", "latitude": lat, "longitude": lon})
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_COORDINATES"
    assert session.calls == []


def test_soil_wetness_over_water_returns_location_not_supported_with_suggestions():
    session = RecordingSession(value_fn=lambda y, m: 1.0, parameter="GWETTOP", units="1")
    c = client_with_nasa(session)
    r = c.get("/api/analyze", params={"variable": "soil_wetness", "latitude": 0, "longitude": -140,
                                       "start_year": 2001, "end_year": 2015})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "LOCATION_NOT_SUPPORTED"
    assert body["suggested_variables"] == ["air_temperature", "relative_humidity"]


def test_all_missing_values_return_no_valid_data():
    c = client_with_nasa(RecordingSession(value_fn=lambda y, m: -999.0))
    r = c.get("/api/analyze", params={"variable": "T2M", "latitude": 10, "longitude": 10})
    assert r.status_code == 404 and r.json()["error"] == "NO_VALID_DATA"


def test_variables_expose_availability_metadata():
    body = TestClient(app).get("/api/variables").json()
    soil = next(v for v in body["variables"] if v["parameter"] == "GWETTOP")
    assert soil["land_only"] is True
    assert soil["alternatives"] == ["air_temperature", "relative_humidity"]
    for v in body["variables"]:
        assert v["supported_communities"] == ["AG", "RE", "SB"]
        assert "monthly" in v["available_temporal_resolutions"]
        assert v["coverage_start_year"] == 1981
        assert v["community"] in v["supported_communities"]


# --- Location search (geocoding) ---------------------------------------------------

class FakeGeoSession:
    def __init__(self, body=None, status=200, exc=None):
        self.body, self.status, self.exc = body, status, exc
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        if self.exc:
            raise self.exc
        body, status = self.body, self.status

        class R:
            status_code = status

            def json(self_inner):
                return body

        return R()


NOMINATIM_TOKYO = [
    {"lat": "35.6768601", "lon": "139.7638947", "name": "Tokyo", "display_name": "Tokyo, Japan",
     "addresstype": "city", "address": {"city": "Tokyo", "country": "Japan", "country_code": "jp"}},
    {"lat": "bad", "lon": "x"},  # malformed entries are skipped
]


def fast_settings(**kw) -> Settings:
    return Settings(_env_file=None, geocoder_min_interval_seconds=0.0, **kw)


@pytest.mark.parametrize(
    "text,expected",
    [("40.7128, -74.0060", (40.7128, -74.006)), ("-33.8688 151.2093", (-33.8688, 151.2093)),
     ("6.9271,79.8612", (6.9271, 79.8612)), ("95, 10", None), ("10, 200", None), ("Tokyo", None)],
)
def test_parse_coordinates(text, expected):
    assert parse_coordinates(text) == expected


def test_geocoder_search_parses_caches_and_identifies_itself():
    session = FakeGeoSession(NOMINATIM_TOKYO)
    geo = Geocoder(fast_settings(), session=session)
    first = geo.search("Tokyo, Japan")
    second = geo.search("  tokyo,   JAPAN ")
    assert len(session.calls) == 1, "normalised repeat query must be served from cache"
    assert first == second
    assert first[0]["country"] == "Japan" and first[0]["country_code"] == "JP"
    assert first[0]["latitude"] == pytest.approx(35.6769)
    assert len(first) == 1
    assert "EarthScope" in session.headers["User-Agent"]
    assert session.calls[0][1]["format"] == "jsonv2"


def test_geocoder_coordinates_skip_the_network():
    session = FakeGeoSession(NOMINATIM_TOKYO)
    result = Geocoder(fast_settings(), session=session).search("-1.2921, 36.8219")
    assert session.calls == []
    assert result[0]["place_type"] == "coordinates"


def test_geocoder_reverse_over_ocean_returns_none_and_is_cached():
    session = FakeGeoSession({"error": "Unable to geocode"})
    geo = Geocoder(fast_settings(), session=session)
    assert geo.reverse(0, -140) is None
    assert geo.reverse(0, -140) is None
    assert len(session.calls) == 1


def test_geocoder_throttles_to_one_request_per_interval(monkeypatch):
    sleeps: list[float] = []
    clock = [100.0]
    monkeypatch.setattr("app.services.geocoding.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.services.geocoding.time.sleep", lambda s: sleeps.append(s))
    geo = Geocoder(Settings(_env_file=None, geocoder_min_interval_seconds=1.0), session=FakeGeoSession([]))
    geo.search("Lima")
    clock[0] += 0.25
    geo.search("Oslo")
    assert sleeps and sleeps[-1] == pytest.approx(0.75)


@pytest.mark.parametrize("session", [FakeGeoSession(status=429), FakeGeoSession(exc=requests.ConnectionError("x"))])
def test_geocoder_failures_raise_unavailable(session):
    with pytest.raises(GeocoderUnavailableError):
        Geocoder(fast_settings(), session=session).search("Paris")


def test_geocoder_rejects_too_short_queries():
    with pytest.raises(InvalidRequestError):
        Geocoder(fast_settings(), session=FakeGeoSession([])).search("a")


def test_geocode_endpoints():
    geo = Geocoder(fast_settings(), session=FakeGeoSession(NOMINATIM_TOKYO))
    app.dependency_overrides[get_geocoder] = lambda: geo
    c = TestClient(app)
    r = c.get("/api/geocode/search", params={"q": "Tokyo"})
    assert r.status_code == 200
    assert r.json()["results"][0]["name"] == "Tokyo"
    assert "OpenStreetMap" in r.json()["attribution"]
    bad = c.get("/api/geocode/reverse", params={"latitude": 95, "longitude": 0})
    assert bad.status_code == 422 and bad.json()["error"] == "INVALID_COORDINATES"


# --- Multi-location comparison -----------------------------------------------------

def test_compare_three_locations_sequentially():
    session = RecordingSession(value_fn=trend_values)
    c = client_with_nasa(session)
    r = c.get("/api/compare", params={
        "variable": "T2M",
        "locations": "40.7128,-74.006;35.6762,139.6503;-33.8688,151.2093",
        "labels": "New York;Tokyo;Sydney",
        "start_year": 2001, "end_year": 2015,
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    assert [loc["label"] for loc in body["locations"]] == ["New York", "Tokyo", "Sydney"]
    assert all(loc["ok"] for loc in body["locations"])
    assert len(session.calls) == 3
    assert [float(call["longitude"]) for call in session.calls] == [-74.006, 139.6503, 151.2093]
    assert all(loc["statistics"]["regression"]["slope"] == pytest.approx(0.04, rel=1e-6) for loc in body["locations"])
    assert body["unit_display"] == "°C" and body["start_year"] == 2001
    assert any("rates of change" in cv for cv in body["summary"]["caveats"])
    assert len(body["summary"]["lines"]) >= 4


def test_compare_reports_failure_per_location_without_failing_others():
    # Soil wetness constant 1.0 for the second (ocean) point only.
    def values(y, m):
        return 0.5 + 0.002 * (y - 2001) + 0.05 * (m % 3)

    class Mixed(RecordingSession):
        def get(self, url, params=None, timeout=None):
            self.value_fn = (lambda y, m: 1.0) if float(params["longitude"]) == -140 else values
            return super().get(url, params, timeout)

    c = client_with_nasa(Mixed(parameter="GWETTOP", units="1"))
    body = c.get("/api/compare", params={"variable": "soil_wetness", "locations": "-1.29,36.82;0,-140",
                                          "start_year": 2001, "end_year": 2015}).json()
    ok, ocean = body["locations"]
    assert ok["ok"] and ok["statistics"] is not None
    assert not ocean["ok"] and ocean["error"]["error"] == "LOCATION_NOT_SUPPORTED"
    assert any("could not be analysed" in line for line in body["summary"]["lines"])


@pytest.mark.parametrize(
    "locations,code",
    [
        ("40.7,-74.0", "INVALID_REQUEST"),                              # only one
        ("1,1;2,2;3,3;4,4", "INVALID_REQUEST"),                         # too many
        ("1,1;1,1", "INVALID_REQUEST"),                                 # duplicate
        ("95,0;1,1", "INVALID_COORDINATES"),                            # invalid latitude
        ("abc;1,1", "INVALID_COORDINATES"),                             # malformed
    ],
)
def test_compare_validation(locations, code):
    session = RecordingSession()
    c = client_with_nasa(session)
    r = c.get("/api/compare", params={"variable": "T2M", "locations": locations})
    assert r.status_code == 422 and r.json()["error"] == code
    assert session.calls == []


def test_request_query_string_for_new_york_matches_documented_structure():
    session = RecordingSession(value_fn=trend_values)
    client = NasaPowerClient(get_settings(), session=session)
    from app.core.catalog import get_variable

    url = client.build_url(get_variable("T2M"), 40.7128, -74.0060, 2001, 2025)
    qs = {k: v[0] for k, v in parse_qs(url.split("?", 1)[1]).items()}
    assert qs == {"parameters": "T2M", "community": "AG", "longitude": "-74.0060", "latitude": "40.7128",
                  "start": "2001", "end": "2025", "format": "JSON"}
