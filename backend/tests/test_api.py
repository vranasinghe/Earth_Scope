"""API-level tests with the NASA client replaced by a fake (no network)."""

from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.deps import get_nasa_client
from app.core.config import get_settings
from app.main import app
from app.services.nasa_power import NasaPowerClient
from tests.conftest import make_power_payload
from tests.test_nasa_power import FakeResponse, FakeSession


def client_with(session) -> TestClient:
    nasa = NasaPowerClient(get_settings(), session=session)
    app.dependency_overrides[get_nasa_client] = lambda: nasa
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def increasing_payload():
    return make_power_payload(
        start_year=2001, end_year=2015, value_fn=lambda y, m: 25 + 0.05 * (y - 2001) + (m % 3) * 0.1
    )


def test_health_and_variables():
    c = TestClient(app)
    assert c.get("/api/health").json()["status"] == "ok"
    body = c.get("/api/variables").json()
    assert [v["parameter"] for v in body["variables"]] == ["T2M", "RH2M", "GWETTOP"]
    assert body["min_year"] == 1981
    assert body["significance_alpha"] == 0.05


def test_analyze_returns_full_live_result():
    c = client_with(FakeSession(FakeResponse(200, increasing_payload())))
    r = c.get("/api/analyze", params={"variable": "air_temperature", "latitude": 6.9271,
                                       "longitude": 79.8612, "start_year": 2001, "end_year": 2015})
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["data_mode"] == "LIVE"
    assert body["metadata"]["units_raw"] == "C"
    assert body["metadata"]["request_url"].startswith("https://power.larc.nasa.gov/")
    assert len(body["monthly"]) == 15 * 12
    assert len(body["annual"]) == 15
    s = body["statistics"]
    assert s["regression"]["slope"] == pytest.approx(0.05, rel=1e-6)
    assert s["sens_slope"]["slope"] == pytest.approx(0.05, rel=1e-6)
    assert s["evidence"]["category"] == "significant_increasing"
    assert body["interpretation"]["paragraphs"]


def test_data_endpoint_has_no_statistics():
    c = client_with(FakeSession(FakeResponse(200, increasing_payload())))
    body = c.get("/api/data", params={"variable": "T2M", "latitude": 6.9, "longitude": 79.8,
                                       "start_year": 2001, "end_year": 2015}).json()
    assert "statistics" not in body and "_annual_df" not in body
    assert body["summary"]["n_monthly_valid"] == 180


def test_insufficient_valid_years_returns_data_without_statistics():
    # Only 5 of 12 years have data -> trend tests cannot run, data is still returned.
    payload = make_power_payload(start_year=2001, end_year=2012,
                                 value_fn=lambda y, m: 20.0 + m if y <= 2005 else -999.0)
    c = client_with(FakeSession(FakeResponse(200, payload)))
    body = c.get("/api/analyze", params={"variable": "T2M", "latitude": 1, "longitude": 1,
                                          "start_year": 2001, "end_year": 2012}).json()
    assert body["statistics"] is None
    assert "at least 10" in body["analysis_message"]
    assert body["analysis_error"] == "INSUFFICIENT_DATA_FOR_ANALYSIS"
    assert body["summary"]["n_annual_used"] == 5


@pytest.mark.parametrize(
    "params,status,error",
    [
        ({"variable": "XYZ", "latitude": 1, "longitude": 1}, 404, "PARAMETER_NOT_AVAILABLE"),
        ({"variable": "T2M", "latitude": 91, "longitude": 1}, 422, "INVALID_COORDINATES"),
        ({"variable": "T2M", "latitude": 1, "longitude": -181}, 422, "INVALID_COORDINATES"),
        ({"variable": "T2M", "latitude": "abc", "longitude": 1}, 422, "INVALID_COORDINATES"),
        ({"variable": "T2M", "latitude": 1, "longitude": 1, "start_year": 2015, "end_year": 2010}, 422, "TEMPORAL_RANGE_UNAVAILABLE"),
        ({"variable": "T2M", "latitude": 1, "longitude": 1, "start_year": 2018, "end_year": 2022}, 422, "TEMPORAL_RANGE_UNAVAILABLE"),
        ({"variable": "T2M", "latitude": 1, "longitude": 1, "start_year": 1970, "end_year": 2000}, 422, "TEMPORAL_RANGE_UNAVAILABLE"),
        ({"latitude": 1, "longitude": 1}, 422, "INVALID_REQUEST"),
    ],
)
def test_invalid_inputs(params, status, error):
    c = client_with(FakeSession(FakeResponse(200, increasing_payload())))
    r = c.get("/api/analyze", params=params)
    assert r.status_code == status
    assert r.json()["error"] == error
    assert r.json()["message"]


def test_nasa_outage_is_503_and_retryable_never_synthetic():
    c = client_with(FakeSession(exc=requests.ConnectionError("down")))
    r = c.get("/api/analyze", params={"variable": "T2M", "latitude": 1, "longitude": 1})
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "NASA_API_UNAVAILABLE"
    assert body["retryable"] is True
    assert "statistics" not in body  # no silent fallback to synthetic data


