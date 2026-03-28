"""Server-side TTL + LRU cache for job column distinct values.

Thread-safe, in-process. No external dependencies.

HCA Layer: shared (pulldb/infra/)

Usage::

    from pulldb.infra.distinct_cache import jobs_distinct_cache

    cached = jobs_distinct_cache.get(view="active", column="dbhost")
    if cached is None:
        cached = compute_distinct_values(...)
        jobs_distinct_cache.set(view="active", column="dbhost", values=cached)
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

_TTL_SECONDS: int = 300   # 5 minutes
_MAX_ENTRIES: int = 500   # LRU eviction above this


class _DistinctCache:
    """LRU+TTL cache keyed on (view, column).

    Thread-safe via a single lock. Evicts the least-recently-used entry when
    the store exceeds ``_MAX_ENTRIES``.  Entries expire after ``_TTL_SECONDS``
    regardless of access frequency.
    """

    def __init__(self, ttl: int = _TTL_SECONDS, max_entries: int = _MAX_ENTRIES) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._store: OrderedDict[tuple[str, str], tuple[float, list]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, view: str, column: str) -> list | None:
        """Return cached values or ``None`` if missing/expired."""
        key = (view, column)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, values = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            # Move to end to record recent access (LRU)
            self._store.move_to_end(key)
            return values

    def set(self, view: str, column: str, values: list) -> None:
        """Store *values* under (view, column), evicting LRU if needed."""
        key = (view, column)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (time.monotonic(), values)
            # Evict oldest entries when over the limit
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def invalidate_view(self, view: str) -> int:
        """Remove all cached entries for *view* (e.g., after bulk job changes).

        Returns the number of entries removed.
        """
        with self._lock:
            keys = [k for k in self._store if k[0] == view]
            for k in keys:
                del self._store[k]
        return len(keys)

    def clear(self) -> None:
        """Flush the entire cache (primarily for testing)."""
        with self._lock:
            self._store.clear()


# Module-level singleton shared across all requests
jobs_distinct_cache = _DistinctCache()
