"""In-memory rate limiting and a small TTL cache for the API."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Sliding-window limits per (client, bucket), plus temporary bans.

    Repeated authentication failures from one address block it for a while:
    guessing keys becomes pointless.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._blocked: dict[str, float] = {}

    def blocked_for(self, client: str) -> float:
        until = self._blocked.get(client)
        if until is None:
            return 0.0
        remaining = until - self._clock()
        if remaining <= 0:
            del self._blocked[client]
            return 0.0
        return remaining

    def hit(self, client: str, bucket: str, limit: int, window: float = 60.0) -> float:
        """Record a request; return seconds to wait (0 when allowed)."""
        now = self._clock()
        hits = self._hits.setdefault((client, bucket), deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return max(0.1, hits[0] + window - now)
        hits.append(now)
        if len(self._hits) > 10_000:  # keep memory bounded under a flood
            self._prune(now - window)
        return 0.0

    def auth_failure(self, client: str, limit: int, block_seconds: float) -> None:
        if self.hit(client, "auth-fail", limit) > 0:
            self._blocked[client] = self._clock() + block_seconds

    def _prune(self, older_than: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= older_than]:
            del self._hits[key]


class TtlCache:
    """Values expire after ``ttl`` seconds or when ``invalidate`` is called."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._data: dict[object, tuple[float, int, object]] = {}
        self.generation = 0

    def get(self, key: object) -> object | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires, generation, value = entry
        if generation != self.generation or self._clock() >= expires:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: object, value: object, ttl: float) -> None:
        if ttl <= 0:
            return
        if len(self._data) > 500:
            self._data.clear()
        self._data[key] = (self._clock() + ttl, self.generation, value)

    def invalidate(self) -> None:
        self.generation += 1
        self._data.clear()
