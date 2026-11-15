"""Reliability tests added during QA: caching correctness, grid-cell
reporting, unit handling and error-message hygiene. All mocked (no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_nasa_client
from app.core.catalog import get_variable
from app.core.config import get_settings
from app.main import app
from app.services import data_processing as dp
from app.services.nasa_power import NasaPowerClient
from app.utils.errors import NasaPowerResponseError
from app.utils.grid import merra2_cell
from tests.conftest import make_power_payload
from tests.test_nasa_power import FakeResponse, FakeSession


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


# --- Grid cell (centres/edges observed live from NASA POWER, see app/utils/grid.py) --

@pytest.mark.parametrize(
    "lat,lon,centre",
    [
        (40.26, -74.00, (40.5, -73.75)),
        (40.74, -73.70, (40.5, -73.75)),   # same cell as above (identical NASA values)
        (40.24, -74.00, (40.0, -73.75)),   # across the 40.25° latitude edge
        (40.74, -74.30, (40.5, -74.375)),  # across the -74.0625° longitude edge
        (0.0, 180.0, (0.0, -180.0)),       # +180 is the same meridian as -180
        (0.0, -180.0, (0.0, -180.0)),
        (90.0, 0.0, (90.0, 0.0)),
        (-89.9, 10.0, (-90.0, 10.0)),
    ],
)
def test_merra2_cell_centres(lat, lon, centre):
    cell = merra2_cell(lat, lon)
    assert (cell["center_latitude"], cell["center_longitude"]) == centre
    assert cell["lat_min"] <= lat <= cell["lat_max"] or abs(lat) == 90


def test_metadata_reports_grid_cell_and_echoed_point():
    payload = make_power_payload(start_year=2001, end_year=2012)
    payload["geometry"]["coordinates"] = [-74.006, 40.713, 10.17]
    nasa = NasaPowerClient(get_settings(), session=FakeSession(FakeResponse(200, payload)))
    app.dependency_overrides[get_nasa_client] = lambda: nasa
    m = TestClient(app).get("/api/analyze", params={"variable": "T2M", "latitude": 40.7128, "longitude": -74.006,
                                                     "start_year": 2001, "end_year": 2012}).json()["metadata"]
    assert m["latitude_returned"] == pytest.approx(40.713)
    assert m["grid_cell"]["center_latitude"] == 40.5 and m["grid_cell"]["center_longitude"] == -73.75


# --- Caching ------------------------------------------------------------------------

def test_200_error_payload_is_not_cached(settings):
    t2m = get_variable("T2M")
    session = FakeSession(FakeResponse(200, {"messages": ["temporary problem"], "header": "failed"}))
    client = NasaPowerClient(settings, session=session)
    for _ in range(2):
        payload = client.fetch_monthly(t2m, 1, 1, 2001, 2012).payload
        with pytest.raises(NasaPowerResponseError):
            dp.parse_power_response(payload, t2m, 2001, 2012)
    assert len(session.calls) == 2, "an error payload must be re-requested, not served from cache"
    assert len(client.cache) == 0


def test_cache_entries_are_isolated_by_every_input(settings):
    session = FakeSession(FakeResponse(200, make_power_payload()))
    client = NasaPowerClient(settings, session=session)
    t2m, rh = get_variable("T2M"), get_variable("RH2M")
    client.fetch_monthly(t2m, 10, 20, 2001, 2012)
    client.fetch_monthly(rh, 10, 20, 2001, 2012)       # different variable
    client.fetch_monthly(t2m, 10, 20, 2002, 2012)      # different start
    client.fetch_monthly(t2m, 10, 20, 2001, 2013)      # different end
    client.fetch_monthly(t2m, -10, 20, 2001, 2012)     # different hemisphere
    client.fetch_monthly(t2m, 10, -20, 2001, 2012)
    assert len(session.calls) == 6
    again = client.fetch_monthly(rh, 10, 20, 2001, 2012)
    assert again.from_cache and len(session.calls) == 6
    assert session.calls[1]["params"]["parameters"] == "RH2M"


# --- Units --------------------------------------------------------------------------

def test_unexpected_units_do_not_trigger_wrong_range_rejection():
    # If NASA ever reported Kelvin, the °C physical range must not discard every value.
    payload = make_power_payload(units="K", value_fn=lambda y, m: 290.0 + m)
    parsed = dp.parse_power_response(payload, get_variable("T2M"), 2001, 2012)
    assert (parsed.monthly["status"] == "valid").all()
    assert any("differs" in w for w in parsed.warnings)


# --- Error hygiene ------------------------------------------------------------------

def test_unexpected_server_errors_do_not_leak_internals(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("SECRET internal path C:/secret/file.py")

    monkeypatch.setattr("app.api.routes.analysis.build_analysis_response", boom)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/analyze", params={"variable": "T2M", "latitude": 1, "longitude": 1})
    assert r.status_code == 500
    assert "SECRET" not in r.text and "secret" not in r.text
    assert r.json()["error"] == "INTERNAL_ERROR"


def test_constant_series_reports_no_variation_code_not_significance():
    payload = make_power_payload(start_year=2001, end_year=2012, value_fn=lambda y, m: 21.0)
    nasa = NasaPowerClient(get_settings(), session=FakeSession(FakeResponse(200, payload)))
    app.dependency_overrides[get_nasa_client] = lambda: nasa
    body = TestClient(app).get("/api/analyze", params={"variable": "T2M", "latitude": 5, "longitude": 5,
                                                        "start_year": 2001, "end_year": 2012}).json()
    assert body["statistics"] is None
    assert body["analysis_error"] == "NO_VARIATION_IN_DATA"
    assert "significant" not in body["interpretation"]["headline"].lower()
