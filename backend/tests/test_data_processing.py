"""Tests for NASA response parsing, missing-value handling and annual aggregation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import data_processing as dp
from app.utils.errors import DataUnavailableError, LocationNotSupportedError, NasaPowerResponseError
from tests.conftest import make_power_payload


# --- Date / key parsing -------------------------------------------------------

@pytest.mark.parametrize(
    "key,expected",
    [("200101", (2001, 1)), ("202512", (2025, 12)), ("200113", None), ("200100", None),
     ("2001-01", None), ("20011", None), ("abcdef", None), (None, None)],
)
def test_parse_period_key(key, expected):
    assert dp.parse_period_key(key) == expected


def test_monthly_dates_are_complete_and_ordered(t2m):
    parsed = dp.parse_power_response(make_power_payload(start_year=2001, end_year=2002), t2m, 2001, 2002)
    m = parsed.monthly
    assert len(m) == 24
    assert m["date"].iloc[0] == "2001-01"
    assert m["date"].iloc[-1] == "2002-12"
    assert list(m["month"].iloc[:12]) == list(range(1, 13))
    assert pd.to_datetime(m["date"], format="%Y-%m").is_monotonic_increasing


# --- Response parsing -----------------------------------------------------------

def test_annual_key_13_is_never_treated_as_a_month(t2m):
    parsed = dp.parse_power_response(make_power_payload(), t2m, 2001, 2012)
    assert (parsed.monthly["value"] != 12345.0).all()
    assert len(parsed.monthly) == 12 * 12


def test_metadata_is_extracted(t2m):
    meta = dp.parse_power_response(make_power_payload(), t2m, 2001, 2012).metadata
    assert meta.units_raw == "C"
    assert meta.sources == ["MERRA2"]
    assert meta.fill_value == -999.0
    assert meta.latitude == pytest.approx(6.927)
    assert meta.longitude == pytest.approx(79.861)
    assert meta.elevation_m == pytest.approx(123.66)
    assert meta.api_version == "v2.10.0"
    assert meta.long_name == "Test Parameter"


def test_fill_values_become_missing_never_zero(t2m):
    payload = make_power_payload(overrides={"200103": -999.0, "200104": -999, "200105": "bad", "200106": None})
    m = dp.parse_power_response(payload, t2m, 2001, 2012).monthly
    gaps = m[m["date"].isin(["2001-03", "2001-04", "2001-05", "2001-06"])]
    assert (gaps["status"] == "missing").all()
    assert gaps["value"].isna().all()
    assert not (m["value"] == 0).any()


def test_months_absent_from_response_are_explicit_gaps(t2m):
    payload = make_power_payload(end_year=2012)
    del payload["properties"]["parameter"]["T2M"]["201212"]
    m = dp.parse_power_response(payload, t2m, 2001, 2012).monthly
    last = m[m["date"] == "2012-12"].iloc[0]
    assert last["status"] == "missing" and pd.isna(last["value"])


def test_physically_invalid_values_are_flagged(t2m):
    payload = make_power_payload(overrides={"200107": 150.0})
    parsed = dp.parse_power_response(payload, t2m, 2001, 2012)
    row = parsed.monthly[parsed.monthly["date"] == "2001-07"].iloc[0]
    assert row["status"] == "invalid" and pd.isna(row["value"])
    assert any("physically valid range" in w for w in parsed.warnings)


def test_missing_parameter_raises_data_unavailable(t2m):
    payload = make_power_payload(parameter="RH2M", units="%")
    with pytest.raises(DataUnavailableError):
        dp.parse_power_response(payload, t2m, 2001, 2012)


def test_all_missing_raises_data_unavailable(t2m):
    payload = make_power_payload(value_fn=lambda y, m: -999.0)
    with pytest.raises(DataUnavailableError):
        dp.parse_power_response(payload, t2m, 2001, 2012)


def test_error_payload_without_properties(t2m):
    payload = {"header": "failed", "messages": ["Something went wrong"]}
    with pytest.raises(NasaPowerResponseError) as info:
        dp.parse_power_response(payload, t2m, 2001, 2012)
    assert info.value.details == ["Something went wrong"]


def test_unit_warnings(t2m):
    missing = dp.parse_power_response(make_power_payload(units=None), t2m, 2001, 2012)
    assert missing.metadata.units_raw is None
    assert any("did not report units" in w for w in missing.warnings)
    different = dp.parse_power_response(make_power_payload(units="K"), t2m, 2001, 2012)
    assert any("differs" in w for w in different.warnings)


def test_constant_soil_wetness_over_water_or_ice_is_refused(gwettop):
    # NASA POWER reports GWETTOP = 1.0 over oceans, lakes and ice sheets (verified live).
    payload = make_power_payload(parameter="GWETTOP", units="1", value_fn=lambda y, m: 1.0)
    with pytest.raises(LocationNotSupportedError) as info:
        dp.parse_power_response(payload, gwettop, 2001, 2012)
    assert info.value.error == "LOCATION_NOT_SUPPORTED"
    assert info.value.suggested_variables == ["air_temperature", "relative_humidity"]


def test_constant_temperature_is_not_refused(t2m):
    # The land-only rule applies only to land-only variables.
    parsed = dp.parse_power_response(make_power_payload(value_fn=lambda y, m: 1.0), t2m, 2001, 2012)
    assert (parsed.monthly["status"] == "valid").all()


# --- Annual aggregation -----------------------------------------------------------

def _monthly(year_values: dict[int, list[float | None]]) -> pd.DataFrame:
    rows = []
    for y, vals in year_values.items():
        for i, v in enumerate(vals, start=1):
            rows.append({"date": f"{y}-{i:02d}", "year": y, "month": i, "value": v,
                         "status": "valid" if v is not None else "missing"})
    return pd.DataFrame(rows)


def test_annual_mean_is_day_weighted_not_simple_or_summed():
    vals = [float(i) for i in range(1, 13)]  # Jan=1 ... Dec=12
    annual = dp.aggregate_annual(_monthly({2001: vals}))
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    expected = sum(v * d for v, d in zip(vals, days)) / 365
    assert annual.iloc[0]["value"] == pytest.approx(expected)
    assert annual.iloc[0]["value"] != pytest.approx(np.mean(vals))
    assert annual.iloc[0]["valid_months"] == 12
    assert annual.iloc[0]["status"] == "complete"


def test_leap_year_february_has_29_days():
    vals = [0.0] * 12
    vals[1] = 29.0  # February only non-zero
    leap = dp.aggregate_annual(_monthly({2004: vals})).iloc[0]["value"]
    assert leap == pytest.approx(29.0 * 29 / 366)
    assert dp.days_in_month(2004, 2) == 29 and dp.days_in_month(2001, 2) == 28


def test_incomplete_and_missing_years_are_excluded_not_filled():
    full = [10.0] * 12
    nine = [10.0] * 9 + [None] * 3
    ten = [10.0] * 10 + [None] * 2
    empty = [None] * 12
    annual = dp.aggregate_annual(_monthly({2001: full, 2002: nine, 2003: ten, 2004: empty}), min_valid_months=10)
    by_year = annual.set_index("year")
    assert by_year.loc[2001, "used_in_trend"]
    assert by_year.loc[2002, "status"] == "incomplete" and not by_year.loc[2002, "used_in_trend"]
    assert by_year.loc[2002, "valid_months"] == 9
    assert by_year.loc[2003, "status"] == "complete" and by_year.loc[2003, "used_in_trend"]
    assert by_year.loc[2004, "status"] == "missing"
    assert pd.isna(by_year.loc[2004, "value"])
    # Missing months are ignored, not treated as zero: mean of 10s stays 10.
    assert by_year.loc[2003, "value"] == pytest.approx(10.0)


def test_latest_complete_year():
    m = _monthly({2001: [1.0] * 12, 2002: [1.0] * 12, 2003: [1.0] * 9 + [None] * 3})
    assert dp.latest_complete_year(m) == 2002
    assert dp.latest_complete_year(_monthly({2001: [None] * 12})) is None
