"""Remediation state and reviews (v1.4.0, Stage 3): persistence.

``remediation_states`` holds, per judged change or decision a remediation
or review concerns, what is due and when (operational, unsigned; the signed
judgements, reviews and remediations are in the evidence store).
``remediation_reviews`` holds reviews from their request to their decision.

Writes that change a state run inside the evidence store's write
transaction (``append_evidence_entries_with`` or ``exclusive_transaction``),
so the state and the store entry that moves it land together; an update
names the state it expects, so two instances cannot both make one
transition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

#: Columns of ``remediation_states``.
STATE_COLUMNS: tuple[str, ...] = (
    "subject_id", "subject_kind", "subject_digest", "change_kind", "change_id", "resource_id", "capability",
    "actor", "verdict", "state", "mode", "steps", "fallback", "grace_seconds", "guidance_source",
    "remediation_due_at", "lifetime_ends_at", "waived_until", "review_id", "remediation_id", "notified_at",
    "notified_by", "overdue_since", "created_at", "updated_at",
)

REVIEW_COLUMNS: tuple[str, ...] = (
    "review_id", "subject_id", "opened_for", "requested_by", "requester_holder", "justification",
    "request_approval_json", "requested_at", "decided_at", "verdict",
)


def stamp(value: datetime) -> str:
    """A UTC time as stored here: always six digits of microseconds, so text order is time order."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class RemediationStoreMixin:
    """Persistence methods for remediation state and reviews."""

    conn: Any

    # -- states ---------------------------------------------------------------

    def get_remediation_state(self, subject_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM remediation_states WHERE subject_id = ?", (subject_id,)).fetchone()
        return _dict(row) if row is not None else None

    def insert_remediation_state(self, values: dict[str, Any]) -> None:
        """Insert a state row (inside the caller's write transaction)."""
        unknown = set(values) - set(STATE_COLUMNS)
        if unknown:
            raise ValueError(f"unknown remediation state columns {sorted(unknown)}")
        cols = [c for c in STATE_COLUMNS if c in values]
        self.conn.execute(
            f"INSERT INTO remediation_states({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(values[c] for c in cols),
        )

    def update_remediation_state(self, subject_id: str, expected_state: str, changes: dict[str, Any]) -> bool:
        """Change a state row that is still in ``expected_state`` (inside the caller's write
        transaction). Returns False when another writer moved it first."""
        unknown = set(changes) - set(STATE_COLUMNS)
        if unknown:
            raise ValueError(f"unknown remediation state columns {sorted(unknown)}")
        cols = sorted(changes)
        cur = self.conn.execute(
            f"UPDATE remediation_states SET {', '.join(f'{c} = ?' for c in cols)} "
            "WHERE subject_id = ? AND state = ?",
            (*(changes[c] for c in cols), subject_id, expected_state),
        )
        return cur.rowcount > 0

    def list_remediation_states(
        self, states: Sequence[str], *, after: tuple[str, str] | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """States in ``states``, oldest first by (created_at, subject_id), after a cursor."""
        marks = ", ".join("?" for _ in states)
        clauses = [f"state IN ({marks})"]
        params: list[Any] = list(states)
        if after is not None:
            clauses.append("(created_at > ? OR (created_at = ? AND subject_id > ?))")
            params.extend([after[0], after[0], after[1]])
        rows = self.conn.execute(
            f"SELECT * FROM remediation_states WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at, subject_id LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_dict(r) for r in rows]

    def count_remediation_states(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) AS n FROM remediation_states GROUP BY state").fetchall()
        return {r["state"]: int(r["n"]) for r in rows}

    def remediation_states_for(self, subject_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not subject_ids:
            return {}
        out: dict[str, dict[str, Any]] = {}
        ids = list(subject_ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = self.conn.execute(
                f"SELECT * FROM remediation_states WHERE subject_id IN ({', '.join('?' for _ in chunk)})",
                tuple(chunk),
            ).fetchall()
            out.update({r["subject_id"]: _dict(r) for r in rows})
        return out

    def remediation_states_due(self, column: str, state: str, now: datetime, limit: int) -> list[dict[str, Any]]:
        """Rows in ``state`` whose time ``column`` has passed (``remediation_due_at``,
        ``waived_until`` or ``lifetime_ends_at``), oldest first."""
        if column not in ("remediation_due_at", "waived_until", "lifetime_ends_at"):
            raise ValueError(f"not a time column: {column}")
        rows = self.conn.execute(
            f"SELECT * FROM remediation_states WHERE state = ? AND {column} IS NOT NULL AND {column} <= ? "
            f"ORDER BY {column}, subject_id LIMIT ?",
            (state, stamp(now), limit),
        ).fetchall()
        return [_dict(r) for r in rows]

    def judgements_needing_state(self, limit: int, recorded_since: datetime | None = None) -> list[str]:
        """Judgement IDs that may need a remediation state and have none (denied, indeterminate
        or flagged), recorded since a time, oldest first: those whose arming failed are armed
        again at start."""
        rows = self.conn.execute(
            """SELECT e.record_id FROM evidence_entries e
               WHERE e.entry_kind = 'judgement' AND e.recorded_at >= ?
                 AND (e.outcome IN ('deny', 'indeterminate') OR e.payload_json LIKE '%"flagged_for_review":true%')
                 AND NOT EXISTS (SELECT 1 FROM remediation_states s WHERE s.subject_id = e.record_id)
               ORDER BY e.store_sequence LIMIT ?""",
            ((recorded_since or datetime.min.replace(tzinfo=timezone.utc)).isoformat(), limit),
        ).fetchall()
        return [r["record_id"] for r in rows]

    # -- reviews --------------------------------------------------------------

    def insert_remediation_review(self, values: dict[str, Any]) -> None:
        """Insert a review request (inside the caller's write transaction)."""
        unknown = set(values) - set(REVIEW_COLUMNS)
        if unknown:
            raise ValueError(f"unknown review columns {sorted(unknown)}")
        cols = [c for c in REVIEW_COLUMNS if c in values]
        self.conn.execute(
            f"INSERT INTO remediation_reviews({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(values[c] for c in cols),
        )

    def get_remediation_review(self, review_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM remediation_reviews WHERE review_id = ?", (review_id,)).fetchone()
        return _dict(row) if row is not None else None

    def open_remediation_review(self, subject_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM remediation_reviews WHERE subject_id = ? AND decided_at IS NULL", (subject_id,)
        ).fetchone()
        return _dict(row) if row is not None else None

    def mark_remediation_review_decided(self, review_id: str, verdict: str, decided_at: datetime) -> bool:
        """Mark a review decided (inside the caller's write transaction); False when it already was."""
        cur = self.conn.execute(
            "UPDATE remediation_reviews SET decided_at = ?, verdict = ? WHERE review_id = ? AND decided_at IS NULL",
            (stamp(decided_at), verdict, review_id),
        )
        return cur.rowcount > 0

    def remediation_reviews_for(self, subject_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM remediation_reviews WHERE subject_id = ? ORDER BY requested_at, review_id", (subject_id,)
        ).fetchall()
        return [_dict(r) for r in rows]

    def remediation_entries_for(self, subject_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Stored remediation and review entries of these subjects, in store order."""
        if not subject_ids:
            return []
        ids = list(subject_ids)
        out: list[dict[str, Any]] = []
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = self.conn.execute(
                f"""SELECT * FROM evidence_entries WHERE entry_kind IN ('remediation', 'review')
                    AND subject_id IN ({', '.join('?' for _ in chunk)}) ORDER BY store_sequence""",
                tuple(chunk),
            ).fetchall()
            out.extend(self._row_to_stored(r) for r in rows)  # type: ignore[attr-defined]
        return sorted(out, key=lambda s: s["entry"].store_sequence)
