"""
In-process TTL cache for computed risk scores.

Avoids recomputing scores on every request — scores are expensive (DB queries
+ scoring engine). Default TTL is 1 hour; scores update daily anyway.
"""

import time
from threading import Lock
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Module-level singleton — shared across all requests in the process
score_cache = TTLCache(ttl_seconds=3600)
