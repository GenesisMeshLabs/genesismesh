"""Boundary policy persistence (v0.58)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from ..models.boundary_policy import BoundaryPolicy


@dataclass(frozen=True)
class ActiveBoundaryPolicies:
    """The active policy set as loaded from the store.

    ``integrity_failures`` lists ``policy_id@version`` for active rows whose
    stored JSON no longer parses, whose digest does not match, or whose body
    names a different policy/version than the row.  Any entry makes policy
    resolution fail closed.
    """

    policies: list[BoundaryPolicy]
    integrity_failures: list[str]


class BoundaryPolicyStoreMixin:
    """Persistence methods for signed boundary policy versions."""

    conn: Any
    _lock: Any

    def next_boundary_policy_version(self, policy_id: str) -> int:
        """Return the version number the next publish of ``policy_id`` receives."""
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM boundary_policy_versions WHERE policy_id = ?",
            (policy_id,),
        ).fetchone()
        return int(row["v"] or 0) + 1

    def save_boundary_policy(self, policy: BoundaryPolicy) -> None:
        """Insert a new, inactive policy version.  Existing versions are never replaced."""
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO boundary_policy_versions(
                    policy_id, version, policy_json, policy_digest, active, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    policy.policy_id,
                    policy.version,
                    policy.model_dump_json(),
                    policy.digest(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_boundary_policy_row(self, policy_id: str, version: int) -> Optional[dict]:
        """Return one stored version row, or None."""
        row = self.conn.execute(
            "SELECT * FROM boundary_policy_versions WHERE policy_id = ? AND version = ?",
            (policy_id, version),
        ).fetchone()
        return dict(row) if row else None

    def list_boundary_policy_rows(self, policy_id: Optional[str] = None) -> list[dict]:
        """Return stored version rows, newest first; optionally for one policy."""
        if policy_id is None:
            rows = self.conn.execute(
                "SELECT * FROM boundary_policy_versions ORDER BY policy_id, version DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM boundary_policy_versions WHERE policy_id = ? ORDER BY version DESC",
                (policy_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def parse_boundary_policy_row(row: dict) -> Optional[BoundaryPolicy]:
        """Parse a row and check it against its stored digest; None if tampered."""
        try:
            policy = BoundaryPolicy.model_validate_json(row["policy_json"])
        except ValidationError:
            return None
        if (
            policy.policy_id != row["policy_id"]
            or policy.version != row["version"]
            or policy.digest() != row["policy_digest"]
        ):
            return None
        return policy

    def load_active_boundary_policies(self) -> ActiveBoundaryPolicies:
        """Load every active version, reporting rows that fail integrity checks."""
        rows = self.conn.execute(
            "SELECT * FROM boundary_policy_versions WHERE active = 1 ORDER BY policy_id, version"
        ).fetchall()
        policies: list[BoundaryPolicy] = []
        failures: list[str] = []
        for raw in rows:
            row = dict(raw)
            policy = self.parse_boundary_policy_row(row)
            if policy is None:
                failures.append(f"{row['policy_id']}@{row['version']}")
            else:
                policies.append(policy)
        return ActiveBoundaryPolicies(policies=policies, integrity_failures=failures)

    def activate_boundary_policy(self, policy_id: str, version: int) -> Optional[int]:
        """Activate one version, deactivating any other active version of the policy.

        Returns the previously active version (or None).  Raises KeyError for an
        unknown version.  Both changes commit in one transaction.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            if self.get_boundary_policy_row(policy_id, version) is None:
                raise KeyError(f"{policy_id}@{version}")
            prev = self.conn.execute(
                "SELECT version FROM boundary_policy_versions WHERE policy_id = ? AND active = 1",
                (policy_id,),
            ).fetchone()
            previous = int(prev["version"]) if prev else None
            if previous == version:
                return previous
            self.conn.execute(
                "UPDATE boundary_policy_versions SET active = 0, deactivated_at = ? "
                "WHERE policy_id = ? AND active = 1",
                (now, policy_id),
            )
            self.conn.execute(
                "UPDATE boundary_policy_versions SET active = 1, activated_at = ? "
                "WHERE policy_id = ? AND version = ?",
                (now, policy_id, version),
            )
        return previous

    def deactivate_boundary_policy(self, policy_id: str, version: int) -> bool:
        """Deactivate one version.  Returns False if it was not active."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE boundary_policy_versions SET active = 0, deactivated_at = ? "
                "WHERE policy_id = ? AND version = ? AND active = 1",
                (now, policy_id, version),
            )
        return cur.rowcount > 0
