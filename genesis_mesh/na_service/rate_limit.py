"""Rate limiting helpers for the Network Authority API.

Two stores share one interface, ``allow(key, limit, window_seconds)``, plus
``exceeded(key, limit, window_seconds)``, which reads a bucket without
counting a request in it (v1.1.0):

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

#: Every NA rate limit counts per minute (v1.1.0: named, for ``Retry-After``).
RATE_LIMIT_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateLimits:
    """Requests per minute per client address, by route class (v0.63.1).

    A deployment whose clients share one address (a corporate proxy or NAT)
    or that runs busy controllers raises them; see
    docs/reference/configuration.md. Enrollment limits (``/join``) are
    anti-abuse controls and stay fixed.

    v1.1.0: ``admin`` rose from 30 to 300, because every governed action is
    one admin call. ``admin_auth_failures`` keeps unauthenticated traffic
    where ``admin`` held it before: once an address has that many failed
    admin authentications in a minute, its admin requests are refused before
    their signatures are checked.
    """

    admin: int = 300
    verify: int = 60
    evidence: int = 120
    read: int = 120
    admin_auth_failures: int = 30
    #: v1.3.0: observations and break-glass records, a bucket of their own so
    #: an observer's backlog does not crowd out controllers' evidence.
    observations: int = 120

    def __post_init__(self) -> None:
        for name in ("admin", "verify", "evidence", "read", "admin_auth_failures", "observations"):
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

    def exceeded(self, key: str, limit: int, window_seconds: float) -> bool:
        """Return whether the next ``allow`` would be refused, without counting a request."""
        now = time.time()
        events = self._events.get(key)
        if not events:
            return False
        while events and now - events[0] > window_seconds:
            events.popleft()
        if not events:
            # Forget an address whose window has passed (v1.1.0: the failure
            # buckets add a key per address).
            del self._events[key]
            return False
        return len(events) >= limit


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

    def exceeded(self, key: str, limit: int, window_seconds: float) -> bool:
        """Return whether the next ``allow`` would be refused, without counting a request."""
        window = max(1, int(window_seconds))
        window_start = int(self._clock() // window) * window
        return self._db.rate_limit_hits(f"{key}|{window}", window_start) >= limit
