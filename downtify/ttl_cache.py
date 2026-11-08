"""A small thread-safe in-memory cache whose entries expire.

Used for answers fetched from YouTube Music that don't change from one
minute to the next (a track's radio mix for the playlist
recommendations): asking again would only make the page wait.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable, Generic, Hashable, Optional, TypeVar

_V = TypeVar('_V')


class TTLCache(Generic[_V]):
    """At most *max_entries* values, each kept *ttl_seconds*; the least
    recently used goes first when it is full."""

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._items: OrderedDict[Hashable, tuple[float, _V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[_V]:
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            if self._clock() - hit[0] >= self._ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return hit[1]

    def set(self, key: Hashable, value: _V) -> None:
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
