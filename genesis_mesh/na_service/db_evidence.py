"""Evidence store persistence (v0.59).

Append-only by construction: this mixin has no update path for entries, and
database triggers (migration 012) refuse updates and any delete that a
retention checkpoint does not cover.  Positions are protected by unique
indexes, so concurrent writers cannot both take the same store, decision or
resource position.  Appends run inside an exclusive transaction (SQLite
``BEGIN IMMEDIATE``; a PostgreSQL advisory lock) so the next ``store_sequence``
and the previous entry's digest are read and written under one write lock,
across every NA instance.
"""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Sequence

from ..models.evidence_store import EvidenceStoreEntry, RetentionCheckpoint, StoreAnchor

#: Entry columns that may be used as search filters.
SEARCH_FIELDS: tuple[str, ...] = (
    "vendor_id", "attestation_id", "capability", "resource_id", "outcome",
    "entry_kind", "decision_id", "executor_sovereign_id",
    # v1.3.0
    "record_id", "subject_id",
)

_ENTRY_COLUMNS = (
    "store_sequence", "entry_kind", "recorded_at", "entry_json", "entry_digest",
    "prev_entry_digest", "payload_json", "decision_id", "context_id", "vendor_id",
    "attestation_id", "capability", "outcome", "evidence_id", "executor_sovereign_id",
    "exec_sequence_no", "resource_id", "resource_action", "resource_sequence",
    # v1.3.0: envelope fields, then lookup columns outside the envelope.
    "record_id", "subject_id", "matched_evidence_id", "observation_sequence",
    "dedupe_key", "version_id",
)

#: Lookup columns (v1.3.0) a pending entry may set besides its envelope.
LOOKUP_COLUMNS: tuple[str, ...] = ("dedupe_key", "version_id")

#: Builds the envelope for one pending payload given (store_sequence, prev_entry_digest).
EntryBuilder = Callable[[int, "str | None"], EvidenceStoreEntry]

#: A pending append: (builder, payload) or (builder, payload, lookup columns).
PendingEntry = "tuple[EntryBuilder, dict[str, Any]] | tuple[EntryBuilder, dict[str, Any], dict[str, Any]]"

#: Builds the next anchor from (latest anchor, head store_sequence, head entry digest), or None.
AnchorBuilder = Callable[["StoreAnchor | None", int, "str | None"], "StoreAnchor | None"]


