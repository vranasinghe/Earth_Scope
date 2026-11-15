<div align="center">

# 🌍 Earth Scope

### Discover how our planet is changing — with real NASA data and rigorous statistics.

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)](https://vite.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Data: NASA POWER](https://img.shields.io/badge/Data-NASA%20POWER-0B3D91)](https://power.larc.nasa.gov/)

[Features](#-features) •
[Tech Stack](#-tech-stack) •
[Architecture](#-architecture) •
[Getting Started](#-getting-started) •
[API](#-api-overview) •
[Testing](#-testing) •
[Documentation](#-documentation)

</div>

---

## 📖 Overview

**Earth Scope** is a full-stack, web-based Earth-science platform that measures and tests long-term environmental change **anywhere on the planet**. Choose a point, a rectangle, a country or your own polygon, and Earth Scope pulls **real NASA POWER** monthly data, visualises the change over time, and tells you whether the trend is **statistically significant**. Results come with plain-language explanations for non-specialists.

It answers four questions:

| Question | How Earth Scope answers it |
| --- | --- |
| **What** is changing? | Air temperature (`T2M`), relative humidity (`RH2M`) and soil wetness (`GWETTOP`) |
| **Where** is it changing? | Any latitude/longitude, a rectangular region, a country boundary or a custom polygon |
| **How much** is it changing? | OLS regression slope and Sen's slope, in the variable's own units per year |
| **Is** the change significant? | Regression p-value with 95% CI, the Mann-Kendall test, and autocorrelation-aware variants |

**Built for** students, researchers, educators and curious members of the public.

### Principles

- **Real data only.** No fabricated, zero-filled or interpolated values in live mode.
- **Transparent statistics.** Independent tests are reported side by side, and the app says so when they disagree.
- **Honest interpretation.** Every result explains what it does **not** show, such as causation or a city-wide average.
- **Approachable code.** The code stays simple enough for university students to extend.

---

## ✨ Features

| Module | Highlights |
| --- | --- |
| 📍 **Point Analysis** | Worldwide place search, a clickable world map with a draggable marker, manual coordinates and continent presets. Shows the exact NASA grid cell analysed. |
| 📈 **Trend Results** | Monthly and annual charts with trend lines, key result cards, full statistics, a rule-based interpretation, a data table, data provenance and CSV/JSON export. |
| 🧮 **Advanced Statistics** | Autocorrelation diagnostics (ACF, Ljung–Box), the Hamed–Rao modified Mann-Kendall test, Sen's slope confidence interval and Newey–West (HAC) regression. |
| 🗺️ **Regional Analysis** | Draw or type a 2°–9° rectangle for an area-weighted average of every grid cell inside it, with a live preview before any data is fetched. |
| 🔥 **Spatial Trend Explorer** | Per-cell trend maps (magnitude, direction, significance, availability) with Benjamini–Hochberg / Benjamini–Yekutieli false-discovery-rate correction. |
| 🏳️ **Country & Polygon Analysis** | Analyse any country (geoBoundaries / Natural Earth) or a drawn or uploaded GeoJSON polygon, with exact area weighting and tiled NASA requests. |
| ⚙️ **Background Jobs** | Durable, resumable analysis of large countries using PostgreSQL, Redis and RQ workers, with progress tracking, checkpoints, cancellation and retry. |
| 🆚 **Compare** | Compare 2–3 locations side by side, including a "change vs own average" view, so you compare trends rather than absolute levels. |
| 🤖 **"Ask me" AI Assistant** | An optional Google Gemini chat that summarises the current results page and answers follow-up questions. The API key stays on the server. |
| 🎓 **Learn** | Plain-language guides to time series, regression, Mann-Kendall, p-values, confidence intervals and causation. |

---

## 🛠 Tech Stack

| Layer | Technologies |
| --- | --- |
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS v4, Recharts, React Leaflet, React Router, Lucide React |
| **Backend** | Python 3.11+, FastAPI, Uvicorn, Pydantic, Pandas, NumPy, SciPy, pymannkendall |
| **Geospatial** | Shapely 2, pyproj, geoBoundaries (gbOpen ADM0), Natural Earth (fallback) |
| **Jobs & Storage** | PostgreSQL 16, SQLAlchemy, Alembic, Redis 7, RQ |
| **AI** | Google Gemini (`google-genai`), optional |
| **External Data** | NASA POWER monthly point and regional APIs, OpenStreetMap Nominatim (geocoding) |
| **Quality** | pytest, statsmodels (independent validation), Vitest, React Testing Library, Oxlint |
| **DevOps** | Docker, Docker Compose |

---

## 🏗 Architecture

```text
┌──────────────────────┐   /api/*   ┌───────────────────────────────┐  HTTPS  ┌──────────────────────────┐
│  React + Vite (SPA)  │──────────▶ │        FastAPI backend        │───────▶ │ NASA POWER (point/region)│
│  maps · charts · UI  │            │ routes → services → statistics│───────▶ │ OSM Nominatim (geocoding)│
└──────────────────────┘            └──────────────┬────────────────┘───────▶ │ Google Gemini (optional) │
                                                   │                          └──────────────────────────┘
                                   enqueue / status│
                                                   ▼
                              ┌────────────┐   ┌────────────┐   ┌──────────────────────┐
                              │ PostgreSQL │◀──│ RQ workers │──▶│ Redis queue + locks  │
                              │ job records│   │ + scheduler│   └──────────────────────┘
                              └────────────┘   └────────────┘
```

- The browser never calls NASA, Nominatim or Gemini directly. All external traffic goes through the backend.
- Place names are for display only. NASA data is always requested by the user's selected coordinates.
- Point, regional and polygon analyses run synchronously. Very large areas run as **background jobs**.

### Project structure

```text
Earth_Scope/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, error handlers
│   │   ├── api/routes/        # health, variables, data, analysis, compare, geocode,
│   │   │                      # regional, areas, jobs, ai
│   │   ├── core/              # settings (EARTHSCOPE_* env vars), variable catalogue
│   │   ├── services/          # NASA client, data processing, trend & advanced statistics,
│   │   │                      # regional / spatial / polygon analysis, geocoding, AI chat
│   │   ├── jobs/              # background job queue, worker, reconciler, pipeline
│   │   ├── ai/                # Gemini client, rate limiting, system prompt
│   │   ├── models/            # Pydantic schemas
│   │   └── utils/             # validators, error codes, grid helpers
│   ├── migrations/            # Alembic database migrations
│   ├── scripts/               # live validation & maintenance scripts
│   ├── tests/                 # pytest suite
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/             # Home, Explore, Results, RegionalExplore, RegionalResults,
│   │   │                      # Compare, AnalysisJobs, JobDetails, Learn
│   │   ├── components/        # layout, map, charts, analysis, spatial, region, jobs, ai
│   │   ├── hooks/ services/   # data fetching and API client
│   │   └── utils/ types/      # helpers and TypeScript API types
│   └── vite.config.ts         # dev server with /api proxy
├── docs/
│   └── TECHNICAL_REFERENCE.md # full methodology & engineering documentation
├── docker-compose.yml         # PostgreSQL, Redis, API, worker, scheduler
└── .env.example
```

---

## 🚀 Getting Started

### Prerequisites

- **Python** 3.11 or newer
- **Node.js** 20 or newer
- **Docker Desktop**, only needed for background jobs (large-country analysis)
- No NASA API key is required.

### 1. Clone the repository

```bash
git clone https://github.com/vranasinghe/Earth_Scope.git
cd Earth_Scope
```

### 2. Backend setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # optional: every setting has a default
uvicorn app.main:app --reload --reload-dir app --port 8000
```

Interactive API docs are then served at **<http://127.0.0.1:8000/docs>**.

### 3. Frontend setup

Run this in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **<http://localhost:5173>**. Vite forwards `/api/*` requests to the backend on port 8000.

### 4. Background jobs (optional)

Large-country analyses need PostgreSQL, Redis and a worker. Start the full stack from the repository root. It also serves the API on port 8000, so use it **instead of** the `uvicorn` command above:

```powershell
copy .env.example .env              # then set POSTGRES_PASSWORD
docker compose up -d --build
docker compose up -d --scale worker=2   # optional: more workers
docker compose down                     # stop the stack (data volumes are kept)
```

### 5. AI assistant (optional)

Add a Google Gemini API key ([get one here](https://aistudio.google.com/apikey)) to `backend/.env` (or the root `.env` when using Docker), then restart the backend:

```env
GEMINI_API_KEY=your-key-here
# GEMINI_MODEL=gemini-2.5-flash
```

Without a key, the rest of Earth Scope works normally and the chat bubble explains how to enable it.

> 🔐 **Never commit `.env` files.** They are already listed in `.gitignore`. Keep API keys on the server and never put them in `VITE_*` variables.

---

## ⚙️ Configuration

| File | Purpose |
| --- | --- |
| [`backend/.env.example`](backend/.env.example) | Backend settings: NASA timeouts, cache, analysis thresholds, CORS, geocoder, Gemini |
| [`frontend/.env.example`](frontend/.env.example) | Backend URL for the Vite proxy, or a separately hosted API |
| [`.env.example`](.env.example) | Docker Compose: database credentials, API port, ops token, Gemini |

All backend settings use the `EARTHSCOPE_` prefix. Gemini settings also accept the plain `GEMINI_*` names.

---

## 🔌 API Overview

Most endpoints are `GET` and return JSON. All errors share one consistent shape with a stable error code.

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Health check |
| `GET /api/variables` | Variable catalogue and availability metadata |
| `GET /api/analyze` | Full trend analysis for one point |
| `GET /api/compare` | Side-by-side analysis for 2–3 points |
| `GET /api/geocode/search` | Worldwide place search |
| `GET /api/regional/analyze` | Area-weighted analysis of a rectangle |
| `GET /api/regional/spatial-trends` | Per-grid-cell trends with FDR correction |
| `GET /api/boundaries/countries` | Countries with available boundaries |
| `POST /api/polygon/analyze` | Country or custom polygon analysis |
| `POST /api/ai/chat` | Ask the AI assistant about the current page |

**Example request:**

```bash
curl "http://127.0.0.1:8000/api/analyze?variable=T2M&latitude=6.9271&longitude=79.8612&start_year=2001&end_year=2025"
```

The complete endpoint list, parameters, background-job API and error codes are in the [Technical Reference](docs/TECHNICAL_REFERENCE.md#api-reference).

---

## 🧪 Testing

```bash
# Backend: unit & integration tests (NASA and Nominatim are mocked)
cd backend
python -m pytest

# Backend: live checks against the real NASA POWER API (internet required)
python scripts/live_smoke_test.py
python scripts/live_validation.py

# Frontend: lint, unit/component tests and production build
cd frontend
npm run lint
npm run test
npm run build
```

The statistical engine is validated independently against **statsmodels**, **pymannkendall**, **SciPy** and from-scratch reference implementations. Live scripts recompute point, regional, spatial and polygon results directly from raw NASA JSON.

---

## 🔬 Methodology at a Glance

1. **Clean.** NASA fill values (`-999`) and invalid values are excluded, never zero-filled.
2. **Aggregate.** Annual values are day-weighted means. Years with fewer than 10 valid months are excluded from trend tests.
3. **Test.** OLS regression, the Mann-Kendall test and Sen's slope, at α = 0.05, with at least 10 usable years.
4. **Adjust.** Autocorrelation-aware checks (Hamed–Rao, Newey–West). These are never more significant than the standard result.
5. **Correct.** Spatial maps control the false discovery rate across grid cells (BH/BY).
6. **Explain.** Rule-based interpretation that states the limitations as well as the findings.

See the [Technical Reference](docs/TECHNICAL_REFERENCE.md) for formulas, design decisions and validation details.

---

## ⚠️ Limitations

- Results describe NASA POWER grid cells (≈ 0.5° × 0.625°, about 55 × 70 km), not individual streets or buildings.
- The data is **MERRA-2 reanalysis** (model-derived), not station measurements.
- Soil wetness is only meaningful over ice-free land, and it is a relative fraction, not volumetric soil moisture.
- Short records (10–45 years) limit statistical power: "not significant" does not mean "no change".
- A significant trend does **not** identify its cause.

---

## 🗺 Roadmap

- [ ] More variables, such as precipitation, root-zone soil wetness, solar radiation and wind
- [ ] Seasonal Mann-Kendall and change-point detection
- [ ] ADM1/ADM2 sub-national boundaries
- [ ] User accounts so background jobs follow a person across devices
- [ ] Object storage for artifacts and vector tiles for very large maps
- [ ] Field-significance testing for whole spatial patterns

---

## 📚 Documentation

| Document | Contents |
| --- | --- |
| [Technical Reference](docs/TECHNICAL_REFERENCE.md) | Full methodology, statistics, regional/spatial/polygon pipelines, background-job architecture, API reference, error codes and test coverage |
| [Frontend README](frontend/README.md) | Frontend-specific notes |

---

## 🤝 Contributing

Contributions, issues and feature requests are welcome.

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/your-feature`.
3. Commit your changes: `git commit -m "Add your feature"`.
4. Push the branch: `git push origin feature/your-feature`.
5. Open a Pull Request.

Before submitting, please make sure `python -m pytest`, `npm run lint`, `npm run test` and `npm run build` all pass.

---

## 🙏 Acknowledgements

- **Data:** [NASA Langley Research Center POWER Project](https://power.larc.nasa.gov/), funded through the NASA Earth Science / Applied Science Program
- **Maps & geocoding:** © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (Nominatim)
- **Boundaries:** [geoBoundaries](https://www.geoboundaries.org/) (Runfola et al., 2020, *PLoS ONE* 15(4): e0231866) and [Natural Earth](https://www.naturalearthdata.com/) (public domain)

> Earth Scope is an independent educational project. It is not affiliated with or endorsed by NASA.

---

<div align="center">

Made with 💙 for a better understanding of our changing planet.

⭐ If you find this project useful, consider giving it a star!

</div>
