"""Evidence store protocol logic (v0.59): validation, chains and verification.

Pure functions only.  The Network Authority loads state and passes it in;
nothing here performs I/O or reads the clock.

Two chains protect execution evidence:

* the per-decision chain (``sequence_no`` / ``prev_evidence_digest``,
  unchanged since v0.28), and
* the per-resource chain (``resource_sequence`` / ``prev_resource_digest``,
  v0.59), one history per secret across decisions.

The store itself is a third chain: every ``EvidenceStoreEntry`` links to the
previous entry's digest, so an edited, removed or reordered entry is
detectable.  A signed ``RetentionCheckpoint`` records what a retention run
removed so the remaining history still verifies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal, Sequence

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import BoundaryDecision, ContextRecord
from ..models.evidence_store import (
    EvidenceEvent,
    EvidenceStoreEntry,
    RetentionCheckpoint,
    payload_digest,
)
from ..models.execution import ExecutionEvidence
from ..models.justification import JustificationProof
from genesis_mesh.crypto.signing import SigningKeyLike

EvidenceRejectionCode = Literal[
    "evidence_malformed",
    "evidence_unknown_executor",
    "evidence_invalid_signature",
    "evidence_decision_not_found",
    "evidence_decision_denied",
    "evidence_decision_mismatch",
    "evidence_outside_decision_window",
    "evidence_capability_mismatch",
    "evidence_chain_gap",
    "evidence_chain_mismatch",
    "resource_chain_gap",
    "resource_chain_mismatch",
    "evidence_conflict",
    "evidence_secret_material",
]

#: Hard limit on the metadata a record may carry (execution_parameters + outcome_detail).
MAX_METADATA_BYTES = 16 * 1024

#: Field names that must never appear in stored metadata (compared after
#: lower-casing and removing ``-``, ``_`` and ``.``).
_SECRET_KEYS = frozenset({
    "value", "secret", "secretvalue", "password", "passwd", "passphrase", "token",
    "accesstoken", "refreshtoken", "bearer", "privatekey", "keymaterial",
    "credential", "credentials", "clientsecret", "apikey", "pem", "connectionstring",
})
_LONG_OPAQUE = re.compile(r"^[A-Za-z0-9+/=_\-]{120,}$")
_JWT = re.compile(r"^eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class ExecutorKey:
    """A registered executor signing key."""

    key_id: str
    public_key: str
    executor_sovereign_id: str
    retired: bool = False


@dataclass(frozen=True)
class ResourceHeadState:
    """Last known record of a resource chain (stored, or from a checkpoint)."""

    resource_sequence: int
    record_digest: str


@dataclass(frozen=True)
class EvidenceCheck:
    """Outcome of validating one submitted execution record."""

    code: EvidenceRejectionCode | None
    detail: str

    @property
    def accepted(self) -> bool:
        return self.code is None


def _normalise_key(key: str) -> str:
    return key.lower().replace("-", "").replace("_", "").replace(".", "")


def _secret_material(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and _normalise_key(k) in _SECRET_KEYS:
                return f"field {path + k!r} is not allowed in evidence metadata"
            found = _secret_material(v, f"{path}{k}.")
            if found:
                return found
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found = _secret_material(v, f"{path}{i}.")
            if found:
                return found
    elif isinstance(value, str):
        if "-----BEGIN" in value:
            return f"field {path.rstrip('.')!r} contains a PEM block"
        if _LONG_OPAQUE.match(value) or _JWT.match(value):
            return f"field {path.rstrip('.')!r} looks like key or token material"
    return None


def check_metadata_only(evidence: ExecutionEvidence) -> str | None:
    """Return why the record carries secret material, or None.

    A guard, not a guarantee: controllers must send identifiers, versions and
    timestamps (``secret_version``, ``vault_uri``, ``rotated_at``), never values.
    """
    size = len(evidence.model_dump_json(include={"execution_parameters", "outcome_detail"}).encode("utf-8"))
    if size > MAX_METADATA_BYTES:
        return f"metadata is {size} bytes, over the {MAX_METADATA_BYTES}-byte limit"
    found = _secret_material(evidence.execution_parameters)
    if found:
        return found
    if evidence.outcome_detail:
        return _secret_material({"outcome_detail": evidence.outcome_detail})
    return None


def validate_execution(
    evidence: ExecutionEvidence,
    *,
    executor_key: ExecutorKey | None,
    decision: BoundaryDecision | None,
    context: ContextRecord | None,
    prev_decision_record: ExecutionEvidence | None,
    resource_head: ResourceHeadState | None,
) -> EvidenceCheck:
    """Validate a submitted execution record against the stored state.

    Checks run in a fixed order and the first failure is returned, so the
    rejection code is deterministic.
    """

    def reject(code: EvidenceRejectionCode, detail: str) -> EvidenceCheck:
        return EvidenceCheck(code=code, detail=detail)

    has_resource = [
        evidence.resource_id is not None,
        evidence.resource_action is not None,
        evidence.resource_sequence is not None,
    ]
    if any(has_resource) and not all(has_resource):
        return reject("evidence_malformed", "resource_id, resource_action and resource_sequence go together")
    if evidence.resource_id is None and evidence.prev_resource_digest is not None:
        return reject("evidence_malformed", "prev_resource_digest requires resource_id")

    if evidence.signature is None:
        return reject("evidence_invalid_signature", "evidence is not signed")
    if executor_key is None or executor_key.executor_sovereign_id != evidence.executor_sovereign_id:
        return reject("evidence_unknown_executor", "signing key is not registered for this executor")
    if executor_key.retired:
        return reject("evidence_unknown_executor", "signing key is retired")
    if not verify_model_signature(evidence, evidence.signature, executor_key.public_key):
        return reject("evidence_invalid_signature", "signature does not verify")

    if decision is None or context is None:
        return reject("evidence_decision_not_found", f"decision {evidence.decision_id!r} is not in the store")
    if not decision.authorized:
        return reject("evidence_decision_denied", "the decision denied the request")
    if evidence.context_id != decision.context_id or evidence.agreement_id != decision.agreement_id:
        return reject("evidence_decision_mismatch", "context_id or agreement_id does not match the decision")
    if not (decision.decision_made_at <= evidence.executed_at <= decision.decision_valid_until):
        return reject(
            "evidence_outside_decision_window",
            f"executed_at {evidence.executed_at.isoformat()} is outside "
            f"[{decision.decision_made_at.isoformat()}, {decision.decision_valid_until.isoformat()}]",
        )
    if evidence.executed_capability != context.requested_capability:
        return reject(
            "evidence_capability_mismatch",
            f"executed {evidence.executed_capability!r}, decision covers {context.requested_capability!r}",
        )

    expected = prev_decision_record.sequence_no + 1 if prev_decision_record else 1
    if evidence.sequence_no > expected:
        return reject("evidence_chain_gap", f"sequence_no {evidence.sequence_no}, expected {expected}")
    if evidence.sequence_no < expected:
        return reject("evidence_conflict", f"sequence_no {evidence.sequence_no} is already recorded")
    expected_prev = prev_decision_record.digest() if prev_decision_record else None
    if evidence.prev_evidence_digest != expected_prev:
        return reject("evidence_chain_mismatch", "prev_evidence_digest does not match the previous record")

    if evidence.resource_id is not None:
        assert evidence.resource_sequence is not None
        r_expected = resource_head.resource_sequence + 1 if resource_head else 1
        if evidence.resource_sequence > r_expected:
            return reject("resource_chain_gap", f"resource_sequence {evidence.resource_sequence}, expected {r_expected}")
        if evidence.resource_sequence < r_expected:
            return reject("evidence_conflict", f"resource_sequence {evidence.resource_sequence} is already recorded")
        r_prev = resource_head.record_digest if resource_head else None
        if evidence.prev_resource_digest != r_prev:
            return reject("resource_chain_mismatch", "prev_resource_digest does not match the resource's last record")

    secret = check_metadata_only(evidence)
    if secret:
        return reject("evidence_secret_material", secret)
    return EvidenceCheck(code=None, detail="accepted")


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


def build_entry(
    *,
    store_sequence: int,
    entry_kind: str,
    recorded_at: datetime,
    payload: dict[str, Any],
    prev_entry_digest: str | None,
    index: dict[str, Any],
) -> EvidenceStoreEntry:
    """Build the envelope for a payload at a given store position."""
    return EvidenceStoreEntry(
        store_sequence=store_sequence,
        entry_kind=entry_kind,  # type: ignore[arg-type]
        recorded_at=recorded_at,
        payload_digest=payload_digest(payload),
        prev_entry_digest=prev_entry_digest,
        **index,
    )


def decision_index(decision: BoundaryDecision, context: ContextRecord) -> dict[str, Any]:
    """Search fields for a stored decision."""
    binding = decision.attestation_binding
    vendor = binding.subject_id if binding is not None and binding.subject_id else context.requester_sovereign_id
    return {
        "decision_id": decision.decision_id,
        "context_id": decision.context_id,
        "vendor_id": vendor,
        "attestation_id": context.attestation_id,
        "capability": context.requested_capability,
        "outcome": "authorized" if decision.authorized else "denied",
    }


def execution_index(evidence: ExecutionEvidence, decision_fields: dict[str, Any]) -> dict[str, Any]:
    """Search fields for stored execution evidence (vendor/attestation from its decision)."""
    return {
        "decision_id": evidence.decision_id,
        "context_id": evidence.context_id,
        "vendor_id": decision_fields.get("vendor_id"),
        "attestation_id": decision_fields.get("attestation_id"),
        "capability": evidence.executed_capability,
        "outcome": evidence.outcome,
        "evidence_id": evidence.evidence_id,
        "executor_sovereign_id": evidence.executor_sovereign_id,
        "exec_sequence_no": evidence.sequence_no,
        "resource_id": evidence.resource_id,
        "resource_action": evidence.resource_action,
        "resource_sequence": evidence.resource_sequence,
    }


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionCandidate:
    """Metadata of one stored entry, as seen by the retention planner."""

    store_sequence: int
    recorded_at: datetime
    decision_id: str | None
    resource_id: str | None
    resource_sequence: int | None
    decision_valid_until: datetime | None


def plan_retention(
    entries: Sequence[RetentionCandidate],
    *,
    cutoff: datetime,
    now: datetime,
    resource_latest: dict[str, int],
) -> int:
    """Return N: entries 1..N may be removed (0 when nothing may be).

    Only a prefix of the store is ever removed, so every chain loses a prefix
    and stays verifiable from the checkpoint.  The prefix stops before the
    first entry that is newer than the cut-off, is the latest record of its
    resource, or belongs to a decision still inside its validity window, and
    never splits a decision from its justification or evidence.
    """
    ordered = sorted(entries, key=lambda e: e.store_sequence)
    n = 0
    for e in ordered:
        if e.recorded_at >= cutoff:
            break
        if e.resource_id is not None and resource_latest.get(e.resource_id) == e.resource_sequence:
            break
        if e.decision_valid_until is not None and e.decision_valid_until >= now:
            break
        n = e.store_sequence
    changed = True
    while changed and n > 0:
        changed = False
        first_by_decision: dict[str, int] = {}
        split: set[str] = set()
        for e in ordered:
            if e.decision_id is None:
                continue
            first_by_decision.setdefault(e.decision_id, e.store_sequence)
            if e.store_sequence > n and first_by_decision[e.decision_id] <= n:
                split.add(e.decision_id)
        if split:
            n = min(first_by_decision[d] for d in split) - 1
            changed = True
    return max(n, 0)


def sign_retention_checkpoint(
    checkpoint: RetentionCheckpoint, signing_key: SigningKeyLike, key_id: str
) -> RetentionCheckpoint:
    """Return the checkpoint signed by the NA."""
    return checkpoint.model_copy(update={"signature": sign_model(checkpoint, signing_key, key_id)})


def verify_retention_checkpoint(checkpoint: RetentionCheckpoint, na_public_keys: Sequence[str]) -> bool:
    """True when the checkpoint carries a valid NA signature."""
    sig = checkpoint.signature
    return sig is not None and any(verify_model_signature(checkpoint, sig, k) for k in na_public_keys)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass
class EvidenceVerification:
    """Result of verifying a set of stored entries."""

    verified: bool = True
    checked_entries: int = 0
    decisions: int = 0
    executions: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, store_sequence: int | None, reason: str, detail: str = "") -> None:
        self.verified = False
        self.failures.append({"store_sequence": store_sequence, "reason": reason, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "checked_entries": self.checked_entries,
            "decisions": self.decisions,
            "executions": self.executions,
            "failures": self.failures,
        }


def _verify_payload(
    event: EvidenceEvent,
    result: EvidenceVerification,
    na_public_keys: Sequence[str],
    executor_keys: dict[str, ExecutorKey],
) -> Any:
    """Verify one payload's signature; return the parsed model (or None)."""
    entry = event.entry
    kind = entry.entry_kind
    try:
        if kind == "decision":
            model: Any = BoundaryDecision.model_validate(event.payload["decision"])
        elif kind == "justification":
            model = JustificationProof.model_validate(event.payload)
        elif kind == "execution":
            model = ExecutionEvidence.model_validate(event.payload)
        else:
            model = RetentionCheckpoint.model_validate(event.payload)
    except (ValueError, KeyError, TypeError):
        result.fail(entry.store_sequence, "payload_invalid")
        return None
    sig = model.signature
    if kind == "execution":
        key = executor_keys.get(sig.key_id) if sig is not None else None
        ok = sig is not None and key is not None and key.executor_sovereign_id == model.executor_sovereign_id \
            and verify_model_signature(model, sig, key.public_key)
    else:
        ok = sig is not None and any(verify_model_signature(model, sig, k) for k in na_public_keys)
    if not ok:
        result.fail(entry.store_sequence, "invalid_signature", kind)
    return model


