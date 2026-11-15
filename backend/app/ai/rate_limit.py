"""In-memory request limits for the AI chat (per browser session or IP) and a concurrency cap.

Only request timestamps are kept (keyed by a hash), never message contents. State is
per process and resets on restart, which is acceptable for cost control.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Iterator

from app.ai.errors import AiBusyError, AiRateLimitedError


class ChatLimiter:
    def __init__(self, per_minute: int, per_hour: int, max_concurrency: int):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max(1, max_concurrency))

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > 3600:
                hits.popleft()
            last_minute = sum(1 for t in hits if now - t <= 60)
            if last_minute >= self.per_minute:
                raise AiRateLimitedError("You're sending messages very quickly. Please wait a minute and try again.",
                                         ["Limit: %d messages per minute." % self.per_minute])
            if len(hits) >= self.per_hour:
                raise AiRateLimitedError("You've reached the AI Assistant's hourly message limit. Please try again later.",
                                         ["Limit: %d messages per hour." % self.per_hour])
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 3600][:5000]:
                    self._hits.pop(k, None)

    @contextmanager
    def slot(self) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise AiBusyError("The AI Assistant is busy right now. Please try again in a moment.")
        try:
            yield
        finally:
            self._slots.release()


_limiter: ChatLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter(per_minute: int, per_hour: int, max_concurrency: int) -> ChatLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None or (_limiter.per_minute, _limiter.per_hour) != (per_minute, per_hour):
            _limiter = ChatLimiter(per_minute, per_hour, max_concurrency)
        return _limiter


def reset_limiter() -> None:
    global _limiter
    with _limiter_lock:
        _limiter = None
