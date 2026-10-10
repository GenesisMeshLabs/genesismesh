"""Evidence store application logic for the NA (v0.59).

Routes in ``routes/evidence_store.py`` parse HTTP and call this service.  The
service loads stored state, runs the pure checks in ``trust/evidence_store.py``
and appends entries.  Invariants that must hold under concurrency (positions,
append-only) are enforced by the database (migration 012); this service maps
their violations to stable error codes.

The store is opt-in (``evidence_store="on"``).  When off, nothing is stored
and the evidence routes answer ``404 evidence_store_disabled``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal, NoReturn

import nacl.encoding
from pydantic import ValidationError as PydanticValidationError

from ...models.context import BoundaryDecision, ContextRecord
from ...models.evidence_store import (
    EvidenceEvent,
    EvidenceStoreEntry,
    ResourceHead,
    RetentionCheckpoint,
    StoreAnchor,
    canonical_json,
    payload_digest,
)
from ...models.execution import RESOURCE_CHAIN_FIELDS, ExecutionEvidence
from ...models.justification import JustificationProof
from ...trust.evidence_store import (
    EvidenceVerification,
    ExecutorKey,
    ResourceHeadState,
    RetentionCandidate,
    build_entry,
    check_events_against_anchors,
    decision_index,
    execution_index,
    plan_retention,
    sign_retention_checkpoint,
    sign_store_anchor,
    validate_execution,
    verify_retention_checkpoint,
    verify_evidence_events,
    verify_store_anchors,
)
from ..errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

EvidenceStoreMode = Literal["off", "on"]
EVIDENCE_STORE_MODES: tuple[str, ...] = ("off", "on")

#: Largest page returned by search and export.
MAX_PAGE = 1000
# Records in one resource or vendor history response; longer histories report
# ``truncated`` and are read through the paged export.
HISTORY_LIMIT = MAX_PAGE * 10


def _event(stored: dict[str, Any]) -> EvidenceEvent:
    return EvidenceEvent(entry=stored["entry"], entry_digest=stored["entry_digest"], payload=stored["payload"])


def _serialized_form(evidence: ExecutionEvidence) -> dict[str, Any]:
    """The payload form an execution record is admitted in (v1.1.1).

    The model's JSON serialization, with the optional resource-chain fields
    omitted when absent, exactly as the signed canonical form treats them.
    """
    data = evidence.model_dump(mode="json")
    for field in RESOURCE_CHAIN_FIELDS:
        if data.get(field) is None:
            data.pop(field, None)
    return data


def _serialized_form_difference(raw: dict[str, Any], evidence: ExecutionEvidence) -> str | None:
    """Name the first difference between a submitted payload and its exact form."""
    # Timestamps must be UTC: a naive or offset time serializes unchanged, so
    # the comparison below would admit it, and it cannot be ordered against
    # the NA's own times.
    for name in type(evidence).model_fields:
        value = getattr(evidence, name)
        if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
            return f"field {name!r} is not a UTC timestamp"
    expected = _serialized_form(evidence)
    # The optional resource-chain fields may be sent as null or left out: the
    # signed form omits them either way, so a null carries nothing unsigned.
    raw = {k: v for k, v in raw.items() if not (k in RESOURCE_CHAIN_FIELDS and v is None)}
    if canonical_json(raw) == canonical_json(expected):
        return None
    extra = sorted(set(raw) - set(expected))
    if extra:
        return "unexpected field " + ", ".join(repr(k) for k in extra)
    missing = sorted(set(expected) - set(raw))
    if missing:
        return "missing field " + ", ".join(repr(k) for k in missing)
    for key in sorted(expected):
        if canonical_json(raw[key]) != canonical_json(expected[key]):
            return f"field {key!r} is not in its serialized form"
    return "payload differs from its serialized form"


class _AnchorRefused(Exception):
    """The store cannot be anchored; raised inside the write transaction."""


class EvidenceStoreService:
    """NA application logic for the append-only evidence store."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service
        # Monotonic time before which no automatic anchor is due (per process).
        self._next_anchor_check = 0.0

    # -- configuration ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._na.evidence_store == "on"

    def require_enabled(self) -> None:
        if not self.enabled:
            raise NotFoundError("The evidence store is not enabled", code="evidence_store_disabled")

    def na_public_keys(self) -> list[str]:
        return [self._na.signer.public_key_b64]

    @staticmethod
    def key_from_row(row: Any) -> ExecutorKey:
        """A registered key from its row, with its role and resource prefix (v1.3.0)."""
        names = set(row.keys())
        return ExecutorKey(
            key_id=row["key_id"],
            public_key=row["public_key"],
            executor_sovereign_id=row["executor_sovereign_id"],
            retired=row["retired_at"] is not None,
            role=row["key_role"] if "key_role" in names and row["key_role"] else "executor",
            resource_prefix=row["resource_prefix"] if "resource_prefix" in names else None,
        )

    def executor_keys(self) -> dict[str, ExecutorKey]:
        return {row["key_id"]: self.key_from_row(row) for row in self._na.db.list_executor_keys()}

    # -- decisions ------------------------------------------------------------

    def record_decision(
        self,
        decision: BoundaryDecision,
        context: ContextRecord,
        proof: JustificationProof | None = None,
    ) -> None:
        """Store a signed decision (and proof) when the store is on.

        A storage failure fails the request: the NA never returns a decision
        the store does not hold.
        """
        if not self.enabled:
            return
        now = datetime.now(timezone.utc)
        index = decision_index(decision, context)
        decision_payload = {
            "decision": decision.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
        }
        pending: list[tuple[Any, dict[str, Any]]] = [(
            lambda seq, prev, p=decision_payload: build_entry(
                store_sequence=seq, entry_kind="decision", recorded_at=now,
                payload=p, prev_entry_digest=prev, index=index,
            ),
            decision_payload,
        )]
        if proof is not None:
            proof_payload = proof.model_dump(mode="json")
            pending.append((
                lambda seq, prev, p=proof_payload: build_entry(
                    store_sequence=seq, entry_kind="justification", recorded_at=now,
                    payload=p, prev_entry_digest=prev, index=index,
                ),
                proof_payload,
            ))
        try:
            entries = self._na.db.append_evidence_entries(pending)
        except self._na.db.database_errors as exc:
            logger.warning("evidence store write failed for decision %s: %s", decision.decision_id, exc)
            raise ServiceUnavailableError(
                "The decision could not be stored", code="evidence_store_unavailable"
            ) from exc
        self._na.db.add_audit_event("decision_stored", {
            "decision_id": decision.decision_id,
            "store_sequence": entries[0].store_sequence,
            "vendor_id": index["vendor_id"],
            "authorized": decision.authorized,
        })
        self.maybe_anchor()

    # -- execution evidence ---------------------------------------------------

    def _reject(
        self, code: str, detail: str, evidence: ExecutionEvidence | None, digest: str | None,
        raw: dict[str, Any] | None = None,
    ) -> NoReturn:
        # v1.3.0: an authentic record refused for good is kept as a quarantine
        # entry: the action it describes already happened.
        quarantine_id = (
            self._na.out_of_band_service.quarantine_execution(code, detail, evidence, raw)
            if evidence is not None and raw is not None else None
        )
        self._na.db.add_evidence_rejection(
            code,
            submitted_digest=digest,
            evidence_id=evidence.evidence_id if evidence else None,
            decision_id=evidence.decision_id if evidence else None,
            resource_id=evidence.resource_id if evidence else None,
            executor_sovereign_id=evidence.executor_sovereign_id if evidence else None,
        )
        self._na.db.add_audit_event("evidence_rejected", {
            "code": code,
            "evidence_id": evidence.evidence_id if evidence else None,
            "decision_id": evidence.decision_id if evidence else None,
            "resource_id": evidence.resource_id if evidence else None,
            "submitted_digest": digest,
        })
        error = ConflictError if code == "evidence_conflict" else ValidationError
        raise error(detail, code=code, details={"quarantine_id": quarantine_id} if quarantine_id else None)

    def submit_execution(self, raw: Any) -> tuple[dict[str, Any], bool]:
        """Validate and store one signed execution record.

        Returns (response body, created).  An identical resubmission is
        idempotent: it returns the stored entry with created=False.
        """
        self.require_enabled()
        if not isinstance(raw, dict):
            raise BadRequestError("evidence must be an object", code="invalid_evidence")
        digest = payload_digest(raw)
        try:
            evidence = ExecutionEvidence.model_validate(raw)
        except PydanticValidationError:
            self._reject("evidence_malformed", "evidence does not match the ExecutionEvidence model", None, digest)
        # v1.1.1: the stored payload must be exactly what the signature covers.
        # Extra fields, coerced types or other variants would be stored and
        # exported as received; refuse them instead of repairing them.
        difference = _serialized_form_difference(raw, evidence)
        if difference is not None:
            self._reject(
                "evidence_malformed",
                f"evidence is not in its exact serialized form: {difference}",
                evidence,
                digest,
            )

        duplicate = self._stored_duplicate(evidence, digest, raw)
        if duplicate is not None:
            return duplicate, False

        key_row = self._na.db.get_executor_key(evidence.signature.key_id) if evidence.signature else None
        executor_key = self.key_from_row(key_row) if key_row else None

        decision_stored = self._na.db.get_decision_entry(evidence.decision_id)
        decision = context = None
        decision_fields: dict[str, Any] = {}
        if decision_stored is not None:
            decision = BoundaryDecision.model_validate(decision_stored["payload"]["decision"])
            context = ContextRecord.model_validate(decision_stored["payload"]["context"])
            decision_fields = decision_stored["entry"].model_dump()

        prev_exec_stored = self._na.db.last_execution_for_decision(evidence.decision_id)
        prev_exec = ExecutionEvidence.model_validate(prev_exec_stored["payload"]) if prev_exec_stored else None
        head = self._resource_head(evidence.resource_id) if evidence.resource_id else None

        check = validate_execution(
            evidence,
            executor_key=executor_key,
            decision=decision,
            context=context,
            prev_decision_record=prev_exec,
            resource_head=head,
        )
        if not check.accepted:
            assert check.code is not None
            if check.code == "evidence_conflict":
                # The same record may have been stored by another instance or
                # worker since the duplicate check above (v0.60).
                duplicate = self._stored_duplicate(evidence, digest, raw)
                if duplicate is not None:
                    return duplicate, False
            self._reject(check.code, check.detail, evidence, digest, raw)

        index = execution_index(evidence, decision_fields)
        recorded_at = datetime.now(timezone.utc)
        version = evidence.execution_parameters.get("version_id")
        lookup = {"version_id": version} if isinstance(version, str) and version else {}
        try:
            entries = self._na.db.append_evidence_entries([(
                lambda seq, prev: build_entry(
                    store_sequence=seq, entry_kind="execution", recorded_at=recorded_at,
                    payload=raw, prev_entry_digest=prev, index=index,
                ),
                raw,
                lookup,
            )])
        except self._na.db.integrity_errors:
            # Another writer took this position between validation and insert:
            # if it stored this very record, the submission is a duplicate.
            duplicate = self._stored_duplicate(evidence, digest, raw)
            if duplicate is not None:
                return duplicate, False
            self._reject("evidence_conflict", "the chain position was taken by another record", evidence, digest, raw)
        stored = {"entry": entries[0], "entry_digest": entries[0].digest(), "payload": raw}
        self._na.db.add_audit_event("evidence_recorded", {
            "evidence_id": evidence.evidence_id,
            "decision_id": evidence.decision_id,
            "resource_id": evidence.resource_id,
            "resource_sequence": evidence.resource_sequence,
            "store_sequence": entries[0].store_sequence,
            "executor_sovereign_id": evidence.executor_sovereign_id,
        })
        self.maybe_anchor()
        return self._entry_body(stored), True

    def _stored_duplicate(
        self, evidence: ExecutionEvidence, digest: str, raw: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """The stored entry when this exact record is already stored; None when it is not.

        Rejects with ``evidence_conflict`` when a different record holds the
        same ``evidence_id``. An identical resubmission -- including one that
        raced another instance or worker -- is idempotent.
        """
        existing = self._na.db.get_entry_by_evidence_id(evidence.evidence_id)
        if existing is None:
            return None
        if existing["entry"].payload_digest != digest:
            self._reject("evidence_conflict", "a different record with this evidence_id is stored",
                         evidence, digest, raw)
        self._na.db.add_audit_event("evidence_duplicate", {
            "evidence_id": evidence.evidence_id,
            "store_sequence": existing["entry"].store_sequence,
        })
        return self._entry_body(existing)

    def _resource_head(self, resource_id: str) -> ResourceHeadState | None:
        """The resource chain's head: its latest execution record (observations take no position)."""
        last = self._na.db.last_resource_record(resource_id)
        if last is not None:
            record = ExecutionEvidence.model_validate(last["payload"])
            return ResourceHeadState(record.resource_sequence or 0, record.digest())
        cp = self._na.db.latest_retention_checkpoint()
        if cp is not None and resource_id in cp.resource_heads:
            h = cp.resource_heads[resource_id]
            return ResourceHeadState(h.resource_sequence, h.record_digest)
        return None

    @staticmethod
    def _entry_body(stored: dict[str, Any]) -> dict[str, Any]:
        entry: EvidenceStoreEntry = stored["entry"]
        return {"entry": entry.model_dump(mode="json"), "entry_digest": stored["entry_digest"]}

    # -- executor keys ----------------------------------------------------------

    def register_executor_key(self, data: dict[str, Any], registered_by: str) -> dict[str, Any]:
        """Register an executor or (v1.3.0) observer key, optionally scoped to a resource prefix."""
        self.require_enabled()
        key_id = data.get("key_id")
        public_key = data.get("public_key")
        executor = data.get("executor_sovereign_id")
        if not all(isinstance(v, str) and v for v in (key_id, public_key, executor)):
            raise BadRequestError(
                "key_id, public_key and executor_sovereign_id are required", code="missing_executor_key_fields"
            )
        role = data.get("role", "executor")
        if role not in ("executor", "observer"):
            raise BadRequestError("role must be 'executor' or 'observer'", code="invalid_key_role")
        prefix = data.get("resource_prefix")
        if prefix is not None and (not isinstance(prefix, str) or not 1 <= len(prefix) <= 256):
            raise BadRequestError("resource_prefix must be a string of 1 to 256 characters",
                                  code="invalid_resource_prefix")
        try:
            raw = nacl.encoding.Base64Encoder.decode(str(public_key).encode())
        except Exception as exc:  # noqa: BLE001 -- any decode failure is a bad key
            raise BadRequestError("public_key must be base64 Ed25519", code="invalid_public_key") from exc
        if len(raw) != 32:
            raise BadRequestError("public_key must be a 32-byte Ed25519 key", code="invalid_public_key")
        try:
            registered_at = self._na.db.register_executor_key(
                str(key_id), str(public_key), str(executor), registered_by, role=role, resource_prefix=prefix,
            )
        except self._na.db.integrity_errors as exc:
            raise ConflictError("key_id is already registered", code="executor_key_exists") from exc
        self._na.db.add_audit_event("executor_key_registered", {
            "key_id": key_id, "executor_sovereign_id": executor, "registered_by": registered_by,
            "role": role, "resource_prefix": prefix,
        })
        self._na.out_of_band_service.key_registered(
            ExecutorKey(key_id=str(key_id), public_key=str(public_key), executor_sovereign_id=str(executor),
                        role=role, resource_prefix=prefix),
            registered_at, registered_by,
        )
        out: dict[str, Any] = {"key_id": key_id, "executor_sovereign_id": executor, "active": True, "role": role}
        if prefix is not None:
            out["resource_prefix"] = prefix
        return out

    def retire_executor_key(self, key_id: str, retired_by: str) -> dict[str, Any]:
        self.require_enabled()
        if self._na.db.get_executor_key(key_id) is None:
            raise NotFoundError("unknown executor key", code="executor_key_not_found")
        if not self._na.db.retire_executor_key(key_id, retired_by):
            raise ConflictError("executor key is already retired", code="executor_key_retired")
        self._na.db.add_audit_event("executor_key_retired", {"key_id": key_id, "retired_by": retired_by})
        self._na.out_of_band_service.key_retired(key_id, retired_by)
        return {"key_id": key_id, "active": False}

    def list_executor_keys(self) -> list[dict[str, Any]]:
        self.require_enabled()
        return [
            {
                "key_id": row["key_id"],
                "public_key": row["public_key"],
                "executor_sovereign_id": row["executor_sovereign_id"],
                "registered_at": row["registered_at"],
                "retired_at": row["retired_at"],
                "role": self.key_from_row(row).role,
                "resource_prefix": self.key_from_row(row).resource_prefix,
            }
            for row in self._na.db.list_executor_keys()
        ]

    # -- search, history, export ----------------------------------------------

    def search(self, args: dict[str, str]) -> dict[str, Any]:
        self.require_enabled()
        filters = {k: v for k, v in args.items() if k in (
            "vendor_id", "attestation_id", "capability", "resource_id", "outcome", "entry_kind", "decision_id",
        ) and v}
        after, limit = self._page(args)
        rows = self._na.db.search_evidence(
            filters, since=args.get("since") or None, until=args.get("until") or None,
            after_sequence=after, limit=limit,
        )
        return {
            "count": len(rows),
            "next_after_sequence": rows[-1]["entry"].store_sequence if len(rows) == limit else None,
            "entries": [_event(r).model_dump(mode="json", by_alias=True) for r in rows],
        }

    @staticmethod
    def _page(args: dict[str, str]) -> tuple[int, int]:
        try:
            after = int(args.get("after_sequence") or 0)
            limit = int(args.get("limit") or 100)
        except ValueError as exc:
            raise BadRequestError("after_sequence and limit must be integers", code="invalid_page") from exc
        if after < 0 or not 1 <= limit <= MAX_PAGE:
            raise BadRequestError(f"limit must be 1..{MAX_PAGE}", code="invalid_page")
        return after, limit

    def _history(self, decision_ids: list[str], extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = self._na.db.entries_for_decisions(sorted(set(decision_ids)))
        if extra:
            seen = {r["entry"].store_sequence for r in rows}
            rows = sorted([*rows, *(r for r in extra if r["entry"].store_sequence not in seen)],
                          key=lambda r: r["entry"].store_sequence)
        events = [_event(r) for r in rows]
        verification: EvidenceVerification = verify_evidence_events(
            events,
            na_public_keys=self.na_public_keys(),
            executor_keys=self.executor_keys(),
            contiguous=False,
            checkpoint=self._na.db.latest_retention_checkpoint(),
        )
        return {
            "entries": [e.model_dump(mode="json", by_alias=True) for e in events],
            "verification": verification.to_dict(),
        }

    def resource_head(self, resource_id: str) -> dict[str, Any]:
        """Where the next record of a resource must link: one indexed lookup (v0.63.1).

        The same head submission validation uses: the latest stored record, or
        the latest retention checkpoint once retention removed every stored
        record. It is a hint for building the next record; submission still
        validates the chain.
        """
        self.require_enabled()
        head = self._resource_head(resource_id)
        if head is None:
            raise NotFoundError("no evidence for this resource", code="resource_not_found")
        return {
            "resource_id": resource_id,
            "resource_sequence": head.resource_sequence,
            "record_digest": head.record_digest,
        }

    def resource_history(self, resource_id: str) -> dict[str, Any]:
        """History of one resource, decision to execution, verified.

        At most ``HISTORY_LIMIT`` records (the oldest); ``truncated`` says
        when a longer chain was cut. Use the export for complete history and
        ``resource_head`` for the next record's link.
        """
        self.require_enabled()
        records = self._na.db.search_evidence({"resource_id": resource_id}, limit=HISTORY_LIMIT + 1)
        if not records:
            raise NotFoundError("no evidence for this resource", code="resource_not_found")
        truncated = len(records) > HISTORY_LIMIT
        records = records[:HISTORY_LIMIT]
        decision_ids = [r["entry"].decision_id for r in records if r["entry"].decision_id]
        # v1.3.0: the resource's observations, break-glass records, judgements
        # and quarantine entries, with the decisions its executions rest on.
        stage2 = [r for r in records if r["entry"].entry_kind not in ("decision", "justification", "execution")]
        history = self._history(decision_ids, extra=stage2)
        # Only this resource's execution records, plus the decisions they rest on.
        history["entries"] = [
            e for e in history["entries"]
            if e["entry"]["entry_kind"] != "execution" or e["entry"]["resource_id"] == resource_id
        ]
        return {"resource_id": resource_id, "truncated": truncated, **history}

    def vendor_history(self, vendor_id: str) -> dict[str, Any]:
        """Every decision for a vendor and the evidence under it, verified."""
        self.require_enabled()
        decisions = self._na.db.search_evidence(
            {"vendor_id": vendor_id, "entry_kind": "decision"}, limit=HISTORY_LIMIT + 1
        )
        if not decisions:
            raise NotFoundError("no decisions for this vendor", code="vendor_not_found")
        truncated = len(decisions) > HISTORY_LIMIT
        decisions = decisions[:HISTORY_LIMIT]
        return {"vendor_id": vendor_id, "truncated": truncated,
                **self._history([d["entry"].decision_id for d in decisions])}

    def export_lines(self, args: dict[str, str]) -> list[str]:
        """``gm.evidence.event`` JSON Lines in store order, for incremental SIEM pulls."""
        self.require_enabled()
        try:
            since = int(args.get("since_sequence") or 0)
            limit = int(args.get("limit") or MAX_PAGE)
        except ValueError as exc:
            raise BadRequestError("since_sequence and limit must be integers", code="invalid_page") from exc
        if since < 0 or not 1 <= limit <= MAX_PAGE:
            raise BadRequestError(f"limit must be 1..{MAX_PAGE}", code="invalid_page")
        rows = self._na.db.search_evidence({}, after_sequence=since, limit=limit)
        return [_event(r).to_json_line() for r in rows]

    def verify_store(self) -> dict[str, Any]:
        """Verify the whole store from the latest checkpoint onward."""
        self.require_enabled()
        rows = self._na.db.search_evidence({}, limit=10**9)
        events = [_event(r) for r in rows]
        result = verify_evidence_events(
            events,
            na_public_keys=self.na_public_keys(),
            executor_keys=self.executor_keys(),
            contiguous=True,
            checkpoint=self._na.db.latest_retention_checkpoint(),
        )
        # v1.2.0: the NA's own anchors must form an unbroken signed chain and
        # name the digests of the entries still stored.
        anchors = self._na.db.list_store_anchors(limit=10**9)
        chain = verify_store_anchors(
            anchors, na_public_keys=self.na_public_keys(), sovereign_id=self._na.genesis_block.network_name
        )
        check_events_against_anchors(events, anchors, result)
        assert result.anchors is not None
        result.anchors["chain"] = chain.to_dict()
        for failure in chain.failures:
            result.fail(None, failure["reason"], f"anchor {failure['anchor_sequence']} {failure['detail']}".rstrip())
        return result.to_dict()

    def status(self) -> dict[str, Any]:
        stats = self._na.db.evidence_stats() if self.enabled else {}
        cp = self._na.db.latest_retention_checkpoint() if self.enabled else None
        out: dict[str, Any] = {
            "evidence_store": self._na.evidence_store,
            **stats,
            "retention_checkpoint": cp.removed_through_sequence if cp else None,
        }
        if self.enabled:
            anchor = self._na.db.latest_store_anchor()
            head, _ = self._na.db.store_head()
            out["latest_anchor"] = {
                "anchor_sequence": anchor.anchor_sequence,
                "store_sequence": anchor.store_sequence,
                "anchored_at": anchor.anchored_at.isoformat(),
            } if anchor else None
            out["unanchored_entries"] = max(0, head - (anchor.store_sequence if anchor else 0))
        return out

    # -- anchors (v1.2.0) -------------------------------------------------------

    #: Largest lead the last anchor's time may have over this instance's clock.
    ANCHOR_CLOCK_TOLERANCE = timedelta(minutes=5)

    def _continuity_problem(self, latest: StoreAnchor, head_seq: int, head_digest: str | None) -> str | None:
        """Why the store does not continue from the latest anchor, or None.

        The NA signs a new anchor only over a store that still contains what
        it anchored last: otherwise a database writer without the NA key
        could rewrite history and have the NA extend its signed chain over it.
        """
        db = self._na.db
        if head_seq < latest.store_sequence or head_digest is None:
            return f"the store ends at {head_seq}, before anchored entry {latest.store_sequence}"
        start_seq, prev = latest.store_sequence, latest.entry_digest
        stored = db.entry_digest_at(latest.store_sequence)
        if stored is not None:
            if stored != latest.entry_digest:
                return f"entry {latest.store_sequence} no longer has the digest anchor {latest.anchor_sequence} names"
        else:
            cp = db.latest_retention_checkpoint()
            if cp is None or cp.removed_through_sequence < latest.store_sequence:
                return f"anchored entry {latest.store_sequence} is gone and no retention checkpoint covers it"
            if not verify_retention_checkpoint(cp, self.na_public_keys()):
                return "the retention checkpoint that removed the anchored entry is not signed by this NA"
            if cp.removed_through_sequence == latest.store_sequence and cp.last_removed_entry_digest != prev:
                return f"the retention checkpoint names another digest for anchored entry {latest.store_sequence}"
            start_seq, prev = cp.removed_through_sequence, cp.last_removed_entry_digest
        expected = start_seq + 1
        for row in db.search_evidence({}, after_sequence=start_seq, limit=10**9):
            entry: EvidenceStoreEntry = row["entry"]
            if entry.store_sequence != expected:
                return f"entry {expected} is missing"
            if (entry.prev_entry_digest != prev or entry.digest() != row["entry_digest"]
                    or payload_digest(row["payload"]) != entry.payload_digest):
                return f"entry {entry.store_sequence} does not continue the anchored chain"
            prev, expected = row["entry_digest"], expected + 1
        if expected - 1 != head_seq or prev != head_digest:
            return "the store head does not continue the anchored chain"
        return None

    def anchor(self) -> tuple[StoreAnchor | None, bool]:
        """Sign the store's current head. Returns (anchor, created).

        When the head is already anchored (or the store is empty) nothing new
        is signed and the latest anchor is returned with created=False. Runs
        inside the evidence write transaction, so the head cannot move while
        it is checked and signed. Refuses (``409 evidence_anchor_refused``)
        when the store no longer continues from the last anchor, or when the
        last anchor's time is far ahead of this instance's clock.
        """
        self.require_enabled()
        now = datetime.now(timezone.utc)

        def make(latest: StoreAnchor | None, seq: int, digest: str | None) -> StoreAnchor | None:
            if seq == 0 or digest is None or (latest is not None and latest.store_sequence >= seq):
                return None
            anchored_at = now
            if latest is not None:
                problem = self._continuity_problem(latest, seq, digest)
                if problem:
                    raise _AnchorRefused(problem)
                if latest.anchored_at > now:
                    if latest.anchored_at - now > self.ANCHOR_CLOCK_TOLERANCE:
                        raise _AnchorRefused(
                            f"anchor {latest.anchor_sequence} is dated {latest.anchored_at.isoformat()}, "
                            "ahead of this instance's clock"
                        )
                    anchored_at = latest.anchored_at  # small skew between instances
            return sign_store_anchor(
                StoreAnchor(
                    anchor_sequence=latest.anchor_sequence + 1 if latest else 1,
                    sovereign_id=self._na.genesis_block.network_name,
                    store_sequence=seq,
                    entry_digest=digest,
                    anchored_at=anchored_at,
                    previous_anchor_digest=latest.digest() if latest else None,
                    issued_by=self._na.key_id,
                ),
                self._na.signer,
                self._na.key_id,
            )

        try:
            anchor, created = self._na.db.append_store_anchor(make)
        except _AnchorRefused as exc:
            logger.error("evidence store anchor refused: %s", exc)
            self._na.db.add_audit_event("evidence_anchor_refused", {"reason": str(exc)})
            raise ConflictError(
                "The evidence store cannot be anchored: " + str(exc), code="evidence_anchor_refused"
            ) from exc
        except self._na.db.integrity_errors:
            # Defence in depth: the write lock serializes anchoring, so another
            # writer taking this position means it anchored first.
            return self._na.db.latest_store_anchor(), False
        if created:
            assert anchor is not None
            self._na.db.add_audit_event("evidence_anchored", {
                "anchor_sequence": anchor.anchor_sequence,
                "store_sequence": anchor.store_sequence,
            })
        return anchor, created

    def maybe_anchor(self) -> None:
        """Anchor after an append once the interval has passed; never fails the caller.

        The append has already succeeded: a failed or refused anchor is
        logged and audited, and this worker tries again on an append after a
        back-off of at most a minute (or on ``POST /admin/evidence/anchors``).
        """
        interval = self._na.anchor_interval_seconds
        clock = time.monotonic()
        if interval <= 0 or clock < self._next_anchor_check:
            return
        try:
            latest = self._na.db.latest_store_anchor()
            if latest is not None:
                due = latest.anchored_at + timedelta(seconds=interval)
                wait = (due - datetime.now(timezone.utc)).total_seconds()
                if wait > 0:
                    self._next_anchor_check = clock + min(wait, interval)
                    return
            self.anchor()
            self._next_anchor_check = clock + interval
        except Exception as exc:  # noqa: BLE001 -- anchoring must never fail a stored append
            logger.warning("evidence store anchor failed: %s", exc)
            self._next_anchor_check = clock + min(interval, 60)
            if not isinstance(exc, ConflictError):  # a refusal is already audited
                try:
                    self._na.db.add_audit_event("evidence_anchor_failed", {"error": type(exc).__name__})
                except Exception:  # noqa: BLE001
                    pass

    def list_anchors(self, args: dict[str, str]) -> dict[str, Any]:
        self.require_enabled()
        try:
            after = int(args.get("after_anchor") or 0)
            limit = int(args.get("limit") or 100)
        except ValueError as exc:
            raise BadRequestError("after_anchor and limit must be integers", code="invalid_page") from exc
        if after < 0:
            raise BadRequestError("after_anchor must be 0 or more", code="invalid_page")
        if not 1 <= limit <= MAX_PAGE:
            raise BadRequestError(f"limit must be 1..{MAX_PAGE}", code="invalid_page")
        anchors = self._na.db.list_store_anchors(after_anchor=after, limit=limit)
        return {
            "count": len(anchors),
            "next_after_anchor": anchors[-1].anchor_sequence if len(anchors) == limit else None,
            "anchors": [a.to_wire() for a in anchors],
        }

    # -- retention ------------------------------------------------------------

    #: Single-runner lease for retention (v0.60): one instance applies it at a time.
    RETENTION_LEASE = "evidence-retention"
    RETENTION_LEASE_TTL_SECONDS = 300

    def apply_retention(self, older_than_days: Any, applied_by: str) -> dict[str, Any]:
        """Remove a verifiable prefix of the store older than the cut-off.

        Runs under a job lease, so with several NA instances only one applies
        retention at a time; a concurrent request gets ``retention_in_progress``.
        """
        self.require_enabled()
        if isinstance(older_than_days, bool) or not isinstance(older_than_days, int) or older_than_days < 1:
            raise BadRequestError("older_than_days must be a positive integer", code="invalid_retention")
        holder = self._na.instance_id
        if not self._na.db.claim_lease(self.RETENTION_LEASE, holder, self.RETENTION_LEASE_TTL_SECONDS):
            raise ConflictError("Retention is already running on another instance", code="retention_in_progress")
        try:
            return self._apply_retention(older_than_days, applied_by)
        finally:
            self._na.db.release_lease(self.RETENTION_LEASE, holder)

    def _apply_retention(self, older_than_days: int, applied_by: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=older_than_days)
        rows = self._na.db.retention_candidates()
        valid_until: dict[str, datetime] = {}
        judged: set[str] = set()
        for r in rows:
            if r["entry_kind"] == "decision":
                d = json.loads(r["payload_json"])["decision"]
                valid_until[r["decision_id"]] = datetime.fromisoformat(d["decision_valid_until"])
            elif r["entry_kind"] == "judgement" and r["subject_id"]:
                judged.add(r["subject_id"])

        def group(r: Any) -> str | None:
            # v1.3.0: an observation or break-glass record stays with its judgement.
            if r["entry_kind"] == "judgement":
                return f"subject:{r['subject_id']}"
            if r["entry_kind"] in ("observation", "break_glass"):
                return f"subject:{r['record_id']}"
            return None

        candidates = [
            RetentionCandidate(
                store_sequence=int(r["store_sequence"]),
                recorded_at=datetime.fromisoformat(r["recorded_at"]),
                decision_id=r["decision_id"],
                resource_id=r["resource_id"],
                resource_sequence=r["resource_sequence"],
                decision_valid_until=valid_until.get(r["decision_id"]) if r["decision_id"] else None,
                group_id=group(r),
                pinned=r["entry_kind"] in ("observation", "break_glass") and r["record_id"] not in judged,
            )
            for r in rows
        ]
        n = plan_retention(candidates, cutoff=cutoff, now=now, resource_latest=self._na.db.resource_latest_sequences())
        if n == 0:
            self._na.db.add_audit_event("evidence_retention_applied", {
                "older_than_days": older_than_days, "removed_count": 0, "applied_by": applied_by,
            })
            return {"removed_count": 0, "checkpoint": None}

        removed = [r for r in rows if int(r["store_sequence"]) <= n]
        heads: dict[str, ResourceHead] = {}
        observation_heads: dict[str, int] = {}
        carried: list[tuple[dict[str, Any], str | None]] = []
        for r in removed:
            if r["entry_kind"] == "execution" and r["resource_id"]:
                record = ExecutionEvidence.model_validate(json.loads(r["payload_json"]))
                heads[r["resource_id"]] = ResourceHead(
                    resource_sequence=record.resource_sequence or 0, record_digest=record.digest()
                )
            elif r["entry_kind"] == "observation" and r["resource_id"] and r["observation_sequence"]:
                observation_heads[r["resource_id"]] = int(r["observation_sequence"])
            elif r["entry_kind"] == "registry":
                # v1.3.0: judgements replay the registry; a removed registry
                # record is carried forward unchanged after the checkpoint.
                carried.append((json.loads(r["payload_json"]), r["dedupe_key"]))
        previous = self._na.db.latest_retention_checkpoint()
        all_observation_heads = {**((previous.observation_heads or {}) if previous else {}), **observation_heads}
        checkpoint = sign_retention_checkpoint(
            RetentionCheckpoint(
                cutoff=cutoff,
                removed_through_sequence=n,
                last_removed_entry_digest=removed[-1]["entry_digest"],
                removed_count=len(removed),
                resource_heads={**(previous.resource_heads if previous else {}), **heads},
                previous_checkpoint_id=previous.checkpoint_id if previous else None,
                issued_by=self._na.key_id,
                observation_heads=all_observation_heads or None,
            ),
            self._na.signer,
            self._na.key_id,
        )
        payload = json.loads(checkpoint.model_dump_json())

        def carry(record: dict[str, Any], dedupe_key: str | None) -> Any:
            index = {"record_id": record.get("registry_record_id"), "outcome": record.get("event")}
            return (
                lambda seq, prev, p=record, i=index: build_entry(
                    store_sequence=seq, entry_kind="registry", recorded_at=now,
                    payload=p, prev_entry_digest=prev, index=i,
                ),
                record,
                {"dedupe_key": dedupe_key} if dedupe_key else {},
            )

        entry = self._na.db.apply_retention_checkpoint(
            checkpoint,
            lambda seq, prev: build_entry(
                store_sequence=seq, entry_kind="retention_checkpoint", recorded_at=now,
                payload=payload, prev_entry_digest=prev, index={},
            ),
            carried=[carry(record, dedupe) for record, dedupe in carried],
        )
        self._na.db.add_audit_event("evidence_retention_applied", {
            "older_than_days": older_than_days,
            "removed_through_sequence": n,
            "removed_count": len(removed),
            "checkpoint_id": checkpoint.checkpoint_id,
            "checkpoint_store_sequence": entry.store_sequence,
            "applied_by": applied_by,
        })
        self.maybe_anchor()
        return {"removed_count": len(removed), "checkpoint": payload}
