"""RQ (Redis Queue) integration.

RQ only delivers "run job <id>" messages. Whether a job runs, and what state
it is in, is decided by compare-and-set updates on the PostgreSQL row, so a
message that is lost (Redis restart) is re-sent by the reconciler, and a
message delivered twice is ignored by the second worker.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Any, Callable

import redis
from rq import Queue

from app.core.config import get_settings

logger = logging.getLogger(__name__)
TASK_PATH = "app.jobs.worker.run_job"


@lru_cache
def get_redis() -> redis.Redis:
    s = get_settings()
    return redis.Redis.from_url(s.redis_url, socket_connect_timeout=5, socket_timeout=30, health_check_interval=30)


def get_queue(connection: redis.Redis | None = None) -> Queue:
    s = get_settings()
    return Queue(s.job_queue_name, connection=connection or get_redis(), default_timeout=s.job_rq_timeout_seconds)


def redis_available() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:  # noqa: BLE001 - connection refused, DNS, timeout, ...
        return False


def inline_mode() -> bool:
    """True when jobs run in the API process because Redis is unreachable (see app.jobs.inline)."""
    return get_settings().job_inline_fallback and not redis_available()


class Enqueuer:
    """Callable that hands a job id to the queue; replaceable in tests."""

    def __call__(self, job_id: str) -> str:
        s = get_settings()
        if inline_mode():
            from app.jobs import inline

            inline.start_reconciler()
            return inline.runner.submit(job_id)
        rq_id = f"es-{job_id}-{uuid.uuid4().hex[:8]}"
        get_queue().enqueue(
            TASK_PATH, job_id, job_id=rq_id, job_timeout=s.job_rq_timeout_seconds,
            result_ttl=24 * 3600, failure_ttl=7 * 24 * 3600, description=f"Earth Scope analysis {job_id}",
        )
        return rq_id


_enqueuer: Callable[[str], str] = Enqueuer()


def set_enqueuer(fn: Callable[[str], str]) -> None:
    global _enqueuer
    _enqueuer = fn


def enqueue(job_id: str) -> str:
    return _enqueuer(job_id)


def rq_job_state(rq_id: str | None, connection: redis.Redis | None = None) -> str | None:
    """RQ status of a queued message (None = unknown / expired / Redis unavailable)."""
    if not rq_id:
        return None
    if rq_id.startswith("inline-"):
        from app.jobs.inline import runner

        return runner.state(rq_id)
    try:
        from rq.job import Job

        return str(Job.fetch(rq_id, connection=connection or get_redis()).get_status(refresh=True))
    except Exception:  # noqa: BLE001 - NoSuchJobError, connection errors
        return None


def queue_health(connection: redis.Redis | None = None) -> dict[str, Any]:
    from rq import Worker

    conn = connection or get_redis()
    try:
        conn.ping()
    except redis.RedisError as exc:
        if get_settings().job_inline_fallback:   # jobs run in the API process instead
            return {"redis": False, "error": type(exc).__name__, "workers": 1, "queued": None, "inline": True}
        return {"redis": False, "error": type(exc).__name__, "workers": 0, "queued": None}
    q = get_queue(conn)
    workers = Worker.all(queue=q)
    return {"redis": True, "workers": len(workers), "queued": q.count,
            "worker_states": sorted({str(w.get_state()) for w in workers})}
