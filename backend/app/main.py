"""Earth Scope FastAPI application.

Run from the ``backend`` directory:

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import ai, analysis, areas, compare, data, geocode, health, jobs, regional, variables
from app.core.config import get_settings
from app.utils.errors import EarthScopeError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("earthscope")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # SQLite (tests / single-machine experiments) gets its tables created here;
    # PostgreSQL is migrated only by Alembic (`alembic upgrade head`).
    try:
        from app.jobs.db import ensure_schema

        ensure_schema()
    except Exception:  # noqa: BLE001 - the synchronous analyses must keep working without the job database
        logger.exception("Job database unavailable at startup; background jobs are disabled until it recovers")
    try:
        from app.jobs.queue import inline_mode

        if inline_mode():   # no Redis / workers (e.g. a single free-tier instance): recover jobs in-process
            from app.jobs.inline import start_reconciler

            start_reconciler()
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the in-process job reconciler")
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Earth Scope retrieves NASA POWER monthly time series for a point location and tests "
        "them for statistically significant trends (OLS regression, Mann-Kendall, Sen's slope) "
        "for any location worldwide, with optional multi-location comparison and place search. "
        "Large country / polygon analyses run as durable background jobs (/api/analysis/...)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],  # POST carries polygon geometry, job submission, cancel and retry
    allow_headers=["*"],
    allow_credentials=True,  # the anonymous job-session cookie (explicit origin list, never "*")
)
# Regional and spatial-trend responses can be several hundred KB of JSON; compress them.
app.add_middleware(GZipMiddleware, minimum_size=2048)


def _error(
    status: int,
    error: str,
    message: str,
    details: list[str] | None = None,
    retryable: bool = False,
    suggested_variables: list[str] | None = None,
):
    return JSONResponse(
        status_code=status,
        content={
            "error": error,
            "message": message,
            "details": details or [],
            "retryable": retryable,
            "suggested_variables": suggested_variables or [],
        },
    )


@app.exception_handler(EarthScopeError)
async def earthscope_error_handler(_: Request, exc: EarthScopeError):
    return _error(exc.status_code, exc.error, exc.message, exc.details, exc.retryable, exc.suggested_variables)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("query", "body"))
        details.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    code = "INVALID_COORDINATES" if any(d.startswith(("latitude", "longitude")) for d in details) else "INVALID_REQUEST"
    return _error(422, code, "Some request parameters are missing or invalid.", details)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error", exc_info=exc)
    return _error(500, "INTERNAL_ERROR", "An unexpected server error occurred. Please try again.", retryable=True)


for module in (health, variables, data, analysis, compare, geocode, regional, jobs, ai):
    app.include_router(module.router, prefix="/api")
app.include_router(areas.boundary_router, prefix="/api")
app.include_router(areas.polygon_router, prefix="/api")


@app.get("/", include_in_schema=False)
def root():
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}