class EvidenceStoreMixin:
    """Persistence methods for the NA evidence store."""

    conn: Any
    _lock: threading.RLock

    @contextmanager
    def _evidence_write(self) -> Iterator[None]:
        """Serialize a store write across threads, processes and NA instances."""
        with self.exclusive_transaction():  # type: ignore[attr-defined]
            yield

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

    def _insert_entry(
        self, entry: EvidenceStoreEntry, payload: dict[str, Any], lookup: dict[str, Any] | None = None
    ) -> None:
        unknown = set(lookup or {}) - set(LOOKUP_COLUMNS)
        if unknown:
            raise ValueError(f"unknown lookup columns {sorted(unknown)}")
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
            "record_id": entry.record_id,
            "subject_id": entry.subject_id,
            "matched_evidence_id": entry.matched_evidence_id,
            "observation_sequence": entry.observation_sequence,
            "dedupe_key": (lookup or {}).get("dedupe_key"),
            "version_id": (lookup or {}).get("version_id"),
        }
        cols = ", ".join(_ENTRY_COLUMNS)
        marks = ", ".join("?" for _ in _ENTRY_COLUMNS)
        self.conn.execute(
            f"INSERT INTO evidence_entries({cols}) VALUES ({marks})",
            tuple(values[c] for c in _ENTRY_COLUMNS),
        )

    def append_evidence_entries(self, pending: Sequence[Any]) -> list[EvidenceStoreEntry]:
        """Append entries atomically, each linked to the one before it.

        Each pending item is ``(builder, payload)`` or, since v1.3.0,
        ``(builder, payload, lookup)`` with lookup columns outside the
        envelope (``LOOKUP_COLUMNS``). Raises the backend's integrity error
        (``db.integrity_errors``) when a unique position is already taken (the
        caller maps that to a conflict).
        """
        written: list[EvidenceStoreEntry] = []
        with self._evidence_write():
            seq, prev = self._store_head()
            for item in pending:
                build, payload = item[0], item[1]
                lookup = item[2] if len(item) > 2 else None
                seq += 1
                entry = build(seq, prev)
                self._insert_entry(entry, payload, lookup)
                prev = entry.digest()
                written.append(entry)
        return written

    def append_evidence_entries_with(
        self, make: Callable[["EvidenceStoreMixin"], Sequence[Any]]
    ) -> list[EvidenceStoreEntry]:
        """Build pending entries from state read inside the write lock, then append them (v1.3.0).

        ``make(db)`` runs under the same exclusive transaction as the append,
        so what it reads (the next observation position, whether a record is
        already judged or matched) cannot change before the entries land.
        """
        written: list[EvidenceStoreEntry] = []
        with self._evidence_write():
            pending = make(self)
            seq, prev = self._store_head()
            for item in pending:
                build, payload = item[0], item[1]
                lookup = item[2] if len(item) > 2 else None
                seq += 1
                entry = build(seq, prev)
                self._insert_entry(entry, payload, lookup)
                prev = entry.digest()
                written.append(entry)
        return written

    # -- reads --------------------------------------------------------------

    @staticmethod
    def _row_to_stored(row: Any) -> dict[str, Any]:
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
        """The resource's latest execution record (v1.3.0: observations name a resource without taking a position)."""
        row = self.conn.execute(
            """SELECT * FROM evidence_entries WHERE resource_id = ? AND entry_kind = 'execution'
               ORDER BY resource_sequence DESC LIMIT 1""",
            (resource_id,),
        ).fetchone()
        return self._row_to_stored(row) if row else None

    # -- v1.3.0: observations, judgements, quarantine, registry ---------------

    def get_entry_by_record(self, entry_kind: str, record_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = ? AND record_id = ?", (entry_kind, record_id)
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def get_entry_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def get_judgement_for(self, subject_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = 'judgement' AND subject_id = ?", (subject_id,)
        ).fetchone()
        return self._row_to_stored(row) if row else None

    def last_observation_sequence(self, resource_id: str) -> int:
        """The resource's latest observation position, honouring retention (0 when none)."""
        row = self.conn.execute(
            "SELECT MAX(observation_sequence) AS seq FROM evidence_entries WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
        if row is not None and row["seq"] is not None:
            return int(row["seq"])
        cp = self.latest_retention_checkpoint()
        return int((cp.observation_heads or {}).get(resource_id, 0)) if cp is not None else 0

    def unmatched_executions(
        self, resource_id: str, resource_action: str, version_id: str | None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Execution and break-glass records of a resource and action no judgement has matched.

        With ``version_id``, only records naming that version, oldest first (the
        match); without it, the most recent records (candidates for a hint).
        """
        version_clause = "AND e.version_id = ?" if version_id is not None else ""
        params: list[Any] = [resource_id, resource_action]
        if version_id is not None:
            params.append(version_id)
        order = "ASC" if version_id is not None else "DESC"
        # Execution evidence is identified by evidence_id, a break-glass record by record_id.
        rows = self.conn.execute(
            f"""SELECT e.* FROM evidence_entries e
                WHERE e.entry_kind IN ('execution', 'break_glass') AND e.resource_id = ?
                  AND e.resource_action = ? {version_clause}
                  AND NOT EXISTS (SELECT 1 FROM evidence_entries j
                                  WHERE j.matched_evidence_id = COALESCE(e.evidence_id, e.record_id))
                ORDER BY e.store_sequence {order} LIMIT ?""",
            (*params, limit),
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def registry_entries(self) -> list[dict[str, Any]]:
        """Every registry record in store order."""
        rows = self.conn.execute(
            "SELECT * FROM evidence_entries WHERE entry_kind = 'registry' ORDER BY store_sequence"
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def resource_changes(self, resource_id: str, limit: int) -> list[dict[str, Any]]:
        """A resource's execution records, observations, break-glass records, judgements and quarantine entries."""
        rows = self.conn.execute(
            """SELECT * FROM evidence_entries WHERE resource_id = ?
               AND entry_kind IN ('execution', 'observation', 'break_glass', 'judgement', 'quarantine')
               ORDER BY store_sequence LIMIT ?""",
            (resource_id, limit),
        ).fetchall()
        return [self._row_to_stored(r) for r in rows]

    # -- operator key holders (v1.3.0) ------------------------------------------

    def add_holder_proposal(self, proposal_id: str, key_id: str, holder: str, proposed_by: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO operator_holder_proposals(proposal_id, key_id, holder, proposed_by, proposed_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (proposal_id, key_id, holder, proposed_by, datetime.now(timezone.utc).isoformat()),
            )

    def get_holder_proposal(self, proposal_id: str) -> Any | None:
        return self.conn.execute(
            "SELECT * FROM operator_holder_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()

    def approve_holder_proposal(self, proposal_id: str, approved_by: str, registry_record_id: str) -> bool:
        with self._lock, self.conn:
            cur = self.conn.execute(
                """UPDATE operator_holder_proposals SET approved_by = ?, approved_at = ?, registry_record_id = ?
                   WHERE proposal_id = ? AND approved_by IS NULL""",
                (approved_by, datetime.now(timezone.utc).isoformat(), registry_record_id, proposal_id),
            )
        return cur.rowcount > 0

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

    def retention_candidates(self) -> list[Any]:
        return self.conn.execute(
            """SELECT e.store_sequence, e.recorded_at, e.decision_id, e.resource_id,
                      e.resource_sequence, e.entry_kind, e.entry_digest, e.payload_json,
                      e.record_id, e.subject_id, e.observation_sequence, e.dedupe_key
               FROM evidence_entries e ORDER BY e.store_sequence"""
        ).fetchall()

    def resource_latest_sequences(self) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT resource_id, MAX(resource_sequence) AS seq FROM evidence_entries
               WHERE resource_id IS NOT NULL AND entry_kind = 'execution' GROUP BY resource_id"""
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
        self, key_id: str, public_key: str, executor_sovereign_id: str, registered_by: str,
        role: str = "executor", resource_prefix: str | None = None,
    ) -> str:
        """Register a key; returns its registration time (ISO 8601)."""
        registered_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO evidence_executor_keys(key_id, public_key, executor_sovereign_id,
                       registered_at, registered_by, key_role, resource_prefix) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (key_id, public_key, executor_sovereign_id, registered_at, registered_by, role, resource_prefix),
            )
        return registered_at

    def retire_executor_key(self, key_id: str, retired_by: str) -> bool:
        with self._lock, self.conn:
            cur = self.conn.execute(
                """UPDATE evidence_executor_keys SET retired_at = ?, retired_by = ?
                   WHERE key_id = ? AND retired_at IS NULL""",
                (datetime.now(timezone.utc).isoformat(), retired_by, key_id),
            )
        return cur.rowcount > 0

    def get_executor_key(self, key_id: str) -> Any | None:
        return self.conn.execute(
            "SELECT * FROM evidence_executor_keys WHERE key_id = ?", (key_id,)
        ).fetchone()

    def list_executor_keys(self) -> list[Any]:
        return self.conn.execute(
            "SELECT * FROM evidence_executor_keys ORDER BY registered_at, key_id"
        ).fetchall()

    # -- anchors (v1.2.0) --------------------------------------------------------

    def store_head(self) -> tuple[int, str | None]:
        """(last store_sequence, its entry digest); (0, None) for an empty store."""
        return self._store_head()

    def latest_store_anchor(self) -> StoreAnchor | None:
        row = self.conn.execute(
            "SELECT anchor_json FROM evidence_anchors ORDER BY anchor_sequence DESC LIMIT 1"
        ).fetchone()
        return StoreAnchor.model_validate_json(row["anchor_json"]) if row else None

    def append_store_anchor(self, make: AnchorBuilder) -> tuple[StoreAnchor | None, bool]:
        """Anchor the store's head inside the evidence write transaction.

        ``make(latest_anchor, head_sequence, head_digest)`` checks the store
        and returns the signed anchor to append, or None when there is nothing
        new to anchor. Holding the write lock means the head cannot move, an
        uncommitted append cannot be anchored, and instances anchor one at a
        time. Returns (anchor, created).
        """
        with self._evidence_write():
            latest = self.latest_store_anchor()
            seq, digest = self._store_head()
            anchor = make(latest, seq, digest)
            if anchor is None:
                return latest, False
            self.conn.execute(
                """INSERT INTO evidence_anchors(anchor_sequence, store_sequence, anchored_at,
                       anchor_digest, anchor_json) VALUES (?, ?, ?, ?, ?)""",
                (anchor.anchor_sequence, anchor.store_sequence, anchor.anchored_at.isoformat(),
                 anchor.digest(), json.dumps(anchor.to_wire(), sort_keys=True, separators=(",", ":"))),
            )
        return anchor, True

    def list_store_anchors(self, *, after_anchor: int = 0, limit: int = 100) -> list[StoreAnchor]:
        rows = self.conn.execute(
            """SELECT anchor_json FROM evidence_anchors WHERE anchor_sequence > ?
               ORDER BY anchor_sequence LIMIT ?""",
            (after_anchor, limit),
        ).fetchall()
        return [StoreAnchor.model_validate_json(r["anchor_json"]) for r in rows]

    def entry_digest_at(self, store_sequence: int) -> str | None:
        """The stored entry digest at a position; None once retention removed it."""
        row = self.conn.execute(
            "SELECT entry_digest FROM evidence_entries WHERE store_sequence = ?", (store_sequence,)
        ).fetchone()
        return row["entry_digest"] if row else None

    # -- retention ------------------------------------------------------------

    def latest_retention_checkpoint(self) -> RetentionCheckpoint | None:
        row = self.conn.execute(
            """SELECT checkpoint_json FROM evidence_retention_checkpoints
               ORDER BY removed_through_sequence DESC LIMIT 1"""
        ).fetchone()
        return RetentionCheckpoint.model_validate_json(row["checkpoint_json"]) if row else None

    def apply_retention_checkpoint(
        self, checkpoint: RetentionCheckpoint, build_entry: EntryBuilder, carried: Sequence[Any] = (),
    ) -> EvidenceStoreEntry:
        """Record the checkpoint, remove entries it covers, append its entry.

        ``carried`` (v1.3.0): pending entries appended after the checkpoint in
        the same transaction (registry records the removal would lose).
        """
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
            prev_digest, next_seq = entry.digest(), seq + 2
            for item in carried:
                build, carried_payload = item[0], item[1]
                carried_entry = build(next_seq, prev_digest)
                self._insert_entry(carried_entry, carried_payload, item[2] if len(item) > 2 else None)
                prev_digest, next_seq = carried_entry.digest(), next_seq + 1
        return entry
