"""In-process job runner, used when Redis / RQ workers are not available.

Small single-instance hosts (for example Render's free tier) cannot run the
Redis + worker + reconciler services from Docker Compose. Without them a
submitted job would stay PENDING forever. When ``job_inline_fallback`` is on
and Redis cannot be reached, jobs instead run one at a time on a background
thread inside the API process, and a light reconciler thread keeps retries and
recovery working.

Every state change still goes through the same compare-and-set updates in the
pipeline, so a job delivered twice is still executed only once.
"""

from __future__ import annotations

import logging
import os
import queue
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("earthscope.inline")

INLINE_PREFIX = "inline-"


class LocalNasaLimiter:
    """Process-local replacement for ``GlobalNasaLimiter`` (same ``slot`` interface)."""

    def __init__(self, limit: int, min_interval: float, poll: float = 0.25):
        self._sem = threading.BoundedSemaphore(max(1, int(limit)))
        self._min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._poll = poll

    @contextmanager
    def slot(self, cancel: threading.Event | None = None, max_wait: float | None = None) -> Iterator[str]:
        from app.jobs.coordination import LimiterCancelled

        deadline = None if max_wait is None else time.monotonic() + max_wait
        while not self._sem.acquire(timeout=self._poll):
            if cancel is not None and cancel.is_set():
                raise LimiterCancelled()
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for a NASA request slot.")
        try:
            while True:
                with self._lock:
                    now = time.monotonic()
                    wait = self._next_start - now
                    if wait <= 0:
                        self._next_start = now + self._min_interval
                        break
                if cancel is not None and cancel.is_set():
                    raise LimiterCancelled()
                time.sleep(min(wait, 1.0))
            yield uuid.uuid4().hex
        finally:
            self._sem.release()


class InlineRunner:
    """Runs jobs serially on one daemon thread (keeps memory use predictable on small hosts)."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._waiting: set[str] = set()
        self._running: str | None = None
        self._thread: threading.Thread | None = None
        self._limiter: LocalNasaLimiter | None = None

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="earthscope-inline-worker", daemon=True)
                self._thread.start()

    def limiter(self) -> LocalNasaLimiter:
        from app.core.config import get_settings

        if self._limiter is None:
            s = get_settings()
            self._limiter = LocalNasaLimiter(s.nasa_global_max_concurrency, s.nasa_min_request_interval_seconds)
        return self._limiter

    def submit(self, job_id: str) -> str:
        rq_id = f"{INLINE_PREFIX}{job_id}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._waiting.add(rq_id)
        self._queue.put((job_id, rq_id))
        self._ensure_thread()
        return rq_id

    def state(self, rq_id: str) -> str | None:
        with self._lock:
            if rq_id == self._running:
                return "started"
            if rq_id in self._waiting:
                return "queued"
        return None

    def _loop(self) -> None:
        from app.core.config import get_settings
        from app.jobs.artifacts import get_store
        from app.jobs.db import get_sessionmaker
        from app.jobs.pipeline import execute
        from app.jobs.worker import make_client

        while True:
            job_id, rq_id = self._queue.get()
            with self._lock:
                self._waiting.discard(rq_id)
                self._running = rq_id
            worker_id = f"{socket.gethostname()}:{os.getpid()}:inline:{uuid.uuid4().hex[:6]}"
            try:
                outcome = execute(job_id, worker_id, get_settings(), get_sessionmaker(), get_store(),
                                  self.limiter, make_client)
                logger.info("inline job=%s finished: %s", job_id, outcome)
            except Exception:  # noqa: BLE001 - never let one job kill the runner thread
                logger.exception("inline job=%s crashed", job_id)
            finally:
                with self._lock:
                    self._running = None
                self._queue.task_done()


runner = InlineRunner()

_reconciler_started = False
_reconciler_lock = threading.Lock()


def start_reconciler() -> None:
    """Start the in-process reconciler loop once (retries, lost messages, orphaned jobs, expiry)."""
    global _reconciler_started
    with _reconciler_lock:
        if _reconciler_started:
            return
        _reconciler_started = True

    def loop() -> None:
        from app.core.config import get_settings
        from app.jobs.artifacts import get_store
        from app.jobs.db import get_sessionmaker
        from app.jobs.reconciler import reconcile_once

        settings = get_settings()
        cycle = 0
        while True:
            try:
                reconcile_once(get_sessionmaker(), settings, get_store(), gc_tiles=(cycle % 180 == 0))
            except Exception as exc:  # noqa: BLE001 - try again next cycle
                logger.warning("inline reconcile cycle failed: %s: %s", type(exc).__name__, exc)
            cycle += 1
            time.sleep(settings.job_reconcile_interval_seconds)

    threading.Thread(target=loop, name="earthscope-inline-reconciler", daemon=True).start()
    logger.info("Redis is unavailable: background jobs run in-process (inline fallback)")
