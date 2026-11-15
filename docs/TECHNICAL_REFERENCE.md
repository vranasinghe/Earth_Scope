# Earth Scope — Technical Reference

**Discover How Our Planet Is Changing.**

Earth Scope is a worldwide, web-based Earth-science trend-analysis platform. Pick **any place on Earth** — by searching, clicking a world map or typing coordinates — and Earth Scope retrieves **real NASA POWER** monthly data for that point, visualises how an environmental variable has changed, and tests whether the change is **statistically significant**. Up to three locations can be compared side by side, and a **rectangular region** (2°–9° per side) can be analysed as an area-weighted average of every NASA POWER grid cell inside it. The **Spatial Trend Explorer** maps the trend of every grid cell in that region, with significance corrected for testing many cells at once. **Countries** (from a public boundary dataset) and **custom polygons** (drawn or uploaded as GeoJSON) can be analysed too, each cell weighted by its exact area inside the boundary and larger areas fetched as several NASA requests.

| Question | How Earth Scope answers it |
|---|---|
| **WHAT** is changing? | Air Temperature (T2M), Relative Humidity (RH2M) or Soil Wetness (GWETTOP) |
| **WHERE** is it changing? | Any latitude/longitude worldwide (place search, world map, presets on six continents, manual coordinates), a rectangle, a country boundary or a custom polygon |
| **HOW MUCH** is it changing? | OLS regression slope and Sen's slope, in the variable's own units per year |
| **IS** the change significant? | Regression p-value + 95 % CI, and the Mann-Kendall test, at α = 0.05 |

Target audience: students, researchers, educators and members of the public, anywhere in the world.

---

## Contents

