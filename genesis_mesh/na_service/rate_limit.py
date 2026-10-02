"""Rate limiting helpers for the Network Authority API.

Two stores share one interface, ``allow(key, limit, window_seconds)``:

* ``RateLimiter`` (in-memory, the SQLite default): a sliding window per
  process. Each gunicorn worker counts on its own.
* ``DatabaseRateLimiter`` (v0.60, required in HA mode): fixed windows counted
  in the shared database with one atomic upsert per request, so the limit is
  enforced across every worker and NA instance.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable

RATE_LIMIT_STORES = ("memory", "database")


@dataclass(frozen=True)
class RateLimits:
    """Requests per minute per client address, by route class (v0.63.1).

    Defaults are the limits every earlier release hard-coded. A deployment
    whose clients share one address (a corporate proxy or NAT) or that runs
    busy controllers raises them; see docs/reference/configuration.md.
    Enrollment limits (``/join``) are anti-abuse controls and stay fixed.
    """

    admin: int = 30
    verify: int = 60
    evidence: int = 120
    read: int = 120

    def __post_init__(self) -> None:
        for name in ("admin", "verify", "evidence", "read"):
            if getattr(self, name) < 1:
                raise ValueError(f"rate limit {name} must be at least 1 per minute")


class RateLimiter:
    """Small in-process sliding-window limiter used as defense-in-depth."""

    store = "memory"

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


class DatabaseRateLimiter:
    """Fixed-window limiter shared through the database (all workers, all instances).

    Fails closed: if the database cannot count the request, ``allow`` raises
    and the request is not served.
    """

    store = "database"

    #: Windows older than this are pruned (seconds).
    RETENTION_SECONDS = 3600
    #: Prune at most once per this many seconds per process.
    PRUNE_INTERVAL_SECONDS = 60

    def __init__(self, db: Any, clock: Callable[[], float] = time.time) -> None:
        self._db = db
        self._clock = clock
        self._last_prune = 0.0

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = self._clock()
        window = max(1, int(window_seconds))
        window_start = int(now // window) * window
        hits = self._db.rate_limit_hit(f"{key}|{window}", window_start)
        if now - self._last_prune >= self.PRUNE_INTERVAL_SECONDS:
            self._last_prune = now
            self._db.prune_rate_limit_windows(int(now) - self.RETENTION_SECONDS)
        return hits <= limit
