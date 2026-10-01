"""Shared runtime state (v0.60): rate-limit windows and single-runner job leases.

Both live in the database so they hold across gunicorn workers and across NA
instances. Every operation is one atomic statement; correctness never relies
on a read followed by a write.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class RuntimeStoreMixin:
    """Persistence for shared rate limiting and job leases."""

    conn: Any
    _lock: Any

    def rate_limit_hit(self, bucket: str, window_start: int) -> int:
        """Count one request in a fixed window and return the window's total."""
        with self._lock, self.conn:
            row = self.conn.execute(
                """
                INSERT INTO rate_limit_windows(bucket, window_start, hits)
                VALUES (?, ?, 1)
                ON CONFLICT(bucket, window_start)
                DO UPDATE SET hits = rate_limit_windows.hits + 1
                RETURNING hits
                """,
                (bucket, window_start),
            ).fetchone()
        return int(row[0])

    def prune_rate_limit_windows(self, older_than: int) -> int:
        """Delete windows that started before ``older_than`` (epoch seconds)."""
        with self._lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM rate_limit_windows WHERE window_start < ?", (older_than,)
            )
        return int(cur.rowcount or 0)

    def claim_lease(self, name: str, holder: str, ttl_seconds: int, now: datetime | None = None) -> bool:
        """Take or renew the lease ``name`` for ``holder``; False if another holder has it."""
        now = now or datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock, self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO job_leases(name, holder, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    holder = excluded.holder,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE job_leases.expires_at < ? OR job_leases.holder = excluded.holder
                """,
                (name, holder, now.isoformat(), expires, now.isoformat()),
            )
        return int(cur.rowcount or 0) == 1

    def release_lease(self, name: str, holder: str) -> None:
        """Release a lease held by ``holder`` (no-op otherwise)."""
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM job_leases WHERE name = ? AND holder = ?", (name, holder))

    def get_lease(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT name, holder, acquired_at, expires_at FROM job_leases WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None
