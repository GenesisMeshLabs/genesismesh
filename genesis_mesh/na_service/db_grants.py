"""Pre-issued grants (v1.6.0, Stage 5): persistence.

``capability_grants`` holds every grant the NA issued (the signed grant is
also a store entry, kind ``grant``) with its operational state: how many uses
the store admitted, the head of its use chain, the time token the last use
cited, and its revocation. ``capability_grant_policies`` holds the policy
versions each grant is bound to, so a deactivation finds its grants.

Writes that move a grant's state run inside the evidence store's write
transaction (``append_evidence_entries_with``), so the counters and the store
entry that moves them land together; an update names the count it expects,
so two instances cannot both admit the same use. Migration 018 refuses any
other change to a stored grant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from .db_remediation import stamp

#: Columns of ``capability_grants`` a new grant sets.
GRANT_COLUMNS: tuple[str, ...] = (
    "grant_id", "grant_json", "grant_digest", "bearer_key_id", "bearer_sovereign_id", "basis_kind", "basis_id",
    "valid_from", "valid_until", "issued_at", "issued_by_operator", "store_sequence",
)


def _dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class GrantStoreMixin:
    """Persistence methods for grants."""

    conn: Any

    def insert_grant(self, values: dict[str, Any], policies: Sequence[tuple[str, int]]) -> None:
        """Insert a grant and its policy binding (inside the caller's write transaction)."""
        unknown = set(values) - set(GRANT_COLUMNS)
        if unknown:
            raise ValueError(f"unknown grant columns {sorted(unknown)}")
        cols = [c for c in GRANT_COLUMNS if c in values]
        self.conn.execute(
            f"INSERT INTO capability_grants({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(values[c] for c in cols),
        )
        for policy_id, version in sorted(set(policies)):
            self.conn.execute(
                "INSERT INTO capability_grant_policies(grant_id, policy_id, policy_version) VALUES (?, ?, ?)",
                (values["grant_id"], policy_id, version),
            )

    def get_grant_row(self, grant_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM capability_grants WHERE grant_id = ?", (grant_id,)).fetchone()
        return _dict(row) if row is not None else None

    def list_grant_rows(
        self, *, status: str | None = None, bearer_key_id: str | None = None, now: datetime | None = None,
        after_issued_at: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Grants, newest first. ``status``: ``active`` (not revoked, not expired at ``now``), ``expired``
        (not revoked, past its end) or ``revoked``."""
        clauses: list[str] = []
        params: list[Any] = []
        if bearer_key_id is not None:
            clauses.append("bearer_key_id = ?")
            params.append(bearer_key_id)
        if status == "revoked":
            clauses.append("revoked_at IS NOT NULL")
        elif status in ("active", "expired"):
            assert now is not None
            clauses.append("revoked_at IS NULL")
            clauses.append("valid_until >= ?" if status == "active" else "valid_until < ?")
            params.append(stamp(now))
        if after_issued_at is not None:
            clauses.append("issued_at < ?")
            params.append(after_issued_at)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM capability_grants {where} ORDER BY issued_at DESC, grant_id LIMIT ?", (*params, limit),
        ).fetchall()
        return [_dict(r) for r in rows]

    def usable_grant_rows(self, now: datetime) -> list[dict[str, Any]]:
        """Grants not revoked and not past their end: what a policy change or a key retirement re-checks."""
        rows = self.conn.execute(
            "SELECT * FROM capability_grants WHERE revoked_at IS NULL AND valid_until >= ? ORDER BY issued_at, grant_id",
            (stamp(now),),
        ).fetchall()
        return [_dict(r) for r in rows]

    def grants_bound_to(self, policy_id: str, version: int, now: datetime) -> list[dict[str, Any]]:
        """Usable grants bound to one policy version."""
        rows = self.conn.execute(
            """SELECT g.* FROM capability_grants g JOIN capability_grant_policies p ON p.grant_id = g.grant_id
               WHERE p.policy_id = ? AND p.policy_version = ? AND g.revoked_at IS NULL AND g.valid_until >= ?
               ORDER BY g.issued_at, g.grant_id""",
            (policy_id, version, stamp(now)),
        ).fetchall()
        return [_dict(r) for r in rows]

    def grant_policy_versions(self, grant_id: str) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT policy_id, policy_version FROM capability_grant_policies WHERE grant_id = ? "
            "ORDER BY policy_id, policy_version", (grant_id,),
        ).fetchall()
        return [(r["policy_id"], int(r["policy_version"])) for r in rows]

    def advance_grant_use(self, grant_id: str, expected_uses: int, changes: dict[str, Any]) -> bool:
        """Record an admitted use (inside the caller's write transaction): the counters move only from
        ``expected_uses``. Returns False when another writer admitted a use first."""
        allowed = {"uses", "last_use_digest", "last_use_executed_at", "last_token_id", "last_token_issued_at",
                   "last_token_uses"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown grant columns {sorted(unknown)}")
        cols = sorted(changes)
        cur = self.conn.execute(
            f"UPDATE capability_grants SET {', '.join(f'{c} = ?' for c in cols)} WHERE grant_id = ? AND uses = ?",
            (*(changes[c] for c in cols), grant_id, expected_uses),
        )
        return cur.rowcount > 0

    def mark_grant_revoked(self, grant_id: str, revoked_at: datetime, reason: str, revocation_id: str) -> bool:
        """Mark a grant revoked (inside the caller's write transaction). False when it already was."""
        cur = self.conn.execute(
            """UPDATE capability_grants SET revoked_at = ?, revocation_reason = ?, revocation_id = ?
               WHERE grant_id = ? AND revoked_at IS NULL""",
            (stamp(revoked_at), reason, revocation_id, grant_id),
        )
        return cur.rowcount > 0

    def grant_use_entry(self, grant_id: str, use_sequence: int) -> dict[str, Any] | None:
        """The stored use of a grant at a position of its chain, or None."""
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = 'grant_execution' AND subject_id = ? "
            "AND exec_sequence_no = ?", (grant_id, use_sequence),
        ).fetchone()
        return self._row_to_stored(row) if row is not None else None  # type: ignore[attr-defined]

    def grant_revocation_entry(self, grant_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = 'grant_revocation' AND subject_id = ?", (grant_id,),
        ).fetchone()
        return self._row_to_stored(row) if row is not None else None  # type: ignore[attr-defined]

    def grant_counts(self, now: datetime) -> dict[str, int]:
        """Grants by state, for ``/admin/evidence/status``."""
        row = self.conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN revoked_at IS NOT NULL THEN 1 ELSE 0 END) AS revoked,
                      SUM(CASE WHEN revoked_at IS NULL AND valid_until >= ? THEN 1 ELSE 0 END) AS active,
                      COALESCE(SUM(uses), 0) AS uses
               FROM capability_grants""",
            (stamp(now),),
        ).fetchone()
        return {"grants_issued": int(row["total"] or 0), "grants_active": int(row["active"] or 0),
                "grants_revoked": int(row["revoked"] or 0), "grant_uses": int(row["uses"] or 0)}

    def grant_revocation_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM capability_grants WHERE revoked_at IS NOT NULL").fetchone()
        return int(row["n"] or 0)

    def revoked_grant_ids(self, now: datetime) -> list[str]:
        """Grants revoked and not yet past their end: what a holder must stop using (the revocation feed)."""
        rows = self.conn.execute(
            "SELECT grant_id FROM capability_grants WHERE revoked_at IS NOT NULL AND valid_until >= ? "
            "ORDER BY grant_id", (stamp(now),),
        ).fetchall()
        return [r["grant_id"] for r in rows]
