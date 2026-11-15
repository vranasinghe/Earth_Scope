"""Shared test fixtures.

The synthetic datasets here are ONLY for unit testing. The application never
uses them in place of live NASA data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests drive jobs explicitly; never start the in-process runner / reconciler threads.
os.environ.setdefault("EARTHSCOPE_JOB_INLINE_FALLBACK", "false")

from app.core.catalog import get_variable  # noqa: E402
from app.core.config import Settings  # noqa: E402


def make_power_payload(
    parameter: str = "T2M",
    start_year: int = 2001,
    end_year: int = 2012,
    value_fn=None,
    units: str | None = "C",
    overrides: dict[str, Any] | None = None,
    include_annual: bool = True,
) -> dict[str, Any]:
    """Build a payload shaped exactly like a NASA POWER monthly point response."""
    value_fn = value_fn or (lambda y, m: 20.0 + 0.1 * (y - start_year) + m / 10)
    series: dict[str, Any] = {}
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            series[f"{y}{m:02d}"] = value_fn(y, m)
        if include_annual:
            series[f"{y}13"] = 12345.0  # annual value: must never be read as a month
    series.update(overrides or {})
    params_meta: dict[str, Any] = {parameter: {"longname": "Test Parameter"}}
    if units is not None:
        params_meta[parameter]["units"] = units
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [79.861, 6.927, 123.66]},
        "properties": {"parameter": {parameter: series}},
        "header": {
            "title": "NASA/POWER Source Native Resolution Monthly and Annual",
            "api": {"version": "v2.10.0", "name": "POWER Monthly and Annual API"},
            "sources": ["MERRA2"],
            "fill_value": -999.0,
            "time_standard": "LST",
        },
        "messages": [],
        "parameters": params_meta,
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def t2m():
    return get_variable("air_temperature")


@pytest.fixture
def gwettop():
    return get_variable("soil_wetness")
