"""Q3 - In-memory cache with time-based expiration (TTL) and bounded size.

- Each entry expires `ttl` seconds after being stored (1 hour by default).
- When `max_size` is reached, the least recently used entry is evicted (LRU),
  so memory stays bounded even under millions of distinct requests.
- Thread-safe: usable from Flask's threaded server and from the async client.
- The clock is injectable so expiration can be demonstrated/tested without waiting 1 hour.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

ONE_HOUR = 3600  # seconds


class TTLCache:
    def __init__(
        self,
        ttl: float = ONE_HOUR,
        max_size: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl = ttl
        self.max_size = max_size
        self._clock = clock
        # key -> (expires_at, value); insertion order doubles as LRU order.
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.expired = 0

    def get(self, key: str) -> Any | None:
        """Return the cached value, or None if absent or expired."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None

            expires_at, value = entry
            if self._clock() >= expires_at:
                # Stale entry: drop it so the caller fetches fresh data.
                del self._data[key]
                self.expired += 1
                self.misses += 1
                return None

            self._data.move_to_end(key)  # mark as recently used
            self.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self.ttl, value)
            self._data.move_to_end(key)
            if len(self._data) > self.max_size:
                self._data.popitem(last=False)  # evict least recently used

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = self.expired = 0

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict:
        lookups = self.hits + self.misses
        return {
            "entries": len(self._data),
            "ttl_seconds": self.ttl,
            "hits": self.hits,
            "misses": self.misses,
            "expired": self.expired,
            "hit_rate": round(self.hits / lookups, 4) if lookups else 0.0,
        }
