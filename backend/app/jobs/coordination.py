"""Application-wide NASA POWER request coordination through Redis.

* **Concurrency** — a distributed counting semaphore: a sorted set of slot
  tokens scored by their lease expiry. At most ``limit`` unexpired tokens may
  exist across ALL worker processes and hosts, so four workers share the same
  three slots instead of opening three each. A worker that dies while holding
  a slot frees it automatically when the lease expires (lease > request timeout).
* **Request-start rate** — a shared "next allowed start" timestamp enforces a
  minimum interval between any two NASA request starts.

Both use optimistic WATCH/MULTI transactions (no Lua), and Redis server time,
so clocks of different containers do not matter.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator

import redis

logger = logging.getLogger(__name__)

SLOTS_KEY = "earthscope:nasa:slots"
NEXT_START_KEY = "earthscope:nasa:next_start"


class LimiterCancelled(Exception):
    """Raised while waiting for a slot when the job is being cancelled."""


def _now(r: redis.Redis) -> float:
    sec, usec = r.time()
    return float(sec) + float(usec) / 1e6


class GlobalNasaLimiter:
    def __init__(self, r: redis.Redis, limit: int, lease_seconds: float, min_interval: float,
                 sleep: Callable[[float], None] = time.sleep, poll: float = 0.25):
        self.r = r
        self.limit = max(1, int(limit))
        self.lease = float(lease_seconds)
        self.min_interval = max(0.0, float(min_interval))
        self.sleep = sleep
        self.poll = poll

    # ------------------------------------------------------------ semaphore
    def try_acquire(self, token: str) -> bool:
        with self.r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(SLOTS_KEY)
                    now = _now(self.r)
                    held = pipe.zcount(SLOTS_KEY, f"({now}", "+inf")   # unexpired leases
                    if held >= self.limit:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.zremrangebyscore(SLOTS_KEY, "-inf", now)       # drop leases of crashed holders
                    pipe.zadd(SLOTS_KEY, {token: now + self.lease})
                    pipe.execute()
                    return True
                except redis.WatchError:
                    continue

    def release(self, token: str) -> None:
        try:
            self.r.zrem(SLOTS_KEY, token)
        except redis.RedisError:   # the lease expires on its own
            logger.warning("Could not release NASA slot %s; it will expire after its lease", token)

    def in_use(self) -> int:
        return int(self.r.zcount(SLOTS_KEY, f"({_now(self.r)}", "+inf"))

    # ----------------------------------------------------------- rate limit
    def _reserve_start(self) -> float:
        """Reserve the next request start; returns seconds to wait (0 = may start now)."""
        if self.min_interval <= 0:
            return 0.0
        with self.r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(NEXT_START_KEY)
                    now = _now(self.r)
                    nxt = float(pipe.get(NEXT_START_KEY) or 0.0)
                    if nxt > now:
                        pipe.unwatch()
                        return nxt - now
                    pipe.multi()
                    pipe.set(NEXT_START_KEY, now + self.min_interval, ex=max(1, int(self.min_interval) + 60))
                    pipe.execute()
                    return 0.0
                except redis.WatchError:
                    continue

    @contextmanager
    def slot(self, cancel: threading.Event | None = None, max_wait: float | None = None) -> Iterator[str]:
        """Hold one global NASA request slot (and respect the start-rate limit) while the block runs."""
        token = f"{uuid.uuid4().hex}"
        deadline = None if max_wait is None else time.monotonic() + max_wait
        while not self.try_acquire(token):
            if cancel is not None and cancel.is_set():
                raise LimiterCancelled()
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for a NASA request slot.")
            self.sleep(self.poll)
        try:
            while True:
                wait = self._reserve_start()
                if wait <= 0:
                    break
                if cancel is not None and cancel.is_set():
                    raise LimiterCancelled()
                self.sleep(min(wait, 1.0))
            yield token
        finally:
            self.release(token)
