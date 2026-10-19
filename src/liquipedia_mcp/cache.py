"""Small size-bounded TTL cache (no background threads, no polling)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


class TTLCache:
    """LRU-evicting cache where every entry carries its own expiry time."""

    def __init__(self, maxsize: int = 256, clock: Callable[[], float] = time.monotonic) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> tuple[bool, Any]:
        """Return ``(hit, value)``; expired entries count as misses."""
        item = self._data.get(key)
        if item is None:
            return False, None
        expires, value = item
        if self._clock() >= expires:
            del self._data[key]
            return False, None
        self._data.move_to_end(key)
        return True, value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
