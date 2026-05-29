"""Rate limiting helpers for the Network Authority API."""

import time
from collections import defaultdict, deque


class RateLimiter:
    """Small in-process sliding-window limiter used as defense-in-depth."""

    def __init__(self):
        """Initialize an empty event store keyed by limiter bucket."""
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        """Return whether a key is still under the limit for the window."""
        now = time.time()
        events = self._events[key]
        while events and now - events[0] > window_seconds:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True