1. [Objectives](#objectives) · 2. [Features](#features) · 3. [Technology stack](#technology-stack) · 4. [Architecture](#architecture) · 5. [NASA data source & global coverage](#nasa-data-source--global-coverage) · 6. [Variables](#environmental-variables) · 7. [Location search](#location-search) · 8. [Statistical methods](#statistical-methods) · 9. [Regional trend analysis](#regional-trend-analysis) · 10. [Spatial trend explorer](#spatial-trend-explorer) · 11. [Country and custom polygon analysis](#country-and-custom-polygon-analysis) · 11b. [Scalable background jobs](#scalable-background-jobs-and-large-country-analysis) · 11c. [AI assistant](#earth-scope-ai-assistant) · 12. [Installation](#installation) · 13. [Running](#running-the-application) · 14. [API](#api-reference) · 15. [Example usage](#example-usage) · 16. [Testing](#testing) · 17. [Limitations](#scientific-limitations) · 18. [Future work](#future-development)

---

## Objectives

- Make long-term environmental change at **any location on the planet** measurable and testable, not just visible.
- Use **only real NASA data** in live mode — never fabricated, zero-filled or interpolated values.
- Report **separate** statistical tests and be explicit when they disagree.
- Explain results so non-experts understand them, including what they do **not** show (causation, regional averages).
- Keep the code simple enough for university students to extend.

## Features

- **Home** — global hero, an interactive world map whose example cities open a live analysis, the four questions, process overview, variables, a significance primer, global examples (New York, São Paulo, Nairobi, Colombo) and a three-continent comparison example.
- **Explore (single location)**
  - Variable cards with NASA parameter, unit, category, community, coverage and land-only notes.
  - **Worldwide location selection**: place search ("Search any location worldwide…"), a world map that opens at a global view (centre 20° N, 0°, zoom 2), click anywhere to place a **draggable** marker, longitude wrapping across the date line, manual latitude/longitude entry with validation, and example locations grouped by continent (Asia, Europe, Africa, North America, South America, Oceania). No location is preselected and nothing restricts the map to one country.
  - The **approximate MERRA-2 grid cell** is outlined, and the selected point shows its place name (from search/preset, or a reverse lookup such as "Near Lomaiviti, Eastern, Fiji").
  - Start/end years (1981 → present, min. 10 years).
- **Results** — place name, requested coordinates **and the grid point returned by NASA** (with elevation), key result cards, monthly/annual chart with trend line, statistics panels, rule-based interpretation and limitations, data table, provenance (exact NASA request URL), CSV/JSON downloads. If a variable is not available at a point (e.g. soil wetness over an ocean), the page explains why and offers compatible variables — it never substitutes one silently.
- **Regional Analysis** — draw a rectangle on the map (drag, or click two corners), edit it with corner handles, type the bounds, or pick one of 8 presets. A live preview shows the expected grid cells, the spherical area and the request size before anything is fetched. The results dashboard has an overview, a cell map (coloured by period mean or any year, with per-cell popups), key results, a monthly/annual chart with a spatial-variability band, the full standard and advanced statistics, a rule-based interpretation, a data table and 5 exports. See [Regional trend analysis](#regional-trend-analysis).
- **Spatial Trend Explorer** (section F of the regional results) — a trend for **every grid cell**. It has four map layers (trend magnitude, direction, significance, data availability) and a choice of test (Mann-Kendall, canonical Hamed–Rao, conservative Hamed–Rao, Yue–Wang). Significance can be raw, Benjamini–Hochberg or Benjamini–Yekutieli, at α = 0.01, 0.05 or 0.10. Clicking a cell opens an inspector with its full statistics and annual chart, optionally compared with the regional aggregate. Summary cards give counts and both cell-based and area-based percentages, and results export as CSV, GeoJSON, a summary JSON and the selected cell's series. See [Spatial trend explorer](#spatial-trend-explorer).
- **Compare (2–3 locations)** — same variable, period, units and methods for each location; per-location trend cards (slope, CI, Sen's slope, p-values, evidence); a chart with a **"change vs own average"** view (so trends, not absolute levels, are compared) and an absolute view; a rule-based comparison summary with caveats. A failure at one location (e.g. ocean) is reported for that location only.
- **Learn** — plain-language explanations of time series, trends, regression, Mann-Kendall, p-values, significance, confidence intervals and causation.
- **"Ask me" AI assistant** — a robot bubble on every results page (point, regional, compare, job results). It opens a small chat that summarises the page in simple English bullet points and answers follow-up questions about it, using Google Gemini. The conversation is kept only in memory: closing the window keeps it, **End chat**, leaving the page or reloading forgets it. Nothing is stored. The visible page text is sent to Gemini; the API key stays on the server.
- **Error handling** with stable error codes (below), Retry buttons, and no synthetic fallback in live mode. Every page with numbers carries a **LIVE NASA DATA** badge.

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, Recharts, React Leaflet + Leaflet (OpenStreetMap tiles), Lucide React, React Router, Fetch API, Oxlint |
| Backend | Python 3, FastAPI, Uvicorn, Pydantic / pydantic-settings, Requests, Pandas, NumPy, SciPy, pymannkendall |
| External services | NASA POWER monthly **point** and **regional** APIs (data); OpenStreetMap Nominatim (place search only); geoBoundaries / Natural Earth files on GitHub (country boundaries, downloaded once from commit-pinned URLs and cached) |
| Geospatial | Shapely 2 (validity, intersections), pyproj (WGS84 geodesic areas); boundaries from geoBoundaries gbOpen ADM0 with a Natural Earth 1:50m fallback |
| Tests | pytest (412 tests, mocked services, incl. independent validation against statsmodels, pymannkendall, SciPy numerical integration and pyproj) + five live scripts (smoke test, point, regional, spatial and polygon cross-validation); Vitest + React Testing Library (39 tests); TypeScript build + Oxlint |

No database, authentication or API keys are required.

## Architecture

```
Browser (React)  ──/api/*──▶  FastAPI backend ──HTTPS──▶  NASA POWER monthly point + regional APIs (data)
                                  │          └─HTTPS──▶  Nominatim (place names ↔ coordinates)
   pages/components               routes → services
   services/api.ts                nasa_power      (point + regional fetch, TTL cache, error mapping)
                                  data_processing (clean + day-weighted annual means)
                                  trend_analysis  (OLS, Mann-Kendall, Sen's slope)
                                  advanced_statistics (autocorrelation, Hamed–Rao, Sen CI, HAC)
                                  interpretation  (rule-based text)
                                  analysis_service (single + multi-location orchestration)
                                  regional_grid / regional_aggregation / regional_analysis
                                                  (bbox validation, cell geometry, area-weighted series)
                                  spatial_trend_analysis / spatial_significance
                                                  (per-cell trends, BH/BY false discovery rate)
                                  geocoding       (Nominatim client, 1 req/s, cache)
```

The browser never calls NASA or Nominatim directly. Geocoding only turns names into coordinates; **NASA data is always requested by the user's selected coordinates** — nothing is hard-coded.

```
Earth_Scope/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, error handlers
│   │   ├── api/deps.py              # shared validation, NASA client, geocoder
│   │   ├── api/routes/              # health, variables, data, analysis, compare, geocode, regional
│   │   ├── core/config.py           # settings (EARTHSCOPE_* env vars)
│   │   ├── core/catalog.py          # variable catalogue + availability metadata
│   │   ├── models/                  # schemas.py, regional_schemas.py, spatial_trend_schemas.py
│   │   ├── services/                # nasa_power, data_processing, trend_analysis, advanced_statistics,
│   │   │                            # interpretation, analysis_service, geocoding,
│   │   │                            # regional_grid, regional_aggregation, regional_analysis,
│   │   │                            # spatial_trend_analysis, spatial_significance
│   │   └── utils/                   # validators.py, errors.py (error codes)
│   ├── scripts/                     # live_smoke_test.py, live_validation.py, live_regional_validation.py,
│   │                                # live_spatial_validation.py
│   ├── tests/                       # pytest suite (incl. test_global.py, test_regional.py, test_spatial_trends.py)
│   ├── requirements.txt · pytest.ini · .env.example
└── frontend/
    ├── src/
    │   ├── pages/                   # Home, Explore, Results, RegionalExplore, RegionalResults,
    │   │                            # Compare, Learn, NotFound
    │   ├── components/              # layout/ dashboard/ map/ (incl. RegionMap) charts/ analysis/ common/
    │   │                            # spatial/ (SpatialTrendExplorer, Map, Controls, Legend, Summary,
    │   │                            #           GridCellInspector, SpatialStatisticalHelp)
    │   ├── services/api.ts          # all HTTP calls
    │   ├── hooks/                   # useVariables, useAnalysis, useCompare, useRegional, useSpatialTrends,
    │   │                            # useReverseGeocode
    │   ├── constants/               # world presets by continent, compare palette, education, help text
    │   ├── utils/                   # formatting, validation, geo, location, region, export,
    │   │                            # regionalExport, spatialColors, spatialExport, URL params
    │   ├── test/                    # Vitest setup + fixtures (*.test.ts(x) live next to the code)
    │   └── types/api.ts             # TypeScript mirror of backend schemas
    └── vite.config.ts               # /api proxy to the backend
```

## NASA data source & global coverage

**NASA POWER** (Prediction Of Worldwide Energy Resources), NASA Langley Research Center — [docs](https://power.larc.nasa.gov/docs/) · [monthly API](https://power.larc.nasa.gov/docs/services/api/temporal/monthly/) · [parameters](https://power.larc.nasa.gov/parameters/). Endpoint: `https://power.larc.nasa.gov/api/temporal/monthly/point`.

Example request built from a user's selection (New York):

```
https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=T2M&community=AG&longitude=-74.0060&latitude=40.7128&start=2001&end=2025&format=JSON
```

### Verified against the live API (v2.10.0)

| Check | Finding | Consequence |
|---|---|---|
| Parameter manager (`/api/system/manager/parameters/<P>`) | T2M, RH2M, GWETTOP offered at **MONTHLY** for communities **AG, RE, SB** | All three enabled; community `AG` used |
| `community=HY` | **Rejected** (HTTP 422, "Please provide a correct user community value") | HY is not used; documented in the catalogue |
| Geographic coverage | Real data returned at both poles (±90°), longitudes ±180°, both sides of the date line (±179.99°), the equator, and all 8 test cities | Any valid coordinate is accepted |
| Returned location | Response `geometry` only **echoes the requested point** (plus the cell's elevation). Values are identical anywhere inside a 0.5° × 0.625° cell and change across its edges (tested live: cell edges at 40.25° N and −74.0625°) | Earth Scope reports the requested point **and** the computed MERRA-2 cell (centre + bounds, `metadata.grid_cell`) |
| Monthly keys | `YYYYMM` months plus `YYYY13` = annual value | `13` keys ignored; annual means computed by Earth Scope |
| Fill value | `-999`; unpublished recent months are `-999` | Treated as missing, never zero |
| Earliest data | 1981-01-01 | Minimum year 1981 |
| GWETTOP over water/ice | Constant `1.0` over oceans, Lake Victoria, Antarctica and Greenland; real values over land (e.g. Sahara 0.1–0.16) | Analysis refused with `LOCATION_NOT_SUPPORTED` + suggested variables |

Results describe the **NASA POWER grid cell** containing the point (≈ 0.5° × 0.625°, about 55 × 70 km at the equator, narrower toward the poles) — not a building, street, city, country or regional average.

## Environmental variables

Defined once in `backend/app/core/catalog.py` and served by `/api/variables`.

| Variable | Parameter | Unit (NASA) | Category | Communities | Coverage | Notes |
|---|---|---|---|---|---|---|
| Air Temperature | `T2M` | `C` (°C) | Atmosphere / Meteorology | AG, RE, SB | 1981–present, global | 2 m dry-bulb temperature |
| Relative Humidity | `RH2M` | `%` | Atmosphere | AG, RE, SB | 1981–present, global | Changes in percentage points |
| Soil Wetness | `GWETTOP` | `1` (0–1) | Hydrology | AG, RE, SB | 1981–present, **ice-free land only** | Model-based relative wetness of the top ~5 cm; **not** volumetric soil water content |

Each entry also records the data source (NASA GMAO MERRA-2 via NASA POWER), available temporal resolutions (hourly, daily, monthly, climatology — Earth Scope uses monthly), spatial resolution, `land_only`, and `alternatives` suggested when the variable is unavailable at a point.

**Adding a variable:** verify it at `https://power.larc.nasa.gov/api/system/manager/parameters/<PARAM>` (MONTHLY + community), append one `VariableDefinition`, and run `python scripts/live_smoke_test.py`. The architecture keeps retrieval (`nasa_power.py`) separate from processing and statistics, so other NASA sources (GPM, MODIS, GLDAS…) could be added as new services later — **none of those are integrated yet**.

## Location search

- Search accepts cities, countries, regions, landmarks, or `lat, lon` text (e.g. `-33.8688, 151.2093` — parsed locally, no network call).
- Uses **OpenStreetMap Nominatim** through the backend (`/api/geocode/search`, `/api/geocode/reverse`), in line with the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/): server-side requests, **max 1 request/second** (process-wide throttle), identifying User-Agent (configurable via `EARTHSCOPE_GEOCODER_USER_AGENT`), **no autocomplete** (search runs on Enter / the Search button), results cached for 7 days, and attribution shown under results.
- Reverse lookup labels map clicks ("Near Suginami, Tokyo, Japan"); open ocean returns no name. Place names are display-only — they never affect the data request.

## Statistical methods

All statistics live in `backend/app/services/trend_analysis.py` as pure, unit-tested functions; they behave identically for every location.

1. **Cleaning** — fill values (`-999`), non-numeric and physically impossible values are excluded; every month is listed so gaps are explicit. No zero-filling, interpolation or synthetic records.
2. **Annual aggregation** — day-weighted mean of valid months, `Σ(value·days)/Σ(days)` (leap years handled). Years with **< 10 valid months** are excluded from trend tests (shown, not filled).
3. **OLS regression** — `Y = a + b·year`; slope (per year and per decade), intercept, two-sided p-value, R², SE, 95 % CI `b ± t(0.975, n−2)·SE`.
4. **Mann-Kendall** (`pymannkendall.original_test`, tie-corrected) — direction, S, Kendall's τ, Z, p-value. Values that are equal up to floating-point rounding (relative difference < 1e-9) count as ties. A live soil-wetness cell had two years whose day-weighted sums were both exactly 153.05/365, yet differed by 5.6e-17 after summation, which changed S by 1. Real differences between NASA annual means are at least about 1e-5.
5. **Sen's slope** — median of pairwise slopes using the **actual years** (gaps handled).
6. **Evidence** at α = 0.05 — significant increasing/decreasing (both tests agree), not significant (neither), or **mixed** (tests disagree, with an explanation).
7. **Minimum data** — ≥ 10 usable annual values (the Mann-Kendall p-value uses the normal approximation of S, generally adequate for n ≥ 10), else data are shown with `analysis_error = INSUFFICIENT_DATA_FOR_ANALYSIS`. A constant series is never called a trend: it returns `analysis_error = NO_VARIATION_IN_DATA`.
8. **Comparison** — each location is analysed independently with the above; the summary compares rates and significance, never absolute levels, and notes overlapping confidence intervals.

### Advanced statistical analysis (autocorrelation-aware)

All of the above **assume independent years**. Environmental series often have *persistence*: a wet year tends to follow a wet year. That positive **autocorrelation** means 25 years carry less independent information than 25 truly independent values, so standard tests become over-confident (p-values too small, intervals too narrow). The results page therefore adds a separately labelled **Advanced Statistical Analysis** section. The standard results are kept unchanged. Code: `backend/app/services/advanced_statistics.py`.

1. **Diagnostics first** — the trend is removed (`value − Sen's slope × year`, because a trend on its own creates apparent autocorrelation), then Earth Scope reports the lag-1 autocorrelation r₁, the autocorrelation function (lags 1 to min(10, n/3)) with the white-noise bound ±1.96/√n, and the **Ljung–Box** test over min(10, n/5) lags. Missing years are handled by pairing only observations exactly *k* calendar years apart. *Limitations:* with 10–45 values these diagnostics have little power: not detecting autocorrelation does not prove independence, and individual bars can fall outside the bound by chance.
2. **Modified Mann-Kendall — Hamed & Rao (1998)** — S is unchanged, but Var(S) is multiplied by `n/n* = 1 + 2/(n(n−1)(n−2)) · Σ (n−i)(n−i−1)(n−i−2)·ρᵢ`, where ρᵢ is the autocorrelation of the **ranks** of the detrended series. Only lags 1–3 whose ρᵢ lies outside ±z/√n are included, so a series with no detectable autocorrelation gets a factor of exactly 1 and the same result as the original test. The original and modified tests are shown side by side (direction, S, variance, Z, p-value, decision, correction factor, effective number of years).
   - **Conservative rule (Earth Scope's choice):** the factor is **never allowed below 1**. Estimated *negative* autocorrelation would shrink the variance and make the test *more* significant. In live NASA series this produced raw factors as low as 0.07 (an "effective sample" of ~350 years from 25), which made the tests badly over-confident. The raw factor is still reported (`raw_correction_factor`, `reduction_suppressed`).
   - **Canonical vs conservative labelling:** the decision column is labelled "Modified (Hamed–Rao, conservative)" and is **not** presented as the unmodified published method. The canonical Hamed & Rao (1998) result, which applies the raw factor including reductions, is also reported (`canonical_var_s`, `canonical_z`, `canonical_p_value`, `canonical_significant`; the "Canonical Hamed–Rao p (no floor)" row). It matches pymannkendall exactly and is shown for transparency only. For example, a live SE Australia regional series gave canonical p = 0.038 but conservative p = 0.234.
   - **Sensitivity check:** Yue & Wang (2004) lag-1 correction (no significance screen, same floor). It is shown collapsed and is not used for conclusions.
   - **Verified implementation:** the raw factors reproduce `pymannkendall.hamed_rao_modification_test(x, lag=3)` and `yue_wang_modification_test(x, lag=1)` exactly on gap-free series. Earth Scope uses its own year-aware code because pymannkendall detrends by observation index (wrong when years are missing). It also found that pymannkendall silently returns a negative variance and NaN p-value when ρ₁ < −0.5 in Yue–Wang.
3. **Sen's slope confidence interval** — the non-parametric interval of Sen (1968, eq. 2.6; Gilbert 1987): with `C = z(1−α/2)·√Var(S)` (Var(S) corrected for ties in both years and values), the bounds are the sorted pairwise slopes at ranks `round((N−C)/2)` and `round((N+C)/2)+1`, where N is the number of pairwise slopes. It uses actual year differences, so missing years are handled. It is computed with `scipy.stats.theilslopes`, checked against an independent implementation, and **is not derived from the OLS interval**. It assumes independent years.
4. **Regression with Newey–West (HAC) standard errors** — the same OLS line, with a heteroscedasticity- and autocorrelation-consistent standard error: Bartlett kernel, bandwidth `floor(4·(n/100)^(2/9))`, small-sample factor n/(n−2), t(n−2) reference. It is checked against statsmodels and labelled as a separate method. The ordinary OLS p-value is **never** presented as autocorrelation-adjusted. OLS inference assumes independent, equally variable, normally distributed residuals; HAC relaxes the first two, but only approximately in short records.
5. **Autocorrelation-aware evidence** — combines the regression (significant only if *both* the ordinary and HAC p-values are below α) with the Hamed–Rao test, using the same rules as the standard evidence. By construction it is **never more significant than the standard evidence**: when the two disagree, the page explains why, and the autocorrelation-aware reading is the cautious one.

| Method | What it estimates | Assumes independent years? |
|---|---|---|
| OLS slope + 95% CI | Straight-line rate of change | Yes |
| OLS + Newey–West (HAC) | Same slope, uncertainty allowing for autocorrelation | No (approximately) |
| Sen's slope + 95% CI | Robust median rate of change | Yes |
| Original Mann-Kendall | Is there a monotonic trend? | Yes |
| Hamed–Rao modified Mann-Kendall | Same question, variance inflated for positive autocorrelation | No (lags 1–3) |

## Regional trend analysis

Point analysis answers "how has this variable changed **at this grid point**?". Regional analysis answers "how has the **area-weighted average over this rectangle** changed?". Open **Regional Analysis** in the navigation bar, or use the Point / Regional switch on the Explore page.

### Selecting a region

- **Draw:** press *Draw region*, then either drag across the map or click one corner and then the opposite corner. The map then zooms to the region.
- **Edit:** drag the south-west or north-east corner handle, or edit the four bounds (latitude min/max, longitude min/max in decimal degrees).
- **Presets:** Sri Lanka (central), Indo-Gangetic Plain, Central Amazon, Kenya highlands, Murray–Darling (south), Central Europe, US Corn Belt, Central Sahara.
- **Delete** clears the region. Invalid boxes show a specific message and cannot be submitted.
- Before any data is requested, the preview lists the bounds, size, exact spherical area, the expected number of NASA grid cells (dashed cells are only partly inside) and the request complexity. The URL holds the full selection (`/regional/results?variable=…&lat_min=…&lat_max=…&lon_min=…&lon_max=…&start=…&end=…&coverage=…`), so a result can be bookmarked or shared.

### How the NASA regional request works

The backend calls `https://power.larc.nasa.gov/api/temporal/monthly/regional` once per analysis (`parameters`, `community=AG`, `latitude-min/max`, `longitude-min/max`, `start`, `end`, `format=JSON`). NASA returns a GeoJSON `FeatureCollection` with one feature per grid cell centre and a monthly series per feature (`YYYYMM` keys; the `YYYY13` annual key is ignored; `-999` is missing). These limits were checked against the live API:

| Property | Verified behaviour |
|---|---|
| Size limits | Each side must span **≥ 2° and ≤ 10°**, in both latitude and longitude |
| Cells returned | Every MERRA-2 cell centre inside the **closed** request box |
| Grid | 0.5° latitude × 0.625° longitude; centres at k·0.5° lat and −180 + k·0.625° lon |
| Values | Identical to the point API at each cell centre |
| Antimeridian | Boxes with `lon_min > lon_max` are rejected |
| Size of the largest request | 10° × 10° × 25 years ≈ 340 cells, 1.7 MB, ~3.5 s |

**Why the user limit is 9°:** so that cells cut by the rectangle's edges are included, Earth Scope expands the request by **half a cell on each side** (0.25° lat, 0.3125° lon). A 9° user box therefore becomes a request of at most 9.625°, inside NASA's 10° limit. The minimum is 2° (smaller areas: use Point Analysis). Supported variables are the same three: Air Temperature (T2M), Relative Humidity (RH2M) and Soil Wetness (GWETTOP).

### Aggregation method

1. **Exact cell geometry.** Each cell's area is computed on a sphere, `A = R²·Δλ·(sin φ₂ − sin φ₁)` with R = 6371.0088 km, so high-latitude cells are correctly smaller. This is tested against SciPy numerical integration and against the full sphere (4πR²).
2. **Partial cells.** Each cell is weighted by the **true spherical area of its overlap** with the rectangle, not by an equal share and not by the cell centre alone. A corner cell that is 25 % inside counts 25 %. Normalised weights sum to 1; cells with zero overlap are dropped.
3. **Monthly regional mean.** For each month, `mean = Σ wᵢ·xᵢ / Σ wᵢ` over cells with a valid value. Earth Scope also reports the spatial SD (area-weighted), min, max, valid/missing cell counts, the valid area and the **coverage** = valid area / analysed area.
4. **Missing data and the coverage threshold.** Missing (`-999`) or physically impossible values are excluded and never filled. A month is used only if its coverage is at least the **threshold** (default 80 %, selectable 50–100 %). Below that it is marked `insufficient_coverage` and shown without a value, because a mean of a few cells may not represent the region.
5. **Land-only soil wetness.** GWETTOP is constant at 1.0 over oceans, large lakes and ice sheets. Cells that are 1.0 in every month are **excluded** (`exclusion_reason`), and coverage is measured against the remaining land area. If less than 10 % of the box is ice-free land, the request fails with `LOCATION_NOT_SUPPORTED` and suggests the other variables.
6. **Annual series.** Monthly regional means go through the same day-weighted annual aggregation as point data; years with < 10 valid months are excluded from trend tests. The annual spatial SD across cells is reported alongside.
7. **Statistics.** The annual regional series goes through the **unchanged** statistics engine: OLS, Mann-Kendall, Sen's slope, evidence, and the full advanced analysis (autocorrelation diagnostics, conservative Hamed–Rao with canonical values, Yue–Wang, Sen CI, Newey–West). The rule-based interpretation names the rectangle and the number of cells.

The spatial-variability band on the chart (±1 SD across cells) shows how much the cells differ from each other. It is **not** a confidence interval and not the uncertainty of the trend.

### Regional vs point analysis

| | Point analysis | Regional analysis |
|---|---|---|
| NASA endpoint | `…/monthly/point` | `…/monthly/regional` |
| Spatial unit | One MERRA-2 grid cell | Area-weighted mean of all cells overlapping the rectangle |
| Size | Any point | 2°–9° per side |
| Missing data | Month missing if NASA has no value | Month missing if valid coverage < threshold |
| Extra outputs | Returned grid point and elevation | Cell map, coverage, spatial SD, per-cell metadata |
| Statistics | Same engine | Same engine |

**A rectangle is not a country.** Results describe the selected rectangle only, not a country, city, administrative or ecological boundary, even when a preset is named after a place. Different rectangles over the same area can give different trends.

### Exports and caching

- **No synthetic data.** If NASA is unavailable the page shows `NASA_API_UNAVAILABLE` with a Retry button.
- **Exports** (each with a provenance header, NASA request and data mode): monthly regional series (CSV), annual regional series (CSV), statistical summary (JSON), grid-cell metadata (CSV: bounds, cell area, overlap area and fraction, weight, status, valid months, period mean) and complete analysis metadata (JSON, including every cell's annual means).
- **Caching:** raw NASA responses are cached only when they contain features; processed regional results are cached for 6 hours, keyed by variable, box, years and threshold.

### Example workflow

Regional Analysis → choose *Air Temperature* → preset *Murray–Darling (south)* → check the preview (cell count, area) → **Run Regional Analysis** → read the key results → open *Advanced statistical analysis* to compare the conservative and canonical Hamed–Rao p-values → export the grid-cell CSV.

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/regional/analyze?variable=air_temperature&lat_min=6&lat_max=10&lon_min=79&lon_max=82&start_year=2001&end_year=2025" |
  Select-Object -ExpandProperty summary
```

### Regional limitations

- Rectangles only (no polygons or country outlines). Regions crossing the **antimeridian** (±180°) are rejected with `ANTIMERIDIAN_NOT_SUPPORTED`; split them into two rectangles.
- 2°–9° per side, one NASA request per analysis.
- MERRA-2 cells are about 55 km × 69 km at the equator; small features (lakes, valleys, cities) are not resolved, and coastal cells mix land and sea.
- An area average can hide opposing local trends: two halves warming and cooling can average to "no trend". Use the cell map (per-year colouring) to check spatial consistency.
- The coverage threshold changes which months are used; results near the threshold should be read with care.

## Spatial trend explorer

A regional average can hide local differences: the central Sri Lanka box (2001–2025) has a regional temperature trend of +0.009 °C/year that is **not** significant (Mann-Kendall p = 0.44). Yet 19 of its 40 cells, mostly coastal, warm significantly even after the FDR correction, while the central highland cells cool. The Spatial Trend Explorer (section F of the regional results page) shows this directly.

### Three separate analyses

| | Question | Where |
|---|---|---|
| **A. Regional aggregate trend** | Did the area-weighted mean of the rectangle change? | Sections C–E (unchanged) |
| **B. Individual cell trends** | How did each grid cell change? | Map layers, inspector |
| **C. Multiple-testing-adjusted significance** | Which cell trends are unlikely to be chance findings, given that many cells were tested? | Significance layer, summary |

The regional slope is never replaced by an average of cell slopes. OLS is linear in the data, so when every cell is complete in every month the regional OLS slope **equals** the area-weighted mean of the cell OLS slopes. The summary reports both values and a flag saying whether this identity holds exactly. With missing months, or for Sen's slopes and p-values, they are different quantities.

### Pipeline (one NASA request)

1. **Same data as the regional analysis.** `regional_analysis.load_regional_grid` reuses the NASA regional request, its cache, the grid parser, fill-value and physical-range rules, and the land-only exclusion. No per-cell point requests are made.
2. **Per-cell annual series.** Each cell's monthly values go through `data_processing.aggregate_annual`, the point-analysis function itself (day-weighted, ≥ 10 valid months). Cells with fewer than 10 usable years are marked **insufficient data**, and no statistics are computed for them.
3. **Per-cell statistics.** Each testable cell's annual series goes through the unchanged `run_trend_analysis`:
   - OLS slope, intercept, R², SE, p and 95 % CI
   - Mann-Kendall S, τ, Z and p
   - Sen's slope with the Sen (1968) CI
   - lag-1 autocorrelation and Ljung–Box
   - Hamed–Rao (conservative and canonical) and Yue–Wang
   - Newey–West HAC

   The Hamed–Rao lag screen always uses the application's α = 0.05, so changing the map threshold never changes any p-value. Constant series are reported as **no variation**, and failures as **calculation failed**; neither is reported as "no trend".
4. **Caching.** Steps 1–3 are cached for 6 hours per variable, community, box, years, annual rules and screening α. Changing the layer, estimator or display options needs no request. Changing the test, correction or threshold re-runs only the classification (about 0.05–0.5 s). The first request for the largest region (285 cells × 45 years) takes about 4 s plus the NASA download.

### Multiple-testing correction

- **Family:** fixed *before* any significance is examined. It contains every analysed cell that has a valid p-value for the **selected test**. Cells that are excluded, have insufficient data or have no p-value (for example Yue–Wang when its correction factor is ≤ 0) are left out and counted. P-values from different tests are never mixed, and the whole family is always adjusted together, never only the increasing, decreasing or already-significant cells.
- **Tests offered:** original Mann-Kendall (default), Hamed–Rao **canonical** (published method), Hamed–Rao **Earth Scope conservative variant** (labelled as such, never as canonical), and Yue–Wang canonical.
- **Corrections:** none (raw p < α), **Benjamini–Hochberg** (default; `q_(i) = min_{k≥i} min(1, m·p_(k)/k)`) and **Benjamini–Yekutieli** (BH × Σ1/k, valid under any dependence). A cell is a discovery when `q ≤ α` (the BH step-up rule). Thresholds are 0.01, 0.05 or 0.10. Raw and adjusted p-values and statuses are both stored, and the map can switch between them.
- **Implementation:** a few lines in `spatial_significance.py`, checked against `statsmodels.stats.multitest.multipletests`, the worked example in Benjamini & Hochberg (1995) and hand-computed cases (ties, ordering, invalid p-values, capping at 1).
- **Spatial dependence:** neighbouring cells are correlated. BH is proven for independent or positively dependent tests (PRDS), which is the usual situation for neighbouring cells, but not for arbitrary dependence. BY is valid under any dependence but more conservative. In a Monte Carlo test with 600 trendless 10 × 10 maps, a map without correction showed at least one false "trend" 90 % (correlated) to 99.5 % (independent) of the time. BH did so 3.8 % / 5.7 % of the time (Monte Carlo SE ≈ 0.9 %) and BY 0.8 % / 1.7 %. This is evidence for the simulated cases, not a proof for real fields. FDR controls the *expected share* of false discoveries; it does not guarantee that any single highlighted cell is real.

### Map layers and controls

- **Trend magnitude:** diverging blue–white–red scale, symmetric around zero, using Sen's or the OLS slope in the variable's unit per year. The scale is fixed per analysis and estimator and never changes on pan or zoom. Significant cells get a dark outline, and the colour itself never implies significance.
- **Trend direction:** increasing, decreasing or near zero. "Near zero" is a display rule only: the change over the period, |slope| × years, is below 10 % of the cell's year-to-year SD.
- **Statistical significance:** significant increase or decrease, not significant ("insufficient evidence under this test", not "no change"), not testable, insufficient data, or excluded. It can be classified by raw p or by FDR-adjusted q. The direction is the sign of the Mann-Kendall S.
- **Data availability:** complete, partial (some months missing but analysed), too few years, no data, or excluded (water or ice).
- **Display toggles:** grid lines, region outline, missing-data cells, and non-significant cells. Hidden non-significant cells are drawn as outlines and **stay in the family and the summary**.
- **Cells:** drawn with their true MERRA-2 bounds (0.5° × 0.625°), never as equal pixels.
- **Grid-cell inspector** (click a cell):
  - metadata: id, bounds, overlap and weight, valid months and years, source
  - all p-values: MK, canonical and conservative HR, YW, selected test, q
  - Sen's CI, autocorrelation
  - annual chart with gaps, OLS trend and optional regional-aggregate line
  - CSV download of the cell's series
- **Summary:** counts per category with **cell %** and **area %** (using the true overlap areas) shown separately, the family size, raw-significant count, number of FDR discoveries, test coverage, and local vs regional slopes. Rule-based statements (for example "The region contains both positive and negative local slopes") appear only when the computed results support them, and never make causal claims.

### API

`GET /api/regional/spatial-trends` takes the regional parameters plus `method` (`mann_kendall` | `hamed_rao_canonical` | `hamed_rao_conservative` | `yue_wang_canonical`), `correction` (`none` | `fdr_bh` | `fdr_by`) and `alpha` (0.01 | 0.05 | 0.10). It returns metadata (provenance and the NASA request URL), `config`, `summary`, `regional_aggregate` and compact `cells` (statistics and p-values, no monthly arrays), plus `available`, `interpretation` and `warnings`. `GET /api/regional/spatial-trends/cell?...&cell_id=7.000_81.2500` returns one cell's annual series, full statistics and the regional annual series. If no cell can be tested, `available` is `false` and the UI shows only the availability layer with an explanation, never an empty "no significant trend" map. Unsupported settings return `INVALID_REQUEST` before any NASA request is made.

### Exports

- **Spatial trend table** (CSV): `cell_id, latitude, longitude, variable, unit, slope (OLS), trend_direction, sen_slope, sen_ci_lower, sen_ci_upper, raw_p_value, adjusted_p_value, statistical_method, fdr_method, significance_status, valid_years, overlap_area, data_status`, plus bounds, weight, all test p-values and the data mode.
- **GeoJSON:** closed, counter-clockwise polygons (RFC 7946) carrying all statistics, with file-level provenance.
- **Summary JSON:** configuration, spatial summary, regional aggregate, methods, NASA metadata and coverage.
- **Selected cell:** annual series with its OLS line and the regional series.

Every export header names the data mode.

### Spatial limitations

- NASA POWER cells are modelled or satellite-derived gridded estimates (MERRA-2), not stations, and neighbouring cells are not independent observations. The map is not a high-resolution land-cover map.
- Per-cell series of 10–45 years give limited power; many real but small trends will be "not significant".
- BH's guarantee assumes independence or positive dependence; BY is the safe alternative. No correction accounts for the spatial *field significance* of a pattern as a whole.
- The grid resolution described here (0.5° × 0.625°) applies to the three MERRA-2 parameters used; other NASA POWER parameters can come from other sources and grids.

## Country and custom polygon analysis

Regional Analysis has three area types: **Rectangle**, **Country** and **Custom polygon** (tabs in the "Area" card). Countries and polygons are analysed inside their actual outline, not their bounding box.

### Four kinds of "where"

| Term | What it is in Earth Scope |
|---|---|
| **NASA grid cell** | One MERRA-2 cell, 0.5° latitude × 0.625° longitude (≈ 55 × 69 km at the equator), holding a modelled average value. It is the smallest unit any result can describe. |
| **Bounding box** | A latitude/longitude rectangle. Rectangle mode analyses it directly; for countries and polygons it is only used for display and to plan NASA requests. |
| **Geographical polygon** | Any closed outline: drawn, uploaded or taken from a boundary dataset. Cells count only for the part of their area inside it. |
| **Political boundary** | One dataset's representation of a country. Boundaries can be disputed, include or exclude overseas territories, and be generalised differently. A country result always names the dataset used. |

### Boundary sources and licences

- **Default: [geoBoundaries](https://www.geoboundaries.org/) gbOpen ADM0**, using its simplified geometries.
  - The catalogue (`backend/app/data/country_index.json`, built by `scripts/build_boundary_index.py`) lists 230 countries.
  - Each entry has its own licence, upstream source, year represented and boundary id. Licences include ODbL 1.0, CC BY 4.0, CC BY 3.0 IGO, public domain and others; each is shown in the app and every export.
  - Download URLs are **pinned to a geoBoundaries Git commit** (mostly `9469f09`), so results are reproducible.
  - Cite: Runfola et al. (2020), *geoBoundaries*, PLoS ONE 15(4): e0231866.
- **Fallback: [Natural Earth](https://www.naturalearthdata.com/) 1:50m Admin-0 v5.1.2** (public domain). It is used **only** for the 19 codes gbOpen lacks, and always labelled.
  - These include **India**, Hong Kong, Macao, Puerto Rico, Kosovo, Western Sahara, Somaliland, Northern Cyprus and Siachen Glacier.
  - Natural Earth draws *de facto* boundaries and labels disputed areas with their own type; Earth Scope shows that type.
- **No silent substitutes.** A country without a boundary returns `COUNTRY_NOT_FOUND`, and a failed download returns `BOUNDARY_SOURCE_UNAVAILABLE`. A rectangle is never used instead.
- **Download and cache.** Geometry is downloaded the first time a country is used, from allow-listed hosts only (the catalogue's GitHub URLs). It is size-limited and cached in `backend/app/data/boundary_cache/`, which is git-ignored. User input only picks an ISO code; it never supplies a URL.
- **Repairs.** Authoritative boundaries that fail validity checks are repaired with `shapely.make_valid`, and the area change is reported. User-drawn polygons are **never** repaired; they are rejected with an explanation.

### Selecting an area

- **Country:** type a name or ISO code in the search box, then choose a country. The map draws and zooms to the boundary. A details card shows:
  - the ISO code, equal-area and WGS84 geodesic areas, number of parts and vertices;
  - boundary source, version and licence;
  - the number of NASA grid cells, NASA requests and data values, and the estimated time;
  - whether the country is within the analysis limits.
- **Custom polygon:** press *Draw polygon* and click vertices on the map. Close it by clicking the first vertex, double-clicking or pressing *Finish polygon*; *Undo vertex* removes the last point.
  - **Edit:** drag a vertex, click the small round handle on an edge to insert a vertex, or right-click (or Alt-click) a vertex to delete it.
  - **Remove:** *Delete polygon* or *Reset selection*.
  - **Feedback:** problems are flagged while you draw (crossing edges, fewer than three distinct vertices, zero area, invalid coordinates, too many vertices); the outline turns red and the analysis cannot start.
- **Upload GeoJSON:** a Polygon, MultiPolygon, Feature or FeatureCollection of polygons in WGS84 longitude/latitude, at most 2 MB and 5,000 vertices.
  - The file is parsed in the browser, then validated again by the server. Nothing it references is downloaded.
  - Single polygons without holes become editable; multi-part polygons and polygons with holes are shown read-only.
- **Shareable links.** The selection is kept in the URL (`shape=country&iso3=LKA`, or `shape=polygon&poly=…`). Very large polygons are kept in the browser session instead. If such a polygon is no longer available, the app asks you to draw it again rather than analysing a rectangle.

### Geometry engine (`app/services/area_geometry.py`)

- **Coordinates:** input is WGS84 longitude/latitude (EPSG:4326, RFC 7946 order). Polygon and MultiPolygon, holes and separate parts are supported.
- **Validation:** finite coordinates, latitude within ±90, at least three distinct vertices, non-zero area, no self-intersection, and limits on vertices, parts and request size.
- **Date line:** shapes drawn across it on a continuous map copy (longitudes beyond ±180) are split at ±180° and shifted back. A ring edge that jumps more than 180° is ambiguous and rejected. Countries split at ±180°, such as Fiji, are drawn on one side of the map.
- **Areas — never planar degrees.** Every geometry is densified to segments of at most 0.02° and projected with the spherical Lambert cylindrical equal-area projection (x = R·λ, y = R·sin φ, R = 6371.0088 km).
  - In this projection a grid cell is an exact rectangle, with area R²·Δλ·(sin φ₂ − sin φ₁). The weights are therefore consistent with rectangle analysis: a polygon equal to a rectangle reproduces rectangle-mode weights to 10⁻¹⁴.
  - The WGS84 geodesic area (pyproj) is reported alongside. For the boundaries tested it matched geoBoundaries' own published areas to within 0.02%; the equal-area and ellipsoidal areas differ by up to ~0.6%.
- **Cell overlaps:** each cell's footprint (the cell on ±180° is split into two parts) is intersected exactly with the area, and the overlap is measured in km². Cells that only touch the boundary, or overlap by less than 10⁻⁶ km², are ignored. The overlaps add up to the polygon area (*grid representability* ≈ 100%).
- **Source grid:** cells are identified by integer grid indices (i, j), never by floating-point strings. The grid's spacing and alignment come from a `GridSpec` for the data source (MERRA-2 here), not hard-coded assumptions about every NASA dataset.

### NASA tiling (`app/services/regional_tiling.py`)

- **Limits, re-verified live:**
  - each regional request must span 2°–10° in latitude and longitude;
  - it carries one parameter and returns every centre inside the closed box;
  - the grid has a centre at −180° but **none at +180°**, so the date-line cell is requested from the −180 side.
- **Planning, with no NASA call:** the needed cells are grouped into blocks of at most 19 × 15 cells, anchored at the area's first cell. Each block that contains needed cells becomes one request.
  - Tile edges lie halfway between cell centres, so no centre sits on an edge; a live check returned exactly 19 × 15 = 285 cells.
  - Tiles narrower than 2° are widened symmetrically; the extra cells are discarded because they are not needed.
  - Blocks with no needed cells are skipped, so a multi-island country only requests tiles over land.
- **Fetching:** at most 3 requests run at once, each with up to 2 retries (exponential backoff of 1.5 s, then 3 s), using the client's timeout and cache.
  - **If any tile still fails, no result is produced** (`INCOMPLETE_TILE_RETRIEVAL`, retryable). Errors that cannot be retried, such as NASA rejecting a request, are reported directly.
- **Merging:** returned centres are mapped to grid indices. A centre that is not on the grid is an error. A cell returned by several tiles must have identical values: it is counted once and reported as a merged duplicate, and conflicting values are an error. Needed cells that NASA did not return are kept as missing data, lower the coverage, and are reported.
- **Provenance:** every tile URL is kept in the request manifest (results page and exports).

### Aggregation and statistics

The tiled grid enters the **same pipeline** as rectangle analysis; only the weights change:
- **Monthly mean:** for each month, `Σ(valueᵢ × valid overlap areaᵢ) / Σ(valid overlap areaᵢ)`.
- **Per-month record:** the polygon area, valid area, missing cells, coverage and status. Months below the coverage threshold (default 80% of the analysed area) are marked `insufficient_coverage` and excluded; they are never filled.
- **Land-only soil wetness:** water and ice cells are excluded and coverage is measured against the land area.
- **Annual series:** the existing day-weighted annual aggregation (at least 10 valid months).
- **Statistics:** the unchanged statistics engine — OLS, Mann-Kendall, Sen's slope with its confidence interval, canonical and conservative Hamed–Rao, Yue–Wang, Newey–West and autocorrelation diagnostics.

**Spatial Trend Explorer:** cells are drawn **clipped to the boundary**, and the correction family is exactly the testable cells that intersect the polygon. Cells that were only fetched as part of a NASA tile are never in the family. BH and BY are applied unchanged, and the country trend stays a separate test from the per-cell maps. The per-cell step was sped up 2.9× (about 6.5 ms per cell) by computing every cell's annual means in one vectorised pass of the same formula; a test proves it equals `aggregate_annual` for every cell.

### Large-country processing

The preflight (`POST /api/polygon/preview`, or `GET /api/boundaries/countries/{iso3}`) reports, before any NASA request:
- the number of cells and tiles, months and values;
- the estimated time and memory;
- availability against configurable budgets in `app/core/config.py`.

| Budget | Default | Measured basis |
|---|---|---|
| Grid cells | 3,000 | Per-cell statistics ≈ 6.5 ms/cell (25 years); Brazil, 2,462 cells: analysis 17.5 s live |
| NASA tiles | 24 | Brazil needs 17 tiles; a full tile downloads in ~1–4 s |
| Cell-month values | 1,500,000 | 3,000 cells × 25 years = 900,000 |
| Concurrent NASA requests | 3 | Respectful use of a public service |
| User geometry | 5,000 vertices, 50 parts, 3 MB request body | |

Preflight results for some countries (25 years):

| Country | Cells | Tiles | Result |
|---|---|---|---|
| Sri Lanka | 30 | 1 | analysed live |
| Fiji | 44 | 2 | |
| Kenya | 195 | 3 | |
| Madagascar | 209 | 4 | |
| Japan | 300 | 10 | |
| India | 1,067 | 13 | |
| Brazil | 2,462 | 17 | analysed live |
| Australia | 2,514 | 23 | within limits |
| United States | 4,089 | 47 | refused |
| Russia | 11,182 | 73 | refused |

Areas over a budget are refused **before** any NASA request. The message says "This region requires more data than the current analysis limit supports" and suggests drawing a smaller polygon, using a rectangle, or shortening the period. Earth Scope never downsamples or analyses only part of an area while calling it complete. These are the budgets of the **instant (synchronous)** analysis, and the table above is the historical Phase 5 estimate. Larger areas now run as durable background jobs; see [Scalable Background Jobs and Large-Country Analysis](#scalable-background-jobs-and-large-country-analysis), which also has counts recalculated with the current code.

### Point, rectangle, polygon and country compared

| | Point | Rectangle | Custom polygon | Country |
|---|---|---|---|---|
| NASA requests | 1 point | 1 regional | 1 or more regional tiles | 1 or more regional tiles |
| Weights | — | overlap with box | exact overlap with polygon | exact overlap with boundary |
| Size limits | any point | 2°–9° per side | cell / tile budgets | cell / tile budgets |
| Describes | one grid cell | the rectangle | the drawn shape | one dataset's boundary of the country |

### Provenance and exports

- **Provenance:** every result shows the analysis mode, area name and ISO code, and the boundary dataset with its version, id, year, licence and attribution. It also shows the geometry id (a hash of the geometry used), parts and vertices, every NASA tile URL, the grid, the aggregation method and the coverage rules.
- **Exports:**
  - the five regional exports (monthly CSV, annual CSV, statistics JSON, grid-cell CSV, full metadata JSON);
  - the spatial CSV and GeoJSON — cells clipped to the boundary, with full cell bounds, statistics, p- and q-values and provenance;
  - the spatial summary JSON and the selected cell's series.

  All exports carry the area provenance and every request URL.

### Country / polygon limitations

- The ~55 km grid cannot resolve small islands, narrow coasts or features within a cell. Small areas are weighted correctly by overlap, but they still describe coarse cells, and the preflight warns about this.
- A result describes one boundary representation. Another dataset, or another treatment of disputed or overseas territories, can give slightly different results.
- Large countries (USA, Russia, Canada, China) exceed the default budgets.
- The vertex-editing tool is mouse-oriented: right-click or Alt-click deletes a vertex.

## Scalable Background Jobs and Large-Country Analysis

Phase 6 lets country and polygon analyses that exceed the instant (synchronous) budget run as **durable background jobs**. You submit a job, can close the tab, and come back later in the same browser for its progress and results. Jobs survive page refreshes, API restarts and worker crashes. They run the **same scientific code** as the synchronous endpoints and produce the same result schema, so the existing dashboards render them.

### 1. Architecture

```
 Browser (React/Vite)                     Docker Compose (Linux containers)
 ───────────────────                      ──────────────────────────────────────────────────────────
 Region setup ─ Preview ─ Start  ──POST──▶ backend (FastAPI)  ── INSERT job (PENDING) ─▶ PostgreSQL  ◀── authoritative state
 Analysis Jobs / Job details ◀─GET (poll)─┤                   ── RQ message ──────────▶ Redis      ◀── queue + NASA slots
 Results dashboards  ◀── GET results ─────┘                                                │
                                                     worker × N (RQ) ◀─────────────────────┘
                                                       claim (compare-and-set) · lease + heartbeat
                                                       NASA tiles (global limiter) ─▶ NASA POWER regional API
                                                       checkpoints + results ─▶ artifacts volume
                                                     scheduler (reconciler): outbox · orphan recovery · expiry
```

| Component | Role |
|---|---|
| `app/jobs/models.py`, `db.py`, `migrations/` | SQLAlchemy models + Alembic migrations: `analysis_jobs`, `job_tiles` (tile manifest and checkpoints), `job_events` (audit trail). |
| `app/jobs/service.py` | Preflight plan, idempotent submission (outbox), budgets, ownership, cancel, retry. |
| `app/jobs/queue.py` | RQ integration. A message only says "run job X". |
| `app/jobs/coordination.py` | Redis-wide NASA concurrency semaphore + request-start rate limit. |
| `app/jobs/pipeline.py`, `worker.py` | Checkpointed processing stages run by RQ workers. |
| `app/jobs/reconciler.py` | Re-enqueues lost / due jobs, recovers orphaned jobs, expires old results. |
| `app/jobs/artifacts.py`, `results.py` | Atomic, checksummed artifact storage; reading published results. |
| `app/api/routes/jobs.py` | `/api/analysis/...` endpoints. |
| `frontend/src/pages/AnalysisJobs.tsx`, `JobDetails.tsx`, `components/jobs/*` | Job dashboard, details page, background-analysis panel. |

### 2. Queue framework: RQ (not Celery)

RQ was chosen because the database, not the queue, holds job state, so a simple queue is enough:

- **Durable tracking.** PostgreSQL rows, not short-lived queue result records.
- **Retries.** Done by the worker and the reconciler from the database, with backoff stored in `next_attempt_at`. No broker-specific retry semantics are needed.
- **Independent processes.** `python -m app.jobs.worker`; scale with `--scale worker=N`.
- **Cancellation.** Cooperative, through the database. Queued jobs are cancelled before any worker claims them.
- **Crash recovery.** Worker leases and heartbeats in PostgreSQL, plus checkpoints. RQ's own abandoned-job registry is not relied on.
- **Monitoring.** `rq info`, `Worker.all()`, and `/api/analysis/health` and `/ops`.
- **Scheduling.** The reconciler process enqueues due retries, so no RQ scheduler or Celery beat is required.
- **Controlled concurrency.** Number of worker processes, plus the Redis-wide NASA limiter.

Celery would add broker and visibility-timeout semantics, acks-late subtleties and a beat scheduler without solving a problem RQ leaves open. No second, home-made queue exists: RQ delivers, PostgreSQL decides.

**Windows.** RQ's default worker forks one work-horse process per job, and native Windows has no `fork`. The supported setup runs the workers in **Linux containers** (Docker Compose). For experiments, `python -m app.jobs.worker` on native Windows automatically uses RQ's `SimpleWorker` (no fork, timer-based timeout).

### 3. Job lifecycle

```
PENDING ──enqueue──▶ QUEUED ──claim──▶ RUNNING ──publish──▶ COMPLETED ──retention──▶ EXPIRED
   ▲  (reconciler      │                 │  │ transient failure / lost worker
   │   retries outbox) │ cancel          │  └──────────▶ RETRYING ──due──▶ QUEUED (resumes from checkpoints)
   │                   ▼                 │ cancel
   └── Retry ◀── CANCELLED ◀── CANCEL_REQUESTED          FAILED (attempts exhausted / bad input) ── Retry ──▶ PENDING
```

- **Claim** is a single `UPDATE … WHERE status IN (claimable) OR (RUNNING AND lease expired)`. Two workers can never both succeed.
- The worker renews a **lease** every 15 s (`job_heartbeat_seconds`; lease 120 s). Every write it makes is conditional on still holding the lease, so a worker that stalled and lost its job cannot overwrite the new owner.
- **Status and progress counters** are always read from PostgreSQL.

### 4. Processing stages and checkpoints

| # | Stage | Checkpoint | On resume |
|---|---|---|---|
| 1 | Preparing geometry | — (boundary version and geometry id are verified against the submitted ones) | A changed boundary fails with `BOUNDARY_VERSION_CHANGED`; it is never silently substituted. |
| 2 | Calculating polygon weights | `work/overlaps.json.gz` (exact equal-area overlap of every cell) | reused |
| 3 | Preparing NASA requests | `job_tiles` rows (tile manifest + request hash) | Plan must match the stored manifest, else `INPUT_CHANGED`. |
| 4 | Downloading NASA data | Each verified tile is stored as an immutable content-addressed blob; the `job_tiles` row records its SHA-256. | Verified tiles are never downloaded again. |
| 5 | Validating data | Per tile: JSON shape, exact parameter, months present, centres on the grid inside the box, units, fill values. | — |
| 6 | Merging grid cells | `work/grid.npz` + `grid_meta.json.gz` (streamed merge, one tile in memory at a time) | reused |
| 7 | Building time series | `work/regional.json.gz` (polygon-weighted monthly/annual series + regional statistics) | reused |
| 8 | Running statistics | `work/cells/chunk-NNNNN.json.gz` (500 cells per chunk) | Only missing chunks are computed. |
| 9 | Calculating spatial FDR | — (fast; always over the complete family) | recomputed |
| 10 | Generating results | `staging-*/` → verified → renamed to `result/` | An already published, verifying result is reused, never published twice. |

Every file is written to a temporary file, `fsync`ed and renamed. Readers verify SHA-256 checksums. A job becomes COMPLETED only **after** the result directory was published **and** the completion row was committed. Execution is *at least once*: a stage may run again after a crash, but all stages are deterministic and idempotent. Exactly-once execution is **not** claimed.

### 5. Progress

The progress bar shows `progress_pct`, which the server computes from real counters (tiles verified, cells analysed) and fixed stage weights:

| Stage | Weight |
|---|---:|
| Geometry | 2 |
| Weights | 6 |
| Requests | 1 |
| Download | 45 |
| Validation | 1 |
| Merge | 5 |
| Series | 4 |
| Statistics | 30 |
| FDR | 2 |
| Results | 4 |

The value never decreases (it is stored as a running maximum), stays below 100 until the result is published, and reaches 100 only on COMPLETED. Download progress (`tiles_completed / tiles_total`, `tiles_retrying`) and processing progress (`cells_processed / cells_total`) are shown separately.

The frontend polls every 2 s for the first minute, then every 5 s, and at most every 15 s while the tab is hidden. It backs off up to 30 s on errors and stops when the job is finished. No timer ever advances the bar.

### 6. NASA request limits, retries and validation

- **One parameter per regional request**, tiles of 2°–10° per side. The Phase 5 tiler (`plan_tiles`) is reused unchanged.
- **Global concurrency.** `nasa_global_max_concurrency = 3` slots **across all workers**. This is a Redis sorted set of leased tokens (lease 300 s, longer than the 120 s request timeout, so a crashed holder frees its slot). Four workers share the same three slots.
- **Request-start rate.** At least `nasa_min_request_interval_seconds = 0.5` s between any two NASA request starts, application-wide.
- **Retries.** These errors are transient: timeouts, connection errors, HTTP 429/5xx, and invalid or HTML responses. A tile gets up to `job_tile_max_attempts = 5` tries with exponential backoff and equal jitter (2, 4, 8, 16 s; capped at 120 s), and `Retry-After` is honoured. HTTP 4xx rejections (bad parameter, location or period) are **not** retried.
- **Exhausted tiles.** The job goes to RETRYING (automatic job-level retry after 60 s, 120 s; up to `job_max_attempts = 3`) and then to FAILED. Verified tiles are kept, so **Retry** fetches only the missing ones.
- **Shared tile cache.** A verified tile is reused by later jobs (of any session) for 24 h (`job_tile_cache_hours`), the same freshness as the synchronous in-memory cache. It is raw public NASA data, keyed by the exact request, and never contains user polygons.
- **No synthetic fallback.** If NASA fails, the job fails; Earth Scope never substitutes generated data.

### 7. Preflight and resource budgets

`POST /api/analysis/preflight` (no NASA call) returns the following:

- cells, tiles, cell-months and boundary version;
- the **tier** and eligibility, with the reasons if blocked;
- the processing stages;
- estimates of duration, memory and storage, labelled as estimates. They come from completed jobs on the deployment when at least three exist, otherwise from development benchmarks.

| Tier | Rule (defaults, `app/core/config.py`) | Runs |
|---|---|---|
| SMALL | ≤ 3,000 cells, ≤ 24 tiles, ≤ 1.5 M cell-months (the synchronous Phase 5 budget) | instant, or as a job |
| MEDIUM | ≤ 6,000 cells, ≤ 60 tiles | background |
| LARGE | ≤ 15,000 cells, ≤ 100 tiles, ≤ 6 M cell-months, estimated memory ≤ 1,536 MB | background, chunked + checkpointed |
| VERY_LARGE | anything bigger | only if `EARTHSCOPE_JOB_ALLOW_VERY_LARGE=true` and within `job_very_large_max_*` |

Additional limits:
- ≤ 512 MB of artifacts per job;
- ≤ 2 active jobs per session and ≤ 20 globally;
- ≤ 6 submissions per session per hour and ≤ 30 per network (hashed IP) per day;
- ≤ 250 NASA tiles per session per 24 h.

A rejected request gets HTTP 422 `ANALYSIS_TOO_LARGE` or 429 `JOB_LIMIT_EXCEEDED` with the reason.

**Large-country results.** All rows below are measured, not estimated: T2M 2001–2025 with the current boundary versions and code, all **live NASA POWER** data and **whole-country** boundaries (no sub-regions). Durations are from this development machine (Docker Desktop on Windows 11).

| Country (boundary) | Cells | NASA tiles | Tier | How it was run | Polygon weights | Per-cell statistics | Peak memory | Results (+ cached tiles) | Sync = background? |
|---|---:|---:|---|---|---:|---:|---:|---:|---|
| Sri Lanka (gbOpen 9469f09) | 30 | 1 | SMALL | native worker pipeline, live | 0.01 s | 0.1 s | — | 0.2 MB (+0.1) | identical (11,536 numbers) |
| Brazil (gbOpen 9469f09) | 2,462 | 19 | SMALL | native, **simulated crash after 8 tiles** → resumed, fetched only the 11 missing | 3.1 s | 9.6 s | — | 5.7 MB (+3.6) | identical (255,241) |
| Australia (gbOpen bdfb316) | 2,514 | 22 | SMALL | Docker, 2 workers in parallel with Canada; 2 transient NASA errors retried; 48 s total | 10.0 s | 9.6 s | 348 MB | 7.1 MB (+4.1) | identical (428,268) |
| United States (gbOpen 9469f09) | 4,089 | 44 | MEDIUM | Docker, **worker killed at 17/44 tiles + API restart + PostgreSQL restart during statistics**; recovered after 144 s; 367 s total | 3.5 s | 15.4 s | 325 MB | 9.6 MB (+7.2) | identical (428,066) |
| Canada (gbOpen 9469f09; 297,180 vertices, 8,145 parts) | 6,628 | 42 | LARGE | Docker, in parallel with Australia; 158 s total | 73 s | 25 s | 589 MB | 20.7 MB (+10.4) | identical (1,514,745) |
| Russia (gbOpen 9469f09) | 11,182 | 72 | LARGE | Docker, 121 s total (72 tiles downloaded in ~52 s at 3 concurrent requests) | 12 s | 42 s | 491 MiB (container) | 24.1 MB (+17.2) | identical (980,852) |
| Japan · India (NE v5.1.2) | 300 · 1,067 | 9 · 12 | SMALL | preflight only | | | | | |

How these were checked (`scripts/live_job_validation.py`):
- Every value of the published background result was compared with the **synchronous** pipeline run on the same verified tile payloads.
- Regional monthly means, cell annual means and OLS slopes were recomputed **independently** from the raw NASA JSON; all agreed within 4 × 10⁻¹⁵.
- BH/BY adjusted p-values were recomputed with statsmodels over the complete family (4,089 / 6,628 / 11,182 hypotheses); all agreed within 2 × 10⁻¹⁶.
- No country had a missing cell, and every duplicated cell was identical in all the tiles that returned it.
- The Redis-wide limiter held at most **3** NASA requests at once across two workers (339 samples).

The tile counts differ slightly from the Phase 5 table (Brazil 19, not 17; Australia 22, not 23; United States 44, not 47; Russia 72, not 73) because they were recalculated with the current tiler and boundaries.

Per-cell statistics cost ≈ 3.8 ms per cell (25 years). Exact polygon weighting depends on boundary complexity: Canada's 297k vertices take 73 s. Russia's result JSON is 11 MB and its spatial JSON 18 MB, both gzip-compressed on the wire. Maps with more than 2,500 cells are drawn on one canvas, without hover tooltips.

These numbers show feasibility on this machine, not a promise for every deployment. The tier limits and the `nasa_global_max_concurrency` budget decide what a given deployment accepts.

### 8. Cancellation and retry

- **Cancel** (`POST …/cancel`). A queued job is CANCELLED at once, and a worker that later receives its message cannot claim it. A running job goes to CANCEL_REQUESTED. The worker sees it at its next heartbeat, stops scheduling NASA requests (requests already in flight finish), and stops at the next safe checkpoint. Publication itself is never interrupted. Staging and results are removed, while work checkpoints are kept until expiry so the job can be retried. **Shared NASA tiles are never deleted by a cancellation.**
- **Retry** (`POST …/retry`) is allowed for FAILED jobs with a transient cause, and for CANCELLED jobs. It reuses the original request, period, statistics, boundary version and verified checkpoints, and the response says how many tiles are already verified. Jobs that failed because of their input (`INVALID_GEOMETRY`, `LOCATION_NOT_SUPPORTED`, `BOUNDARY_VERSION_CHANGED`, …) cannot be retried; the API explains that a new analysis is needed. A job allows at most 5 manual retries.

### 9. Failure handling

| Failure | Behaviour |
|---|---|
| NASA timeout / 429 / 5xx / invalid JSON | Tile retried with backoff → job RETRYING → FAILED (checkpoints kept). Never synthetic data. |
| Worker crash, `docker kill`, OOM | The lease expires (≤ 120 s), the reconciler marks the job RETRYING, and another worker resumes from the last checkpoint. After 3 losses the job is FAILED with `WORKER_LOST` (retryable). |
| API restart | No effect on workers. Jobs are in PostgreSQL, and the frontend reconnects through polling. |
| Redis outage | Submissions stay PENDING (outbox) and are enqueued by the reconciler later. A running job's NASA limiter calls fail and the job goes to RETRYING. Redis uses AOF persistence, and lost messages are re-sent (`requeued_lost`). |
| PostgreSQL outage | Worker database writes retry for up to 120 s (`job_db_outage_tolerance_seconds`). After that the lease lapses and the job is recovered once the database is back. Completion is reported only after the completion row is committed. |
| Disk full / write error | `STORAGE_FULL` / `ARTIFACT_STORAGE_ERROR`: nothing is published and the job is retried. A 200 MB free-space reserve is checked before writing. |
| Tampered or torn result file | Checksum mismatch → `ARTIFACT_CORRUPT` (HTTP 503). It is never served. |
| Statistics error in one cell | Recorded on that cell (`calculation_failed`), exactly as in synchronous mode. |

### 10. Storage and retention

- **PostgreSQL** holds job rows, tile manifests, checksums, events and result references, never large arrays.
- **Artifacts** live on the `artifacts` volume (`/data/artifacts`). Natively they are in `backend/var/artifacts`.
- **Retention:**
  - completed results are kept 14 days;
  - failed and cancelled jobs 7 days;
  - shared tiles 30 days unless a live job still references them.

  The job then becomes **EXPIRED** (HTTP 410 on its results).
- **Durability.** Named volumes survive `docker compose down`, `restart` and image rebuilds. Only `docker compose down -v` deletes them.
- **Production.** Replace `ArtifactStore` with an object-storage implementation offering the same write-then-commit and checksum semantics (for example S3 with conditional writes), and keep the bucket private. Results are only ever served through the owner-checked API.

### 11. Security and ownership

- Anonymous sessions use the `es_session` cookie: a 256-bit random token, HttpOnly, SameSite=Lax, path `/api`, and Secure when `EARTHSCOPE_SESSION_COOKIE_SECURE=true`. Only its SHA-256 is stored.
- Every job endpoint checks the owner. Job ids are random UUIDv4s, but an id alone never grants access. Unknown and foreign jobs return the same 404.
- **CSRF protection.** State-changing requests (submit, cancel, retry) must echo the `es_csrf` double-submit token in `X-CSRF-Token`, and foreign `Origin`s are refused.
- **Custom polygons** are stored only in the job's input artifact, never in job listings or logs.
- **Logs** contain job ids, stages, tiles, attempts and worker host, never session tokens or credentials.
- The frontend never sees the database or Redis URLs.
- `/api/analysis/health` exposes booleans only. `/api/analysis/ops` (counts, durations, NASA errors, worker capacity) requires `X-Ops-Token` and is disabled unless `EARTHSCOPE_OPS_TOKEN` is set.

### 12. Scientific reproducibility

- **Shared code.** The worker calls the same functions as the synchronous path:
  - `area_from_request`, `cell_overlaps` and `plan_tiles` for geometry and tiling;
  - `merge_tiles` (now streaming, but the same rules) for merging;
  - `build_regional_from_loaded` and `compute_cell_rows` for the series and per-cell statistics (the latter split into chunks, since cells are independent);
  - `spatial_response_from_set` for spatial significance.
- **FDR over the complete family.** BH/BY are always applied over every analysed cell of the complete area: never per tile, never only to significant cells, never only to the visible map. The viewport filter (`?lat_min=…`) only trims the returned cells; the summary and adjusted p-values are unchanged.
- **Tests.** `tests/test_jobs.py` asserts **exact** equality of every monthly, annual, statistical and per-cell value (including the BH/BY adjusted p-values) between the synchronous and background paths, and after a crash and resume.
- **Live checks.** `scripts/live_job_validation.py` repeats the comparison on real NASA data.
- **Provenance.** Each result records its job id, `analysis_software_version`, configuration hash, boundary version, the complete tile manifest (URL, retrieval time, attempts, cache use) and `exports/provenance.json`.

### 13. API

| Method & path | Purpose |
|---|---|
| `GET /api/analysis/session` | Start or resume the anonymous session; returns the CSRF token. |
| `POST /api/analysis/preflight` | Tier, eligibility, estimates, stages (no NASA call). |
| `POST /api/analysis/jobs` | Submit (202). Optional `Idempotency-Key` header. A duplicate returns the existing job (200, `duplicate_of_reason`). |
| `GET /api/analysis/jobs` | This session's jobs. |
| `GET /api/analysis/jobs/{id}` | Status, configuration, counters, events. |
| `GET /api/analysis/jobs/{id}/progress` | Lightweight polling payload. |
| `GET /api/analysis/jobs/{id}/results` | `RegionalAnalysisResponse` (same schema as `/api/polygon/analyze`); 409 `JOB_NOT_READY`, 410 `JOB_EXPIRED`. |
| `GET /api/analysis/jobs/{id}/spatial` | `SpatialTrendResponse` for any `method` / `correction` / `alpha`; optional viewport. |
| `GET /api/analysis/jobs/{id}/spatial/cell?cell_id=` | Grid-cell inspector data. |
| `GET /api/analysis/jobs/{id}/artifacts[/{name}]` | Manifest and downloads (`exports/annual.csv`, `monthly.csv`, `spatial_cells.csv`, `provenance.json`, …). |
| `POST /api/analysis/jobs/{id}/cancel` · `/retry` | Cancel / retry (CSRF header required). |
| `GET /api/analysis/health` · `/ops` | Availability (public) · operational summary (token). |

Duplicate handling:
- The same session submitting the same canonical configuration (geometry id, boundary version, parameter, period, statistics, data mode, software version) while a job is active gets that job back. A unique index makes even a race between two clicks impossible.
- If an identical job already completed, it is returned unless `force_new: true` is sent.
- Different sessions never share jobs.

### 14. Windows PowerShell workflow

Prerequisites: Docker Desktop (WSL 2 / Linux containers), Python 3.11+ and Node.js 20+.

```powershell
# 1. One-time setup (from the repository root)
Copy-Item .env.example .env                   # then edit POSTGRES_PASSWORD
cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; cd ..
cd frontend; npm install; cd ..

# 2. Start PostgreSQL, Redis, migrations, API, worker and scheduler
docker compose up -d --build
docker compose ps                              # backend "healthy", migrate "exited (0)"

# 3. Migrations (also run automatically by the "migrate" service)
docker compose run --rm migrate

# 4/5. API and workers are containers. More workers:
docker compose up -d --scale worker=3

# 6. Frontend (Vite proxies /api to http://127.0.0.1:8000)
cd frontend; npm run dev                       # http://localhost:5173 → Analysis Jobs

# 7. Tests
cd backend; .\.venv\Scripts\python.exe -m pytest; cd ..
cd frontend; npm test; npm run lint; npm run build; cd ..
docker compose run --rm --no-deps backend python -m pytest -q   # same suite inside Linux

# 8. Logs
docker compose logs -f worker scheduler

# 9. Restart workers safely (warm shutdown: the current job finishes or resumes from checkpoints)
docker compose restart worker

# 10. Stop everything — volumes (jobs, results, queue) are kept
docker compose down
```

Without Docker (single machine, SQLite + a Redis server you run yourself), set `EARTHSCOPE_REDIS_URL` and run `uvicorn app.main:app` and `python -m app.jobs.worker` and `python -m app.jobs.reconciler` in three windows. This is for experiments only and was not exercised in the Phase 6 validation, which used Docker. SQLite is not supported for several workers.

No Redis installed? `python scripts\dev_fake_redis.py` (in `backend`) starts an in-memory, Redis-compatible server on 127.0.0.1:6379 for local testing. Its queue is lost when you close it; job records stay in SQLite and the reconciler re-queues them.

**Submit a sample job from PowerShell:**

```powershell
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$csrf = (Invoke-RestMethod http://127.0.0.1:8000/api/analysis/session -WebSession $s).csrf_token
$body = @{ iso3 = "LKA"; variable = "T2M"; start_year = 2001; end_year = 2025} | ConvertTo-Json
$job = Invoke-RestMethod http://127.0.0.1:8000/api/analysis/jobs -Method Post -Body $body -ContentType application/json `
        -Headers @{ "X-CSRF-Token" = $csrf; "Idempotency-Key" = [guid]::NewGuid() } -WebSession $s
Invoke-RestMethod "http://127.0.0.1:8000/api/analysis/jobs/$($job.job_id)/progress" -WebSession $s
```

**Recover failed jobs:** open **Analysis Jobs → Retry**, or `POST /api/analysis/jobs/{id}/retry`. Orphaned jobs (crashed or killed workers) need no action, because the scheduler resumes them automatically.

**Live validation:**

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\live_job_validation.py LKA          # small-country regression
.\.venv\Scripts\python.exe scripts\live_job_validation.py BRA --crash-after-tiles 8
.\.venv\Scripts\python.exe scripts\live_job_validation.py RUS --preflight-only
```

### 15. Production deployment requirements

- Managed PostgreSQL with backups, and Redis with AOF persistence.
- Workers sized for the LARGE tier (≥ 2 GB RAM each).
- Private object storage for artifacts.
- HTTPS with `EARTHSCOPE_SESSION_COOKIE_SECURE=true` and an exact `EARTHSCOPE_CORS_ORIGINS` list.
- `EARTHSCOPE_OPS_TOKEN` set from a secret store.
- Container restart policies, and log shipping for the structured `job=… stage=…` logs.
- Run `alembic upgrade head` on each deploy before starting the API and workers.
- Keep `nasa_global_max_concurrency` conservative: NASA POWER is a shared public service.

### 16. Known limitations

- An accepted job is **not** a guaranteed result. It can still fail, for example when NASA POWER stays unavailable through all retries, the boundary dataset changes before a retry, or the storage budget is exceeded. It is never completed with missing tiles or synthetic substitutes.
- Execution is at-least-once with idempotent stages, not exactly-once.
- Ownership is per browser session. Clearing cookies or switching browsers loses access to earlier jobs; there are no user accounts.
- Duration estimates are rough until the deployment has measured history.
- Very large maps are drawn on one canvas without hover tooltips. Vector tiles are not implemented (not needed at the measured ≤ 11k cells).
- A pause/resume button is not offered. Cancel followed by Retry gives the same checkpoint-based behaviour.
- `ArtifactStore` is filesystem-based. Object storage needs an adapter.

## Earth Scope AI Assistant

A small "Ask me" chat (robot button, bottom-right on every page) that explains **the analysis on the current page** in simple English: it summarizes the results, explains the charts and statistics, and answers follow-up questions. It uses Google Gemini through the official [`google-genai`](https://googleapis.github.io/python-genai/) SDK, called **only from the FastAPI backend**.

### How it understands the page

The browser never sends scientific numbers. Each page registers an **analysis reference** — the parameters it used (variable, point / locations / rectangle / country / polygon, years, Spatial Trend Explorer settings and selected cell) or a background job id. For every chat message the backend rebuilds the **authoritative** context from that reference with the same service functions the result pages use (`app/services/ai_context.py`); those are cached, so this normally costs no extra NASA request. Background-job results are read from their published artifacts after the same **session-ownership check** as `/api/analysis/jobs/{id}` (another browser's job id behaves like a missing job).

| Page | Context sent to Gemini (compact, rounded, size-bounded) |
|---|---|
| Point results | variable, NASA parameter, unit, place, coordinates, MERRA-2 cell, period, completeness, OLS / Mann-Kendall / Sen / Hamed-Rao / Yue-Wang / HAC / Ljung-Box results, annual means used, provenance |
| Compare | each location's statistics, years used, shared period and unit, the comparison summary |
| Regional / country / polygon | area type and bounds, boundary dataset and version, cells used, area, coverage, regional statistics, provenance (incl. background job id) |
| Spatial Trend Explorer | test, FDR method, α, cell counts per significance class (cell- and area-based %), slope signs, regional aggregate, current map layer, the selected cell's statistics — never the raw list of thousands of cells |
| Analysis Jobs / job details | status, stage, tiles, progress, errors; results only once COMPLETED |
| Learn / other pages | the selected concept or a description of the page; **"Summarize this analysis" answers that an analysis must be run first** (no Gemini call, no invented summary) |

User-typed strings (place and polygon names) are sanitised, and the context is placed in the system instruction inside `<earth_scope_context>` tags that the model is told to treat as data, never as instructions (`app/ai/system_prompt.py`). The model has no tools and cannot change data, jobs or settings.

### Temporary conversation memory

* The conversation lives **only in React memory** (`src/context/AiChatProvider.tsx`): not in localStorage, sessionStorage, cookies, Redis, PostgreSQL or files. Reloading or closing the tab forgets it.
* **Minimize** (–) hides the panel and keeps the chat; **New conversation** (pen icon) clears it; **End conversation** (×) clears it and closes the panel. Navigating between pages keeps the chat.
* When the analysis on screen changes, a notice says so, the next request only sends turns from after the change, and a button starts a fresh conversation for the new page — results of two analyses are never mixed.
* Each request sends at most the last 20 messages (each truncated); older user questions are condensed into a short in-memory digest.
* The chat API is stateless. Logs contain metadata only (page type, action, context id, latency, outcome) — never message text, context content or the API key.

**Privacy notice (shown in the panel):** your messages and a compact summary of the analysis on screen are sent to Google Gemini to generate answers. Earth Scope itself does not save your chat; Google processes requests under its own API terms.

### Configuration (backend only)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Required for live answers. Empty → the panel says "AI Assistant is not configured yet." and everything else works normally. |
| `GEMINI_MODEL` | *(empty = auto)* | Preferred model id, e.g. `gemini-2.5-flash`. Empty → the newest available stable "flash" text model from your key's model list. |
| `GEMINI_FALLBACK_MODELS` | *(empty = auto)* | Comma-separated rotation after the preferred model. Empty → all of the key's available "flash" text models, newest first. |
| `GEMINI_MODEL_FALLBACK` | `true` | Model rotation (see below). `false` → only `GEMINI_MODEL` is ever used. |
| `EARTHSCOPE_GEMINI_MAX_MODEL_ATTEMPTS` | `6` | Most models tried for one message. |
| `GEMINI_CHAT_ENABLED` | `true` | Turn the assistant off without removing the key. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `1200` | Token budget for the answer itself. |
| `EARTHSCOPE_GEMINI_THINKING_RESERVE_TOKENS` | `1024` | Extra output tokens for "thinking" models (Gemini 2.5 / 3.x), whose thinking counts against the output limit. Gemini 3 models run with `minimal` thinking; an answer that still hits the limit ends with a visible "cut short" note. |
| `EARTHSCOPE_GEMINI_TIMEOUT_SECONDS` | `30` | Request timeout (SDK retries are disabled: one message = at most one billable answer). |
| `EARTHSCOPE_AI_RATE_LIMIT_PER_MINUTE` / `_PER_HOUR` | `8` / `60` | Per browser session (or IP). |
| `EARTHSCOPE_AI_MAX_MESSAGE_CHARS` | `2000` | Longer messages are rejected. |
| `EARTHSCOPE_AI_MAX_CONCURRENCY` | `4` | Simultaneous Gemini calls per backend process. |

**Model rotation.** Each message tries the models in order (preferred model first). A model that is **exhausted** (429 `RESOURCE_EXHAUSTED`, e.g. requests-per-minute or per-day quota) rests for the delay Google returns in `RetryInfo` (1 minute if none; at least 1 hour for a daily quota); a model that is **unavailable** (503 / 404) rests 10 minutes; either way the next model answers the same message. A model that **timed out** (504) rests 10 minutes but is not retried within the same message. Resting models are skipped and rejoin the rotation in their preferred place as soon as their rest ends; if every model rests, the one that recovers first gets a single try, otherwise the user sees "All available AI models have reached their usage limits. Please try again in about N minutes." Failed calls return no answer, so a message still produces at most one billable answer. `GET /api/ai/status` lists `resting_models` with the seconds left.

`EARTHSCOPE_GEMINI_API_KEY` / `EARTHSCOPE_GEMINI_MODEL` are accepted as aliases. **Never** put the key in `frontend/.env` or any `VITE_*` variable — those are compiled into the public JavaScript bundle.

Windows PowerShell setup:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # includes google-genai
notepad .env                             # add:  GEMINI_API_KEY=your-key   (optional: GEMINI_MODEL=gemini-2.5-flash)
uvicorn app.main:app --reload --reload-dir app --port 8000
Invoke-RestMethod http://127.0.0.1:8000/api/ai/status   # "available": true (the key itself is never returned)
```

Docker Compose passes `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_CHAT_ENABLED` and `GEMINI_MAX_OUTPUT_TOKENS` from the repository-root `.env` to the backend container at runtime; nothing is baked into the image.

### API

* `GET /api/ai/status` → `{enabled, configured, available, reason, model ("auto" or the configured id), message, limits, privacy_notice}`.
* `POST /api/ai/chat` → body `{message, action: "ask" | "summarize", page_type, reference, history, earlier_summary}`; response `{reply, context_id, context_label, has_results, model, usage, generated}`.

Friendly error codes: `AI_NOT_CONFIGURED`, `AI_CONFIGURATION_ERROR` (key rejected / model not available), `AI_UNAVAILABLE`, `AI_TIMEOUT`, `AI_QUOTA_EXCEEDED`, `AI_RATE_LIMITED`, `AI_BUSY`, `AI_BAD_RESPONSE`, `AI_CONTEXT_UNAVAILABLE` ("I couldn't access the results for this analysis."), `AI_MESSAGE_TOO_LONG`. Raw provider errors are never shown, and the app never falls back to a fake answer.

### Testing

* `backend/tests/test_ai.py` (Gemini SDK mocked, settings injected — never uses a real key): missing / disabled configuration, env names, model auto-selection, fallback and cool-down, request and history limits, point / compare / rectangle + spatial / polygon / country / job contexts, browser-supplied numbers ignored, job ownership, provider errors (quota, 5xx, 401, 404, timeouts, empty answers), prompt-injection handling, key redaction and log hygiene, no persistence, rate limiting, duplicate suppression, concurrency cap, context size bound.
* `frontend/src/components/ai/ai.test.tsx` (fetch mocked): launcher, open / minimize / restore, sending, quick actions, new / end conversation, no browser storage, loading and duplicate-submission guard, error and retry, unconfigured state, context-change notice, safe Markdown (no HTML from replies), Escape and focus return, theme tokens and mobile bottom-sheet layout, spatial context.

### Known limitations

* Answers are generated by a language model: they explain Earth Scope's results but are not new analyses and can still contain mistakes — the result pages remain the authoritative numbers.
* Rate limits, the model cool-down and the duplicate-suppression cache are per backend process and reset on restart.
* Responses are not streamed; a reply appears when it is complete (typically 5–15 s; the first message after a restart can take longer while the auto-selected model is checked).
* Validated live with one Gemini key (point summary, two follow-ups, a regional heatmap question). During that check the two newest flash models returned 503 / 504 for that key and the rotation answered with an older flash model — set `GEMINI_MODEL` to a model that works for your key to avoid the extra latency. The quota (429) rotation is covered by mocked tests; it has not been exercised against a real exhausted quota.

## Installation

Prerequisites: **Python 3.11+** (developed with 3.14) and **Node.js 20+** (developed with 24). Commands are for **Windows PowerShell**.

```powershell
git clone https://github.com/vranasinghe/Earth_Scope.git
cd Earth_Scope
```

### Backend setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env                # optional — all settings have defaults
```

### Frontend setup

```powershell
cd ..\frontend
npm install
```

> If `npm install` fails with `UNABLE_TO_VERIFY_LEAF_SIGNATURE`, something on your network (antivirus HTTPS scanning or a proxy) is intercepting HTTPS. Allow `registry.npmjs.org`, use another network, or configure your proxy's root certificate with `npm config set cafile <path>`. Do not disable certificate checking.

## Running the application

Two PowerShell windows:

**1 — Backend** (in `backend`, venv active):

```powershell
uvicorn app.main:app --reload --reload-dir app --port 8000
```

API docs: <http://127.0.0.1:8000/docs>

**2 — Frontend** (in `frontend`):

```powershell
npm run dev
```

Open <http://localhost:5173>. Vite forwards `/api/*` to `http://127.0.0.1:8000` (override with `VITE_BACKEND_URL`). Production: `npm run build` then `npm run preview`.

**AI assistant (optional):** put your Gemini API key (from <https://aistudio.google.com/apikey>) in `backend/.env`, then restart the backend:

```
EARTHSCOPE_GEMINI_API_KEY=your-key-here
# EARTHSCOPE_GEMINI_MODEL=gemini-2.5-flash
```

Without a key the bubble still appears and explains how to switch it on.

**Background jobs** (large countries, Analysis Jobs page) need PostgreSQL, Redis and a worker. Start them with `docker compose up -d --build` from the repository root, which also serves the API on port 8000, instead of the uvicorn window above. See [Scalable Background Jobs](#14-windows-powershell-workflow). The synchronous analyses work without them.

## API reference

All endpoints are `GET`. Errors share one shape:

```json
{ "error": "LOCATION_NOT_SUPPORTED", "message": "…", "details": ["…"], "retryable": false, "suggested_variables": ["air_temperature"] }
```

| Endpoint | Purpose |
|---|---|
| `/api/health` | Health check |
| `/api/variables` | Catalogue with availability metadata, year limits, α, documentation links |
| `/api/data` | Cleaned monthly series + annual aggregation for one point |
| `/api/analyze` | `/api/data` + regression, Mann-Kendall, Sen's slope, evidence, interpretation |
| `/api/compare` | Same analysis for 2–3 points (fetched in parallel, max 3 NASA requests at once) + comparison summary |
| `/api/geocode/search?q=` | Worldwide place search (or `lat, lon` parsing) |
| `/api/geocode/reverse?latitude=&longitude=` | Place name for a point (`place: null` over open ocean) |
| `/api/ai/status` | Whether the AI assistant has a Gemini key configured |
| `POST /api/ai/chat` | Ask about the current page (request/response shape: see [AI assistant API](#api-1)) |
| `/api/regional/config` | Regional variables, size limits (2°–9°), grid resolution, default coverage threshold, presets |
| `/api/regional/preview` | Validates a box and returns its area and expected cells **without calling NASA** |
| `/api/regional/data` | Area-weighted monthly + annual regional series, per-cell metadata, coverage, warnings |
| `/api/regional/analyze` | `/api/regional/data` + the full standard and advanced statistics and interpretation |
| `/api/regional/spatial-trends` | Per-grid-cell trends + raw / BH / BY significance for one test (`method`, `correction`, `alpha`) |
| `/api/regional/spatial-trends/cell` | One cell's annual series and full statistics (`cell_id`) |
| `GET /api/boundaries/countries` | Countries with an available boundary (ISO3, name, source) |
| `GET /api/boundaries/countries/{iso3}` | Boundary (display GeoJSON), areas, metadata, licence and preflight (`variable`, `start_year`, `end_year`) |
| `POST /api/polygon/preview` | Validate an area (`iso3` **or** `geometry`) and estimate cells, tiles, data volume and budgets — no NASA call |
| `POST /api/polygon/analyze` | Polygon-weighted series + full statistics (same response as `/api/regional/analyze`, plus area metadata and the tile manifest) |
| `POST /api/polygon/spatial-trends` | Per-cell trends inside the area (+ `method`, `correction`, `alpha`) |
| `POST /api/polygon/spatial-trends/cell` | One cell's detail (+ `cell_id`) |

Regional parameters: `variable`, `lat_min`, `lat_max`, `lon_min`, `lon_max` (decimal degrees, each side 2°–9°, `lon_min < lon_max`), optional `start_year`, `end_year`, `coverage_threshold` (0.5–1.0, default 0.8).

Parameters for `/api/data` and `/api/analyze`: `variable` (id or NASA parameter), `latitude` (−90…90), `longitude` (−180…180), optional `start_year` (≥ 1981, default 2001), `end_year` (default: latest normally complete year; span ≥ 10).

`/api/compare`: `variable`, `locations=lat,lon;lat,lon[;lat,lon]`, optional `labels=label;label;label`, `start_year`, `end_year`.

| Error code | HTTP | Meaning |
|---|---|---|
| `INVALID_REQUEST` | 422 | Missing/malformed parameters, too few/many comparison points |
| `INVALID_COORDINATES` | 422 | Latitude/longitude out of range or not numbers |
| `TEMPORAL_RANGE_UNAVAILABLE` | 422 | Years outside 1981–present, reversed, or < 10 years |
| `PARAMETER_NOT_AVAILABLE` | 404 | Variable not in the catalogue / rejected by NASA |
| `LOCATION_NOT_SUPPORTED` | 422 | Variable not meaningful here (e.g. GWETTOP over water/ice) or NASA rejected the point |
| `NO_VALID_DATA` | 404 | NASA returned only missing values |
| `NASA_API_UNAVAILABLE` | 502/503 | NASA unreachable, failing, rate-limiting or malformed (retryable) |
| `GEOCODER_UNAVAILABLE` | 503 | Place search unavailable (map and coordinates still work) |
| `INVALID_REGION` | 422 | Bounding box malformed (min ≥ max, out of range, missing values) |
| `REGION_TOO_LARGE` | 422 | A side spans more than 9° |
| `REGION_TOO_SMALL` | 422 | A side spans less than 2° (use Point Analysis) |
| `ANTIMERIDIAN_NOT_SUPPORTED` | 422 | `lon_min > lon_max` (region crosses ±180°) |
| `INVALID_GEOMETRY` | 422 | Polygon rejected (self-intersection, < 3 distinct vertices, zero area, bad coordinates, ambiguous date-line edge, wrong type) |
| `GEOMETRY_TOO_COMPLEX` | 422 | Too many vertices / parts, or request body over the limit |
| `COUNTRY_NOT_FOUND` | 404 | Unknown ISO 3166-1 alpha-3 code |
| `BOUNDARY_SOURCE_UNAVAILABLE` | 503 | The boundary file could not be downloaded (retryable) |
| `ANALYSIS_TOO_LARGE` | 422 | The area needs more cells, NASA requests or values than the budget |
| `INCOMPLETE_TILE_RETRIEVAL` | 503 | One or more NASA tiles failed after retries; no partial result (retryable) |
| `INSUFFICIENT_DATA_FOR_ANALYSIS` | 200 | In `analysis_error`: data shown, but too few usable years for trend tests |
| `NO_VARIATION_IN_DATA` | 200 | In `analysis_error`: every usable annual value is identical, so no trend is estimated |

## Example usage

**Browser:** Explore → search "Nairobi" → Enter → choose the result → **Analyze**. Or Compare → **Run example** (New York vs Tokyo vs Sydney). Or Regional Analysis → preset *Central Amazon* → **Run Regional Analysis**.

**PowerShell:**

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/analyze?variable=T2M&latitude=-33.8688&longitude=151.2093&start_year=2001&end_year=2025" |
  Select-Object -ExpandProperty statistics
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/compare?variable=T2M&locations=40.7128,-74.006;35.6762,139.6503;-33.8688,151.2093&labels=New York;Tokyo;Sydney"
```

## Testing

```powershell
# Backend unit/integration tests (mocked NASA + Nominatim), from backend with venv active
python -m pytest

# Live smoke test against the real NASA POWER and Nominatim services (internet required)
python scripts/live_smoke_test.py

# Live cross-validation: app output vs an independent recomputation from raw NASA JSON
python scripts/live_validation.py

# Live regional validation: area-weighted series recomputed independently from raw NASA regional JSON
python scripts/live_regional_validation.py

# Live spatial validation: every cell's trend tests and the FDR correction recomputed from raw NASA JSON
python scripts/live_spatial_validation.py

# Live country / polygon validation: tiles re-downloaded, merged, weighted and analysed independently
python scripts/live_polygon_validation.py

# Rebuild the country-boundary catalogue (geoBoundaries gbOpen + Natural Earth fallback)
python scripts/build_boundary_index.py

# Frontend
npm run lint      # Oxlint
npm run test      # Vitest + React Testing Library (colour scale, styling, exports, controls, legend, summary)
npm run build     # type-check + production build
```

`tests/test_global.py` runs the full analysis for Colombo, New York, London, Tokyo, Nairobi, Sydney, São Paulo and Reykjavik plus the equator, both poles, longitudes ±180 and both sides of the date line — checking that the NASA request uses exactly the selected coordinates, that requested/returned coordinates are reported, and that statistics are correct. It also covers invalid coordinates (lat ±95, lon ±200, …), soil wetness over water, no-data responses, variable metadata, the geocoder (parsing, caching, 1 req/s throttle, failures, ocean reverse lookups) and the comparison endpoint (sequential fetching, per-location failures, validation). The other test files cover parsing, missing values, annual aggregation, OLS/Mann-Kendall/Sen against hand-computed results, confidence intervals, NASA error classification and API validation. Synthetic series are used **only** in tests.

The live smoke test verifies the catalogue against NASA's parameter manager, runs all 3 variables at all 8 cities on real data, checks that ocean soil wetness is refused, and performs a real search and reverse lookup.

**Independent validation.** `tests/test_statistical_validation.py` recomputes OLS (closed form, t-test via the incomplete beta function), Mann-Kendall (brute-force S, tie-corrected variance, continuity-corrected Z) and Sen's slope (brute-force median) **without** `scipy.stats.linregress` or `pymannkendall`, on synthetic datasets: A perfect increase, B perfect decrease, C constant, D/E noisy increase/decrease, F random, G monthly series with missing values (day-weighted annual means, incomplete years). `scripts/live_validation.py` does the same against the raw NASA POWER JSON for Colombo, New York, Tokyo, Nairobi, Sydney, São Paulo and Reykjavik (all 3 variables) and also checks units, sources, missing-month counts, gap handling and coordinates. `tests/test_reliability.py` covers caching (error payloads never cached; entries isolated by variable, years and coordinates), grid-cell geometry, unit handling and that internal errors are never exposed.

| Test type | What it uses | Command |
|---|---|---|
| Unit / integration | Mocked NASA POWER + Nominatim | `python -m pytest` |
| Live smoke test | Real NASA POWER + Nominatim | `python scripts/live_smoke_test.py` |
| Live cross-validation | Real NASA POWER, independent maths (incl. Hamed–Rao, Yue–Wang, Sen CI, HAC) | `python scripts/live_validation.py` |
| Live regional validation | Real NASA POWER regional API, independent area weighting | `python scripts/live_regional_validation.py` |
| Live spatial validation | Real NASA POWER regional API, independent per-cell statistics and FDR | `python scripts/live_spatial_validation.py` |
| Live polygon validation | Real NASA POWER tiles + geoBoundaries, independent merging, weights and statistics | `python scripts/live_polygon_validation.py` |
| Background jobs (unit/integration) | SQLite + fakeredis + mocked NASA, simulated crashes | `python -m pytest tests/test_jobs.py` |
| Live background-job validation | Real NASA POWER through the real worker pipeline; equality with the synchronous path; independent recomputation | `python scripts/live_job_validation.py LKA` |
| Docker failure drill | Running Compose stack; kills the worker and restarts the API, PostgreSQL and Redis during real jobs | `python scripts/docker_failure_drill.py USA` |
| Frontend unit/component | Vitest + jsdom + React Testing Library | `npm run test` |

`tests/test_polygon_analysis.py` (46 tests) uses mocked NASA tiles and mocked boundary downloads:
- **A** the catalogue, ISO mapping, Natural Earth fallback, repair reporting, download allow-list and caching.
- **B** invalid polygons are rejected (not repaired), plus holes, multi-part shapes and date-line splitting.
- **C/D** full, partial, touching-only, hole and disconnected overlaps; areas checked against numerical integration, pyproj and rectangle mode.
- **E** tile limits, coverage of every needed centre, minimum-size expansion, deduplication, conflicting duplicates, off-grid centres, missing cells, retries and backoff, and no partial results.
- **F/G** polygon-weighted means checked against an explicit weighted loop, OLS checked against `numpy.polyfit`, and the vectorised annual means shown to equal `aggregate_annual` for every cell.
- **H/I** the FDR family is exactly the polygon's cells (q-values checked against statsmodels), opposing trends, and the regional slope equal to Σw·b.
- **J/K** missing months, tile failures, budget refusal before any NASA call, validation errors, land-only areas, a date-line polygon and a mocked country analysis.

The frontend tests (`src/**/*.test.ts(x)`) cover:
- polygon validation (crossing edges, collinear vertices, limits);
- GeoJSON upload parsing;
- URL round-trips, which never fall back to a rectangle;
- date-line display;
- the country combobox (filtering, keyboard selection, the Natural Earth label);
- the polygon panel (drawing, deleting, uploading);
- the preflight card (available, refused, server errors);
- the existing spatial tests.

`scripts/live_polygon_validation.py` passed for **the tested extents only**:
- Sri Lanka, the whole country (geoBoundaries);
- sub-region polygons in the Indo-Gangetic Plain, Kenya (across the equator, soil wetness), the Central Amazon (relative humidity, 4 tiles, 21 duplicate cells merged) and SE Australia;

It is not a validation of whole-country results for India, Kenya, Brazil or Australia.

`tests/test_spatial_trends.py` (30 tests) uses mocked NASA responses:
- **A/B** known increasing and decreasing trends per cell, checked against `numpy.polyfit`, brute-force Mann-Kendall S and p, and the median of pairwise slopes; exact linear series recover the true slope.
- **C** opposing local trends stay visible, and the regional slope equals Σw·b exactly.
- **D** constant series are never significant.
- **E** missing months and years, too few years, all-missing cells and invalid values.
- **F** BH and BY against statsmodels and the 1995 worked example (ties, order, invalid p-values); one test per family; the conservative variant kept separate from canonical.
- **G** α changes alter neither the family nor any p-value.
- **H** correlated-null Monte Carlo; BY discoveries are a subset of BH's.
- **I** cell set, spherical overlaps, weights and clipping.
- **J** per-cell results equal the point engine on the same series.
- **API:** one NASA request reused across settings and cell details, settings validation, outage without fallback, ocean rejection, gzip.

`scripts/live_spatial_validation.py` checked 391 real cells in five regions (Sri Lanka, the Indo-Gangetic Plain, Kenya soil wetness, Central Amazon humidity and SE Australia). Every cell's annual means, OLS, Mann-Kendall, Sen's slope, BH q-value and classification matched; so did BY on canonical Hamed–Rao (vs statsmodels) and the detail endpoint.

`tests/test_regional.py` (43 tests) covers the regional feature with mocked NASA responses:
- **Geometry:** box validation and every error code; spherical areas checked against SciPy `dblquad` and the full sphere; expected cells tiling the box exactly.
- **Parsing:** duplicate centres, cells outside the box, `-999`, and the annual `YYYY13` key.
- **Weighting:** area-weighted means checked against a brute-force reference at high latitude; SD, min and max; normalised weights summing to 1 (including a 15 % corner cell); the coverage threshold.
- **Trends:** uniform trends; opposing trends, where the regional slope equals Σ wᵢ·bᵢ; exact cancellation, which correctly returns `NO_VARIATION_IN_DATA`.
- **Aggregation and land-only rules:** day-weighted annual means; too few years; water-cell exclusion and ocean rejection for soil wetness.
- **API:** request parameters, caching, validation, outages, `/config` and `/preview`, and a check that point analysis is unchanged.

`scripts/live_regional_validation.py` downloads real regional responses for 9 regions and recomputes the regional series independently. The regions are Sri Lanka, India, Brazil, Kenya (crossing the equator), SE Australia, Central Europe, the US Corn Belt, N Scandinavia (high latitude) and a mixed land/ocean box. The script also confirms that soil wetness over the South Atlantic is refused.

`tests/test_advanced_statistics.py` validates the autocorrelation-aware methods against **statsmodels** (ACF, Ljung–Box, HAC), **pymannkendall** (Hamed–Rao, Yue–Wang) and from-scratch references (gap-aware Hamed–Rao, Sen 1968 interval). It covers no / positive / negative autocorrelation, increasing, decreasing, constant and random series, missing years, ties and small samples. It also includes coverage simulations (the Sen interval contains the true slope ~95% of the time; HAC intervals cover better than OLS under autocorrelation) and a 60-series property test that autocorrelation-aware evidence is never more significant than the standard evidence.

## Scientific limitations

- **Point-based:** each point result is one NASA POWER grid cell. A trend at one location does not represent a city, country, continent or the globe.
- **Regional = rectangle:** a regional result is the area-weighted mean over the selected rectangle (2°–9° per side), not over a country or administrative area, and an average can hide opposing local trends. See [Regional limitations](#regional-limitations).
- **Countries and polygons:** results describe one boundary representation at ~55 km grid resolution, within the cell and request budgets. See [Country / polygon limitations](#country--polygon-limitations).
- **Model-derived data:** MERRA-2 reanalysis, not station measurements; local effects (urban heat, terrain, coastlines) may be poorly resolved, especially where a grid cell mixes land and sea.
- **Soil wetness** is only meaningful over ice-free land and is a relative fraction, not volumetric soil moisture.
- **Serial correlation** is diagnosed and partly accounted for (Hamed–Rao modified Mann-Kendall, Newey–West regression errors), but with 10–45 annual values autocorrelation estimates are imprecise. The standard OLS, Mann-Kendall and Sen intervals still assume independence, the adjustment only considers lags 1–3, variance reductions are deliberately not applied, and results with fewer than 20 years or with missing years are flagged as less reliable.
- **Short records** (10–45 years) limit statistical power; non-significant ≠ no change.
- **Multiple testing:** comparing many locations/variables raises the chance of false positives at α = 0.05. The spatial map corrects for this across cells (BH/BY), but not across the several variables, regions or tests a user might try.
- **Incomplete years** (10–11 valid months) are averaged over the available months only.
- **Map:** Web-Mercator tiles cannot display beyond ≈ ±85° latitude; polar points can still be entered as coordinates.
- **Place search** depends on the public Nominatim service and its rate limit; names are approximate and display-only.
- **Causation:** a significant trend does not identify its cause.

## Future development

- **Larger areas:** user accounts so background jobs follow a person across browsers, an object-storage adapter for artifacts, vector tiles for maps far beyond ~11k cells, ADM1/ADM2 boundaries from geoBoundaries, and antimeridian-crossing rectangles (the tiler already supports this for polygons).
- **Spatial statistics:** field significance of the whole pattern (e.g. Livezey & Chen / Wilks 2016 resampling), spatially aware FDR (block bootstrap), seasonal per-cell trends, and a slope-uncertainty layer (CI width).
- More parameters (precipitation `PRECTOTCORR`, root-zone wetness `GWETROOT`, solar radiation, wind) via the catalogue; other NASA sources (GPM, MODIS, GLDAS) as separate services.
- Seasonal Mann-Kendall on monthly data, block-bootstrap confidence intervals, an autocorrelation-adjusted Sen interval, change-point detection, anomaly baselines.
- Persistent cache and deployment configuration.

## Credits & attribution

Data: NASA Langley Research Center (LaRC) POWER Project, funded through the NASA Earth Science/Applied Science Program. Map tiles and place search © OpenStreetMap contributors (Nominatim). Country boundaries come from geoBoundaries (Runfola, D. et al. 2020, *geoBoundaries: A global database of political administrative boundaries*, PLoS ONE 15(4): e0231866). Each country carries its own licence, shown with every result, for example ODbL 1.0 for boundaries derived from OpenStreetMap. Boundaries for codes absent from gbOpen are "Made with Natural Earth" (public domain). Earth Scope is an independent educational project and is not affiliated with or endorsed by NASA.
