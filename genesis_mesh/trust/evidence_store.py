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
import typing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal, Sequence

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import BoundaryDecision, ContextRecord
from ..models.evidence_store import (
    EntryKind,
    EvidenceEvent,
    EvidenceStoreEntry,
    RetentionCheckpoint,
    StoreAnchor,
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
    #: Set by ``check_events_against_anchors`` (v1.2.0); absent otherwise.
    anchors: dict[str, Any] | None = None
    #: Findings that do not fail verification (v1.2.0), such as fields a
    #: record carries outside its signature.
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, store_sequence: int | None, reason: str, detail: str = "") -> None:
        self.verified = False
        self.failures.append({"store_sequence": store_sequence, "reason": reason, "detail": detail})

    def warn(self, store_sequence: int | None, reason: str, detail: str = "") -> None:
        self.warnings.append({"store_sequence": store_sequence, "reason": reason, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verified": self.verified,
            "checked_entries": self.checked_entries,
            "decisions": self.decisions,
            "executions": self.executions,
            "failures": self.failures,
        }
        if self.anchors is not None:
            out["anchors"] = self.anchors
        if self.warnings:
            out["warnings"] = self.warnings
        return out


_KNOWN_ENTRY_KINDS = frozenset(typing.get_args(EntryKind))

#: The model each entry kind's payload holds; a decision payload wraps two.
_PAYLOAD_MODELS: dict[str, str] = {
    "justification": "JustificationProof",
    "execution": "ExecutionEvidence",
    "retention_checkpoint": "RetentionCheckpoint",
}


def _unknown_payload_fields(
    kind: str,
    payload: Any,
    na_public_keys: Sequence[str],
    executor_keys: dict[str, ExecutorKey],
) -> tuple[list[str], list[str]]:
    """(unknown signed fields, unknown unsigned fields) of one export payload.

    A field the signature covers is one this release cannot read: the record
    is refused. A field outside the signature (stored as submitted before
    1.1.1, or in a decision payload's wrapper and context, which nothing
    signs) changes nothing the signature proves: it is reported, not refused.
    """
    from ..models.canonical_registry import signed_as_received, unknown_fields

    if not isinstance(payload, dict):
        return [], []
    if kind == "decision":
        unsigned = [k for k in payload if k not in ("decision", "context")]
        unsigned += unknown_fields("ContextRecord", payload.get("context"), path="context.")
        decision = payload.get("decision")
        found = unknown_fields("BoundaryDecision", decision, path="decision.")
        if found and isinstance(decision, dict) and signed_as_received("BoundaryDecision", decision, na_public_keys):
            return found, unsigned
        return [], unsigned + found
    model = _PAYLOAD_MODELS.get(kind)
    found = unknown_fields(model, payload) if model else []
    if not found or model is None:
        return [], []
    if kind == "execution":
        sig = payload.get("signature")
        key = executor_keys.get(str(sig.get("key_id"))) if isinstance(sig, dict) else None
        keys = [key.public_key] if key is not None else []
    else:
        keys = list(na_public_keys)
    return (found, []) if signed_as_received(model, payload, keys) else ([], found)


def _verify_payload(
    event: EvidenceEvent,
    result: EvidenceVerification,
    na_public_keys: Sequence[str],
    executor_keys: dict[str, ExecutorKey],
) -> Any:
    """Verify one payload's signature; return the parsed model (or None)."""
    entry = event.entry
    kind = entry.entry_kind
    # v1.2.0: a signed field this release does not know is refused by name;
    # a field outside the signature is reported and otherwise ignored.
    signed, unsigned = _unknown_payload_fields(kind, event.payload, na_public_keys, executor_keys)
    if signed:
        result.fail(entry.store_sequence, "unknown_field", ", ".join(signed))
        return None
    if unsigned:
        result.warn(entry.store_sequence, "unsigned_field", ", ".join(unsigned))
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
        if entry.entry_kind not in _KNOWN_ENTRY_KINDS:
            # v1.2.0: a kind from a later release; its envelope still chains.
            result.fail(entry.store_sequence, "unknown_entry_kind", entry.entry_kind)
            continue

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


# ---------------------------------------------------------------------------
# Store anchors (v1.2.0)
# ---------------------------------------------------------------------------


def sign_store_anchor(anchor: StoreAnchor, signing_key: SigningKeyLike, key_id: str) -> StoreAnchor:
    """Return the anchor signed by the NA."""
    return anchor.model_copy(update={"signature": sign_model(anchor, signing_key, key_id)})


@dataclass
class AnchorVerification:
    """Result of verifying a run of store anchors."""

    verified: bool = True
    checked_anchors: int = 0
    first_anchor_sequence: int | None = None
    last_anchor_sequence: int | None = None
    anchored_through_sequence: int | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, anchor_sequence: int | None, reason: str, detail: str = "") -> None:
        self.verified = False
        self.failures.append({"anchor_sequence": anchor_sequence, "reason": reason, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "checked_anchors": self.checked_anchors,
            "first_anchor_sequence": self.first_anchor_sequence,
            "last_anchor_sequence": self.last_anchor_sequence,
            "anchored_through_sequence": self.anchored_through_sequence,
            "failures": self.failures,
        }


def verify_store_anchors(
    anchors: Sequence[StoreAnchor],
    *,
    na_public_keys: Sequence[str] | None,
    sovereign_id: str | None = None,
) -> AnchorVerification:
    """Verify a run of anchors: signatures, the anchor chain and monotonic heads.

    ``anchors`` must be ordered by ``anchor_sequence`` and need not start at 1
    (an auditor may hold only recent anchors); a run that starts at 1 must
    start with no previous anchor. ``sovereign_id`` pins whose anchors these
    are. ``na_public_keys=None`` skips the signatures (a database check
    without the NA key) and checks everything else.
    """
    result = AnchorVerification()
    prev: StoreAnchor | None = None
    for anchor in anchors:
        n = anchor.anchor_sequence
        result.checked_anchors += 1
        if result.first_anchor_sequence is None:
            result.first_anchor_sequence = n
        result.last_anchor_sequence = n
        sig = anchor.signature
        if na_public_keys is not None and (
            sig is None or not any(verify_model_signature(anchor, sig, k) for k in na_public_keys)
        ):
            result.fail(n, "anchor_invalid_signature")
        if sovereign_id is not None and anchor.sovereign_id != sovereign_id:
            result.fail(n, "anchor_sovereign_mismatch", anchor.sovereign_id)
        if prev is None:
            if n == 1 and anchor.previous_anchor_digest is not None:
                result.fail(n, "anchor_chain_break", "the first anchor names a previous anchor")
        else:
            if n != prev.anchor_sequence + 1:
                result.fail(n, "anchor_sequence_gap", f"after {prev.anchor_sequence}")
            elif anchor.previous_anchor_digest != prev.digest():
                result.fail(n, "anchor_chain_break")
            if anchor.store_sequence <= prev.store_sequence or anchor.anchored_at < prev.anchored_at:
                result.fail(n, "anchor_not_increasing")
        result.anchored_through_sequence = max(result.anchored_through_sequence or 0, anchor.store_sequence)
        prev = anchor
    return result


def _checkpoint_start(events: Sequence[EvidenceEvent], first: EvidenceEvent) -> bool:
    """True when a retention checkpoint in the run explains where the run starts."""
    for event in events:
        if event.entry.entry_kind != "retention_checkpoint":
            continue
        try:
            cp = RetentionCheckpoint.model_validate(event.payload)
        except ValueError:
            continue
        if (cp.removed_through_sequence == first.entry.store_sequence - 1
                and cp.last_removed_entry_digest == first.entry.prev_entry_digest):
            return True
    return False


def check_events_against_anchors(
    events: Sequence[EvidenceEvent],
    anchors: Sequence[StoreAnchor],
    result: EvidenceVerification,
    *,
    partial: bool = False,
) -> None:
    """Check a contiguous run of entries against anchors held out of band.

    The run must be tied to the anchors at both ends:

    * its start: the run starts at entry 1; or right after a retention
      checkpoint recorded in the run (whose signature the event verification
      checks); or right after a held anchor, whose digest its first entry must
      name. An anchor before a run that starts anywhere else means entries
      before the run are not accounted for (``export_not_linked_to_anchors``);
    * its end: an anchor after the run's last entry means the run stops short
      of history the anchors prove exists (``export_ends_before_anchor``).

    ``partial`` accepts a deliberate slice and skips both ends. Inside the run,
    each anchor must name its entry's digest; because entries are hash-linked,
    a match covers every earlier entry of the run.
    """
    by_sequence = {e.entry.store_sequence: e for e in events}
    ordered = sorted(events, key=lambda e: e.entry.store_sequence)
    first = ordered[0] if ordered else None
    last_seq = ordered[-1].entry.store_sequence if ordered else None
    first_seq = first.entry.store_sequence if first else None
    matched = before = beyond = 0
    anchored_through: int | None = None
    linked_start = first is not None and (first_seq == 1 or _checkpoint_start(ordered, first))
    for anchor in anchors:
        seq = anchor.store_sequence
        if first is None or last_seq is None or first_seq is None or seq > last_seq:
            beyond += 1
            continue
        if seq == first_seq - 1:
            if first.entry.prev_entry_digest == anchor.entry_digest:
                linked_start = True
                matched += 1
                anchored_through = max(anchored_through or 0, seq)
            else:
                result.fail(first_seq, "anchor_mismatch",
                            f"the run does not continue from anchor {anchor.anchor_sequence}")
            continue
        if seq < first_seq:
            before += 1
            continue
        event = by_sequence.get(seq)
        if event is None:
            result.fail(seq, "anchor_entry_missing", f"anchor {anchor.anchor_sequence}")
        elif event.entry_digest != anchor.entry_digest or event.entry.digest() != anchor.entry_digest:
            result.fail(seq, "anchor_mismatch", f"anchor {anchor.anchor_sequence}")
        else:
            matched += 1
            anchored_through = max(anchored_through or 0, seq)
    if before and not linked_start and not partial:
        result.fail(first_seq, "export_not_linked_to_anchors",
                    f"{before} anchor(s) before the first entry, which does not continue from any of them")
    if beyond and not partial:
        result.fail(last_seq, "export_ends_before_anchor", f"{beyond} anchor(s) after the last entry")
    floor = anchored_through or 0
    result.anchors = {
        "anchors_checked": len(anchors),
        "anchors_matched": matched,
        "anchors_before_export": before,
        "anchors_after_export": beyond,
        "linked_start": linked_start,
        "anchored_through_sequence": anchored_through,
        "unanchored_entries": sum(1 for seq in by_sequence if seq > floor),
    }


def parse_export_lines(lines: Iterable[str]) -> list[EvidenceEvent]:
    """Parse ``gm.evidence.event`` JSON Lines (blank lines ignored)."""
    events = []
    for line in lines:
        line = line.strip()
        if line:
            events.append(EvidenceEvent.model_validate_json(line))
    return events