def verify_evidence_events(
    events: Iterable[EvidenceEvent],
    *,
    na_public_keys: Sequence[str],
    executor_keys: dict[str, ExecutorKey],
    contiguous: bool = True,
    checkpoint: RetentionCheckpoint | None = None,
) -> EvidenceVerification:
    """Verify stored entries: envelopes, store chain, signatures and chains.

    ``contiguous`` asserts the events are an unbroken run of the store (an
    export or the whole store); for a filtered history (one resource or vendor)
    set it False: store links are then checked only between adjacent
    positions.  ``checkpoint`` supplies resource heads for chains whose early
    records were removed by retention.
    """
    result = EvidenceVerification()
    prev: EvidenceStoreEntry | None = None
    decisions: dict[str, BoundaryDecision] = {}
    contexts: dict[str, ContextRecord] = {}
    last_exec: dict[str, ExecutionEvidence] = {}
    resource_heads: dict[str, ResourceHeadState] = {}
    if checkpoint is not None:
        resource_heads = {
            rid: ResourceHeadState(h.resource_sequence, h.record_digest)
            for rid, h in checkpoint.resource_heads.items()
        }
    for event in events:
        entry = event.entry
        result.checked_entries += 1
        if entry.digest() != event.entry_digest:
            result.fail(entry.store_sequence, "entry_digest_mismatch")
        if payload_digest(event.payload) != entry.payload_digest:
            result.fail(entry.store_sequence, "payload_digest_mismatch")
        if prev is not None and (contiguous or entry.store_sequence == prev.store_sequence + 1):
            if entry.store_sequence != prev.store_sequence + 1:
                result.fail(entry.store_sequence, "store_sequence_gap")
            elif entry.prev_entry_digest != prev.digest():
                result.fail(entry.store_sequence, "store_chain_break")
        elif prev is None and checkpoint is not None and entry.store_sequence == checkpoint.removed_through_sequence + 1:
            if entry.prev_entry_digest != checkpoint.last_removed_entry_digest:
                result.fail(entry.store_sequence, "store_chain_break", "does not continue from the checkpoint")
        prev = entry

        model = _verify_payload(event, result, na_public_keys, executor_keys)
        if model is None:
            continue
        if entry.entry_kind == "decision":
            result.decisions += 1
            decisions[model.decision_id] = model
            try:
                contexts[model.decision_id] = ContextRecord.model_validate(event.payload["context"])
            except (ValueError, KeyError, TypeError):
                result.fail(entry.store_sequence, "payload_invalid", "context")
        elif entry.entry_kind == "execution":
            result.executions += 1
            ev: ExecutionEvidence = model
            decision = decisions.get(ev.decision_id)
            if decision is not None:
                ctx = contexts.get(ev.decision_id)
                if not decision.authorized:
                    result.fail(entry.store_sequence, "evidence_decision_denied")
                elif not (decision.decision_made_at <= ev.executed_at <= decision.decision_valid_until):
                    result.fail(entry.store_sequence, "evidence_outside_decision_window")
                elif ctx is not None and ev.executed_capability != ctx.requested_capability:
                    result.fail(entry.store_sequence, "evidence_capability_mismatch")
            prior = last_exec.get(ev.decision_id)
            expected_seq = prior.sequence_no + 1 if prior else None
            if prior is not None and (ev.sequence_no != expected_seq or ev.prev_evidence_digest != prior.digest()):
                result.fail(entry.store_sequence, "evidence_chain_break")
            elif prior is None and decision is not None and (ev.sequence_no != 1 or ev.prev_evidence_digest is not None):
                result.fail(entry.store_sequence, "evidence_chain_break")
            last_exec[ev.decision_id] = ev
            if ev.resource_id is not None:
                head = resource_heads.get(ev.resource_id)
                exp = head.resource_sequence + 1 if head else 1
                if ev.resource_sequence != exp or ev.prev_resource_digest != (head.record_digest if head else None):
                    result.fail(entry.store_sequence, "resource_chain_break", ev.resource_id)
                resource_heads[ev.resource_id] = ResourceHeadState(ev.resource_sequence or 0, ev.digest())
        elif entry.entry_kind == "retention_checkpoint":
            pass
    return result


def parse_export_lines(lines: Iterable[str]) -> list[EvidenceEvent]:
    """Parse ``gm.evidence.event`` JSON Lines (blank lines ignored)."""
    events = []
    for line in lines:
        line = line.strip()
        if line:
            events.append(EvidenceEvent.model_validate_json(line))
    return events
