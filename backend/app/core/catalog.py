"""Environmental variable catalogue.

To add a new NASA POWER variable, append one ``VariableDefinition`` to
``VARIABLES``. Before doing so, verify against NASA's parameter manager
(``https://power.larc.nasa.gov/api/system/manager/parameters/<PARAM>``) that
the parameter is offered at MONTHLY resolution and which communities support
it. Nothing else in the backend or frontend needs to change.

Verification performed for the initial catalogue (NASA POWER API v2.10.0):

* T2M, RH2M and GWETTOP are all listed under ``temporal.MONTHLY`` with
  communities ``["AG", "RE", "SB"]``.
* The ``HY`` community suggested in early project notes is *rejected* by the
  API ("Please provide a correct user community value"), so ``AG`` is used.
* Units returned by the API: T2M -> ``C``, RH2M -> ``%``, GWETTOP -> ``1``
  (dimensionless fraction).
* Source reported in the response header: ``MERRA2``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VariableDefinition:
    id: str
    name: str
    parameter: str
    community: str
    category: str
    description: str
    purpose: str
    expected_unit: str
    unit_display: str
    rate_unit: str
    # Phrase used in sentences, e.g. "0.02 °C per year".
    rate_phrase: str
    source_note: str
    spatial_resolution: str
    notes: list[str] = field(default_factory=list)
    # Physically plausible range used to flag suspicious values.
    valid_min: float | None = None
    valid_max: float | None = None
    decimals: int = 2
    # --- Provenance & availability (verified against NASA's parameter manager) ---
    data_source: str = "NASA GMAO MERRA-2 reanalysis, delivered by NASA POWER"
    supported_communities: tuple[str, ...] = ("AG", "RE", "SB")
    # Temporal resolutions NASA POWER offers for this parameter. Earth Scope uses "monthly".
    temporal_resolutions: tuple[str, ...] = ("hourly", "daily", "monthly", "climatology")
    coverage_start_year: int = 1981
    geographic_coverage: str = "Global — every latitude and longitude on the MERRA-2 grid, including oceans and polar regions."
    # True when values are only meaningful over land (not oceans, lakes or ice sheets).
    land_only: bool = False
    # Catalogue ids suggested when this variable is unavailable at a location.
    alternatives: tuple[str, ...] = ()


POWER_PARAMETER_DOCS = "https://power.larc.nasa.gov/parameters/"
POWER_MONTHLY_DOCS = "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/"

MERRA2_RESOLUTION = "MERRA-2 native grid, approx. 0.5° latitude × 0.625° longitude (per NASA POWER documentation)"

VARIABLES: list[VariableDefinition] = [
    VariableDefinition(
        id="air_temperature",
        name="Air Temperature",
        parameter="T2M",
        community="AG",
        category="Atmosphere / Meteorology",
        description="Average air (dry bulb) temperature at 2 meters above the Earth's surface.",
        purpose="Analyse whether near-surface air temperature has increased or decreased over time.",
        expected_unit="C",
        unit_display="°C",
        rate_unit="°C/year",
        rate_phrase="°C per year",
        source_note="Modelled reanalysis value (NASA GMAO MERRA-2) delivered through NASA POWER — not a direct weather-station measurement.",
        spatial_resolution=MERRA2_RESOLUTION,
        valid_min=-90.0,
        valid_max=60.0,
    ),
    VariableDefinition(
        id="relative_humidity",
        name="Relative Humidity",
        parameter="RH2M",
        community="AG",
        category="Atmosphere",
        description="Ratio of actual to saturation water-vapour pressure at 2 meters above the surface, in percent.",
        purpose="Analyse changes in near-surface atmospheric moisture conditions.",
        expected_unit="%",
        unit_display="%",
        rate_unit="percentage points/year",
        rate_phrase="percentage points per year",
        source_note="Modelled reanalysis value (NASA GMAO MERRA-2) delivered through NASA POWER — not a direct weather-station measurement.",
        spatial_resolution=MERRA2_RESOLUTION,
        notes=[
            "A change in relative humidity is expressed in percentage points (e.g. 80% → 81% is +1 percentage point).",
        ],
        valid_min=0.0,
        valid_max=100.0,
    ),
    VariableDefinition(
        id="soil_wetness",
        name="Soil Wetness",
        parameter="GWETTOP",
        community="AG",
        category="Hydrology",
        description="Surface soil wetness of the top ~5 cm of soil, from 0 (completely dry) to 1 (completely saturated).",
        purpose="Analyse whether surface soil wetness is increasing or decreasing over time.",
        expected_unit="1",
        unit_display="wetness fraction (0–1)",
        rate_unit="wetness fraction/year",
        rate_phrase="wetness-fraction units per year",
        source_note="Land-surface model output (NASA GMAO MERRA-2) delivered through NASA POWER — not a field measurement.",
        spatial_resolution=MERRA2_RESOLUTION,
        notes=[
            "GWETTOP is a model-based relative wetness fraction (0 = dry, 1 = saturated). It is NOT volumetric soil water content (m³/m³) and cannot be converted to it without soil-property information.",
            "Only meaningful over ice-free land. Over oceans, large lakes and ice sheets (e.g. Antarctica, Greenland) NASA POWER reports a constant 1.0, so Earth Scope does not analyse those locations.",
        ],
        valid_min=0.0,
        valid_max=1.0,
        decimals=3,
        geographic_coverage="Global grid, but meaningful only over ice-free land (constant 1.0 over oceans, large lakes and ice sheets).",
        land_only=True,
        alternatives=("air_temperature", "relative_humidity"),
    ),
]

_BY_ID = {v.id: v for v in VARIABLES}
_BY_PARAMETER = {v.parameter.upper(): v for v in VARIABLES}


def get_variable(key: str) -> VariableDefinition | None:
    """Look up a variable by catalogue id (``air_temperature``) or NASA parameter (``T2M``)."""
    if not key:
        return None
    return _BY_ID.get(key.strip().lower()) or _BY_PARAMETER.get(key.strip().upper())
