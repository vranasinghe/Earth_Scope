"""Database engine and sessions for job metadata.

PostgreSQL is the supported database (Docker Compose). SQLite works for tests
and single-process experiments: it is configured with WAL and a busy timeout
so the API, a worker thread and the heartbeat thread can share it.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    raw = url[len("sqlite:///"):]
    if not raw or raw == ":memory:":
        return None
    p = Path(raw)
    return p if p.is_absolute() else (BACKEND_DIR / p)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = _sqlite_path(url)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path.as_posix()}"
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def ensure_schema(engine: Engine | None = None) -> None:
    """Create tables for SQLite (tests / local experiments).

    PostgreSQL schemas are managed only by Alembic (``alembic upgrade head``);
    this function never touches a non-SQLite database.
    """
    from app.jobs.models import Base

    engine = engine or get_engine()
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(engine)


def reset_engine_after_fork() -> None:
    """A forked RQ work-horse must not reuse the parent's pooled connections."""
    if get_engine.cache_info().currsize:
        get_engine().dispose(close=False)


@contextmanager
def session_scope(sm: sessionmaker[Session] | None = None) -> Iterator[Session]:
    s = (sm or get_sessionmaker())()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def is_transient_db_error(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) or (isinstance(exc, DBAPIError) and exc.connection_invalidated)


def with_db_retry(fn: Callable[[], T], *, tolerance_seconds: float | None = None, sleep: Callable[[float], None] = time.sleep) -> T:
    """Run ``fn`` and retry transient database errors (outage / restart) with backoff.

    Used by the worker so a short PostgreSQL restart does not fail a long job.
    Never used to hide a failed *commit* of completion metadata: ``fn`` either
    commits or raises, and completion is only reported after it returned.
    """
    budget = get_settings().job_db_outage_tolerance_seconds if tolerance_seconds is None else tolerance_seconds
    deadline = time.monotonic() + budget
    delay = 1.0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - filtered below
            if not is_transient_db_error(exc) or time.monotonic() + delay > deadline:
                raise
            logger.warning("Database unavailable (%s); retrying in %.0f s", type(exc).__name__, delay)
            sleep(delay)
            delay = min(delay * 2, 15.0)
