"""Client-side request budget.

Liquipedia's API terms allow at most 60 requests per hour. ``RequestBudget`` enforces a
sliding one-hour window per process. When the budget is used up, the caller gets an
error *instead of* a request; nothing is queued or retried.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from liquipedia_mcp.errors import ConfigurationError, LocalRateLimitError, ServerRateLimitError

MAX_REQUESTS_PER_HOUR = 60
WINDOW_SECONDS = 3600.0
DEFAULT_LOCKOUT_SECONDS = 600.0
MIN_LOCKOUT_SECONDS = 60.0


class RequestBudget:
    """Sliding-window limiter plus a lockout after the server answered HTTP 429."""

    def __init__(
        self,
        max_per_hour: int = MAX_REQUESTS_PER_HOUR,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_per_hour, bool) or not isinstance(max_per_hour, int):
            raise ConfigurationError("max_per_hour must be an integer.")
        if not 1 <= max_per_hour <= MAX_REQUESTS_PER_HOUR:
            raise ConfigurationError(
                f"max_per_hour must be between 1 and {MAX_REQUESTS_PER_HOUR}: "
                "Liquipedia's API terms allow at most 60 requests per hour, "
                "so the budget can only be lowered."
            )
        if lockout_seconds < MIN_LOCKOUT_SECONDS:
            raise ConfigurationError(f"lockout_seconds must be at least {MIN_LOCKOUT_SECONDS:.0f}.")
        self.max_per_hour = max_per_hour
        self.lockout_seconds = float(lockout_seconds)
        self._clock = clock
        self._sent: deque[float] = deque()
        self._locked_until = 0.0

    def _prune(self, now: float) -> None:
        while self._sent and now - self._sent[0] >= WINDOW_SECONDS:
            self._sent.popleft()

    @property
    def remaining(self) -> int:
        self._prune(self._clock())
        return self.max_per_hour - len(self._sent)

    def acquire(self) -> None:
        """Record one outgoing request, or raise if none may be sent right now."""
        now = self._clock()
        if now < self._locked_until:
            wait = self._locked_until - now
            raise ServerRateLimitError(
                "Liquipedia answered HTTP 429 (too many requests) recently; this client "
                f"pauses all requests for another {wait:.0f} s.",
                retry_after=wait,
            )
        self._prune(now)
        if len(self._sent) >= self.max_per_hour:
            wait = WINDOW_SECONDS - (now - self._sent[0])
            raise LocalRateLimitError(
                f"Request budget of {self.max_per_hour} requests per hour is used up "
                f"(Liquipedia API terms). Next request possible in {wait / 60:.0f} min. "
                "Cached answers are still served.",
                retry_after=wait,
            )
        self._sent.append(now)

    def lock_out(self, retry_after: float | None = None) -> float:
        """Stop all requests after a 429. Honours a longer ``Retry-After``."""
        seconds = max(self.lockout_seconds, retry_after or 0.0)
        self._locked_until = max(self._locked_until, self._clock() + seconds)
        return seconds
