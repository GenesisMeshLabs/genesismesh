"""Evidence store persistence (v0.59).

Append-only by construction: this mixin has no update path for entries, and
database triggers (migration 012) refuse updates and any delete that a
retention checkpoint does not cover.  Positions are protected by unique
indexes, so concurrent writers cannot both take the same store, decision or
resource position.  Appends run inside ``BEGIN IMMEDIATE`` so the next
``store_sequence`` and the previous entry's digest are read and written under
one write lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Sequence

from ..models.evidence_store import EvidenceStoreEntry, RetentionCheckpoint

#: Entry columns that may be used as search filters.
SEARCH_FIELDS: tuple[str, ...] = (
    "vendor_id", "attestation_id", "capability", "resource_id", "outcome",
    "entry_kind", "decision_id", "executor_sovereign_id",
)

_ENTRY_COLUMNS = (
    "store_sequence", "entry_kind", "recorded_at", "entry_json", "entry_digest",
    "prev_entry_digest", "payload_json", "decision_id", "context_id", "vendor_id",
    "attestation_id", "capability", "outcome", "evidence_id", "executor_sovereign_id",
    "exec_sequence_no", "resource_id", "resource_action", "resource_sequence",
)

#: Builds the envelope for one pending payload given (store_sequence, prev_entry_digest).
EntryBuilder = Callable[[int, "str | None"], EvidenceStoreEntry]


class EvidenceStoreMixin:
    """Persistence methods for the NA evidence store."""

    conn: sqlite3.Connection
    _lock: threading.RLock

    @contextmanager
    def _evidence_write(self) -> Iterator[None]:
        """Serialize a store write across threads and processes."""
        with self._lock:
            if self.conn.in_transaction:
                self.conn.commit()
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()

    def _store_head(self) -> tuple[int, str | None]:
        """Return (last store_sequence, its digest), honouring retention checkpoints."""
        row = self.conn.execute(
            "SELECT store_sequence, entry_digest FROM evidence_entries ORDER BY store_sequence DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            return int(row["store_sequence"]), row["entry_digest"]
        cp = self.latest_retention_checkpoint()
        if cp is not None:
            return cp.removed_through_sequence, cp.last_removed_entry_digest
        return 0, None

    def _insert_entry(self, entry: EvidenceStoreEntry, payload: dict[str, Any]) -> None:
        values = {
            "store_sequence": entry.store_sequence,
            "entry_kind": entry.entry_kind,
            "recorded_at": entry.recorded_at.isoformat(),
            "entry_json": entry.model_dump_json(),
            "entry_digest": entry.digest(),
            "prev_entry_digest": entry.prev_entry_digest,
            "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "decision_id": entry.decision_id,
            "context_id": entry.context_id,
            "vendor_id": entry.vendor_id,
            "attestation_id": entry.attestation_id,
            "capability": entry.capability,
            "outcome": entry.outcome,
            "evidence_id": entry.evidence_id,
            "executor_sovereign_id": entry.executor_sovereign_id,
            "exec_sequence_no": entry.exec_sequence_no,
            "resource_id": entry.resource_id,
            "resource_action": entry.resource_action,
            "resource_sequence": entry.resource_sequence,
        }
        cols = ", ".join(_ENTRY_COLUMNS)
        marks = ", ".join("?" for _ in _ENTRY_COLUMNS)
        self.conn.execute(
            f"INSERT INTO evidence_entries({cols}) VALUES ({marks})",
            tuple(values[c] for c in _ENTRY_COLUMNS),
        )

    def append_evidence_entries(
        self, pending: Sequence[tuple[EntryBuilder, dict[str, Any]]]
    ) -> list[EvidenceStoreEntry]:
        """Append entries atomically, each linked to the one before it.

        Raises ``sqlite3.IntegrityError`` when a unique position is already
        taken (the caller maps that to a conflict).
        """
        written: list[EvidenceStoreEntry] = []
        with self._evidence_write():
            seq, prev = self._store_head()
            for build, payload in pending:
                seq += 1
                entry = build(seq, prev)
                self._insert_entry(entry, payload)
                prev = entry.digest()
                written.append(entry)
        return written

    # -- reads --------------------------------------------------------------

    @staticmethod
    def _row_to_stored(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "entry": EvidenceStoreEntry.model_validate_json(row["entry_json"]),
            "entry_digest": row["entry_digest"],
            "payload": json.loads(row["payload_json"]),
        }

    def get_decision_entry(self, decision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = 'decision' AND decision_id = ?",
            (decision_id,),
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def get_entry_by_evidence_id(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def last_execution_for_decision(self, decision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM evidence_entries WHERE entry_kind = 'execution' AND decision_id = ?
               ORDER BY exec_sequence_no DESC LIMIT 1""",
            (decision_id,),
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def last_resource_record(self, resource_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM evidence_entries WHERE resource_id = ?
               ORDER BY resource_sequence DESC LIMIT 1""",
            (resource_id,),
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def search_evidence(
        self, filters: dict[str, str], *, since: str | None = None, until: str | None = None,
        after_sequence: int = 0, limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["store_sequence > ?"]
        params: list[Any] = [after_sequence]
        for key, value in filters.items():
            if key not in SEARCH_FIELDS:
                raise ValueError(f"unsupported filter {key!r}")
            clauses.append(f"{key} = ?")
            params.append(value)
        if since:
            clauses.append("recorded_at >= ?")
            params.append(since)
        if until:
            clauses.append("recorded_at < ?")
            params.append(until)
        rows = self.conn.execute(
            f"SELECT * FROM evidence_entries WHERE {' AND '.join(clauses)} ORDER BY store_sequence LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def entries_for_decisions(self, decision_ids: Sequence[str]) -> list[dict[str, Any]]:
        if not decision_ids:
            return []
        marks = ", ".join("?" for _ in decision_ids)
        rows = self.conn.execute(
            f"SELECT * FROM evidence_entries WHERE decision_id IN ({marks}) ORDER BY store_sequence",
            tuple(decision_ids),
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def evidence_stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, MAX(store_sequence) AS last_seq FROM evidence_entries"
        ).fetchone()
        rejections = self.conn.execute("SELECT COUNT(*) AS n FROM evidence_rejections").fetchone()
        keys = self.conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_executor_keys WHERE retired_at IS NULL"
        ).fetchone()
        return {
            "entries": int(row["n"]),
            "last_store_sequence": row["last_seq"],
            "rejections": int(rejections["n"]),
            "active_executor_keys": int(keys["n"]),
        }

    def retention_candidates(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT e.store_sequence, e.recorded_at, e.decision_id, e.resource_id,
                      e.resource_sequence, e.entry_kind, e.entry_digest, e.payload_json
               FROM evidence_entries e ORDER BY e.store_sequence"""
        ).fetchall()

    def resource_latest_sequences(self) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT resource_id, MAX(resource_sequence) AS seq FROM evidence_entries
               WHERE resource_id IS NOT NULL GROUP BY resource_id"""
        ).fetchall()
        return {r["resource_id"]: int(r["seq"]) for r in rows}

    # -- rejections -----------------------------------------------------------

    def add_evidence_rejection(
        self, code: str, *, submitted_digest: str | None, evidence_id: str | None,
        decision_id: str | None, resource_id: str | None, executor_sovereign_id: str | None,
    ) -> str:
        rejection_id = str(uuid.uuid4())
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO evidence_rejections(rejection_id, rejected_at, code, submitted_digest,
                       evidence_id, decision_id, resource_id, executor_sovereign_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rejection_id, datetime.now(timezone.utc).isoformat(), code, submitted_digest,
                 evidence_id, decision_id, resource_id, executor_sovereign_id),
            )
        return rejection_id

    # -- executor keys --------------------------------------------------------

    def register_executor_key(
        self, key_id: str, public_key: str, executor_sovereign_id: str, registered_by: str
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO evidence_executor_keys(key_id, public_key, executor_sovereign_id,
                       registered_at, registered_by) VALUES (?, ?, ?, ?, ?)""",
                (key_id, public_key, executor_sovereign_id, datetime.now(timezone.utc).isoformat(), registered_by),
            )

    def retire_executor_key(self, key_id: str, retired_by: str) -> bool:
        with self._lock, self.conn:
            cur = self.conn.execute(
                """UPDATE evidence_executor_keys SET retired_at = ?, retired_by = ?
                   WHERE key_id = ? AND retired_at IS NULL""",
                (datetime.now(timezone.utc).isoformat(), retired_by, key_id),
            )
        return cur.rowcount > 0

    def get_executor_key(self, key_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM evidence_executor_keys WHERE key_id = ?", (key_id,)
        ).fetchone()

    def list_executor_keys(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM evidence_executor_keys ORDER BY registered_at, key_id"
        ).fetchall()

    # -- retention ------------------------------------------------------------

    def latest_retention_checkpoint(self) -> RetentionCheckpoint | None:
        row = self.conn.execute(
            """SELECT checkpoint_json FROM evidence_retention_checkpoints
               ORDER BY removed_through_sequence DESC LIMIT 1"""
        ).fetchone()
        return RetentionCheckpoint.model_validate_json(row["checkpoint_json"]) if row else None

    def apply_retention_checkpoint(
        self, checkpoint: RetentionCheckpoint, build_entry: EntryBuilder
    ) -> EvidenceStoreEntry:
        """Record the checkpoint, remove entries it covers, append its entry."""
        payload = json.loads(checkpoint.model_dump_json())
        with self._evidence_write():
            seq, prev = self._store_head()
            self.conn.execute(
                """INSERT INTO evidence_retention_checkpoints(checkpoint_id, removed_through_sequence,
                       checkpoint_json, created_at) VALUES (?, ?, ?, ?)""",
                (checkpoint.checkpoint_id, checkpoint.removed_through_sequence,
                 checkpoint.model_dump_json(), checkpoint.created_at.isoformat()),
            )
            self.conn.execute(
                "DELETE FROM evidence_entries WHERE store_sequence <= ?",
                (checkpoint.removed_through_sequence,),
            )
            entry = build_entry(seq + 1, prev)
            self._insert_entry(entry, payload)
        return entry
