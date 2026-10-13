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

import json
from datetime import datetime, timezone
from typing import Any, Sequence

#: Columns of ``remediation_states``.
STATE_COLUMNS: tuple[str, ...] = (
    "subject_id", "subject_kind", "subject_digest", "change_kind", "change_id", "change_version_id",
    "change_store_sequence", "changed_at", "resource_id", "capability", "actor", "actor_holder", "verdict", "state",
    "review_pending", "mode", "steps", "fallback", "grace_seconds", "guidance_source",
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
        self, states: Sequence[str], *, review_pending: bool = False, after: tuple[str, str] | None = None,
        limit: int = 100, open_only: bool = False,
    ) -> list[dict[str, Any]]:
        """States in ``states`` (or, with ``review_pending``, also any state with a pending review),
        oldest first by (created_at, subject_id), after a cursor. ``open_only`` (v1.5.0) leaves out
        a remediated change whose review is still pending: nothing is left to do about it."""
        marks = ", ".join("?" for _ in states)
        match = [f"state IN ({marks})"] if states else []
        if review_pending:
            match.append("(review_pending = 1 AND state <> 'remediated')" if open_only else "review_pending = 1")
        clauses = ["(" + " OR ".join(match) + ")"]
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
        """Rows by state, and (``review_pending``) rows with a pending review, whatever their state."""
        rows = self.conn.execute("SELECT state, COUNT(*) AS n FROM remediation_states GROUP BY state").fetchall()
        out = {r["state"]: int(r["n"]) for r in rows}
        pending = self.conn.execute("SELECT COUNT(*) AS n FROM remediation_states WHERE review_pending = 1").fetchone()
        out["review_pending"] = int(pending["n"])
        return out

    def open_remediation_subjects(self, now: datetime) -> set[str]:
        """Subjects whose remediation is not settled (v1.4.0 review fixes): due, overdue or waived, a
        review pending, or a lifetime still running. Retention keeps their records."""
        rows = self.conn.execute(
            """SELECT subject_id FROM remediation_states
               WHERE state IN ('remediation_due', 'overdue', 'waived') OR review_pending = 1
                  OR (lifetime_ends_at IS NOT NULL AND state <> 'remediated')""",
        ).fetchall()
        return {r["subject_id"] for r in rows}

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

    def remediation_states_due(
        self, column: str, states: Sequence[str], now: datetime, limit: int,
    ) -> list[dict[str, Any]]:
        """Rows in one of ``states`` whose time ``column`` has passed (``remediation_due_at``,
        ``waived_until`` or ``lifetime_ends_at``), oldest first, whether a review is pending or not."""
        if column not in ("remediation_due_at", "waived_until", "lifetime_ends_at"):
            raise ValueError(f"not a time column: {column}")
        marks = ", ".join("?" for _ in states)
        rows = self.conn.execute(
            f"SELECT * FROM remediation_states WHERE state IN ({marks}) AND {column} IS NOT NULL "
            f"AND {column} <= ? ORDER BY {column}, subject_id LIMIT ?",
            (*states, stamp(now), limit),
        ).fetchall()
        return [_dict(r) for r in rows]

    def subjects_without_state(
        self, kind: str, *, recorded_since: datetime, after_sequence: int, limit: int,
    ) -> list[tuple[int, str]]:
        """(store_sequence, id) of judgements (``kind`` ``judgement``) or authorized decisions
        (``decision``) recorded since a time, after a position, that have no remediation state,
        oldest first: the sweep looks at each once per instance and arms those that need one (a
        judgement or decision an older instance made, or one whose arming failed)."""
        if kind == "judgement":
            id_column, extra = "e.record_id", ""
        elif kind == "decision":
            id_column, extra = "e.decision_id", " AND e.outcome = 'authorized'"
        else:
            raise ValueError(f"not a subject kind: {kind}")
        rows = self.conn.execute(
            f"""SELECT e.store_sequence, {id_column} AS subject_id FROM evidence_entries e
                WHERE e.entry_kind = ? AND e.recorded_at >= ? AND e.store_sequence > ?{extra}
                  AND NOT EXISTS (SELECT 1 FROM remediation_states s WHERE s.subject_id = {id_column})
                ORDER BY e.store_sequence LIMIT ?""",
            (kind, recorded_since.isoformat(), after_sequence, limit),
        ).fetchall()
        return [(int(r["store_sequence"]), r["subject_id"]) for r in rows]

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

    def rotation_cited(self, evidence_id: str) -> bool:
        """Whether a stored remediation record already cites this forward rotation (v1.4.0 review fixes)."""
        fragment = json.dumps({"rotation_evidence_id": evidence_id}, separators=(",", ":"))[1:-1]
        escaped = fragment.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        row = self.conn.execute(
            "SELECT 1 FROM evidence_entries WHERE entry_kind = 'remediation' AND payload_json LIKE ? ESCAPE '!' "
            "LIMIT 1",
            (f"%{escaped}%",),
        ).fetchone()
        return row is not None

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
