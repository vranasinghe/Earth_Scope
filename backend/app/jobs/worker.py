"""RQ worker process and task entrypoint.

Start (Docker, Linux — forking worker, one work-horse process per job)::

    python -m app.jobs.worker

Native Windows has no ``fork``; the same command automatically uses RQ's
``SimpleWorker`` (job runs in the worker process) with a timer-based timeout.
The supported multi-worker setup is Docker Compose (Linux containers).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import uuid

from app.core.config import get_settings
from app.jobs.artifacts import get_store
from app.jobs.coordination import GlobalNasaLimiter
from app.jobs.db import ensure_schema, get_sessionmaker, reset_engine_after_fork
from app.jobs.pipeline import execute
from app.jobs.queue import get_queue, get_redis
from app.services.nasa_power import NasaPowerClient

logger = logging.getLogger("earthscope.worker")


def make_limiter() -> GlobalNasaLimiter:
    s = get_settings()
    r = get_redis()
    r.ping()
    return GlobalNasaLimiter(r, s.nasa_global_max_concurrency, s.nasa_slot_lease_seconds, s.nasa_min_request_interval_seconds)


def make_client() -> NasaPowerClient:
    # Tiny in-memory cache: verified tiles are checkpointed on disk, so payloads must not pile up in RAM.
    return NasaPowerClient(get_settings().model_copy(update={"cache_max_entries": 1}))


def run_job(job_id: str) -> str:
    """RQ task. Safe to deliver more than once: only one worker can claim a job."""
    reset_engine_after_fork()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    return execute(job_id, worker_id, get_settings(), get_sessionmaker(), get_store(), make_limiter, make_client)


def main() -> None:
    from rq import SimpleWorker, Worker

    parser = argparse.ArgumentParser(description="Earth Scope analysis worker")
    parser.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    ensure_schema()
    get_store()
    conn = get_redis()
    queue = get_queue(conn)
    simple = s.job_worker_class == "simple" or (s.job_worker_class == "auto" and not hasattr(os, "fork"))
    cls = SimpleWorker if simple else Worker
    if simple and os.name == "nt":
        from rq.timeouts import TimerDeathPenalty

        cls.death_penalty_class = TimerDeathPenalty
    worker = cls([queue], connection=conn, name=f"earthscope-{socket.gethostname()}-{os.getpid()}")
    logger.info("Earth Scope worker %s listening on '%s' (%s)", worker.name, queue.name, cls.__name__)
    worker.work(burst=args.burst, logging_level="INFO")


if __name__ == "__main__":
    main()
