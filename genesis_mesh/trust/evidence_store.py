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

import hashlib
import re
import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from ..models.key_succession import NAKeyHistory, na_keys_at
from genesis_mesh.crypto.signing import SigningKeyLike
from .. import strict_json

EvidenceRejectionCode = Literal[
    "evidence_malformed",
    "evidence_unknown_executor",
    "evidence_executor_key_retired",
    "evidence_out_of_scope",
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
    """A registered signing key: an executor's, or (v1.3.0) an observer's.

    ``role`` says what the key signs: execution evidence and break-glass
    records (``executor``), or observations (``observer``). A key with a
    ``resource_prefix`` signs only for resources whose id starts with it.
    """

    key_id: str
    public_key: str
    executor_sovereign_id: str
    retired: bool = False
    role: str = "executor"
    resource_prefix: str | None = None

    def covers(self, resource_id: str | None) -> bool:
        """True when this key may sign for ``resource_id``."""
        return self.resource_prefix is None or (resource_id or "").startswith(self.resource_prefix)


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
    if not verify_model_signature(evidence, evidence.signature, executor_key.public_key):
        return reject("evidence_invalid_signature", "signature does not verify")
    # v1.3.0: refusals no retry overcomes have their own codes, checked once the
    # signature verifies: a retired key, an observer key (which never signs
    # execution evidence), and a key with a resource prefix outside it (or
    # without a resource: a scoped key always names one).
    if executor_key.retired:
        return reject("evidence_executor_key_retired", "signing key is retired")
    if executor_key.role != "executor":
        return reject("evidence_out_of_scope", f"signing key is an {executor_key.role} key")
    if executor_key.resource_prefix is not None and (
        evidence.resource_id is None or not executor_key.covers(evidence.resource_id)
    ):
        return reject("evidence_out_of_scope", f"signing key covers only resources starting with "
                      f"{executor_key.resource_prefix!r}")

    if decision is None or context is None:
        return reject("evidence_decision_not_found", f"decision {evidence.decision_id!r} is not in the store")
    if not decision.authorized:
        return reject("evidence_decision_denied", "the decision denied the request")
    if evidence.context_id != decision.context_id or evidence.agreement_id != decision.agreement_id:
        return reject("evidence_decision_mismatch", "context_id or agreement_id does not match the decision")
    made, until = _utc(decision.decision_made_at), _utc(decision.decision_valid_until)
    if not (made <= _utc(evidence.executed_at) <= until):
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
    #: v1.3.0: entries that must stay together (an observation or break-glass
    #: record and its judgement) share a group; a pinned entry (a record not
    #: judged yet) stops retention before it.
    group_id: str | None = None
    pinned: bool = False


def plan_retention(
    entries: Sequence[RetentionCandidate],
    *,
    cutoff: datetime,
    now: datetime,
    through_sequence: int | None = None,
) -> int:
    """Return N: entries 1..N may be removed (0 when nothing may be).

    Only a prefix of the store is ever removed, so every chain loses a prefix
    and stays verifiable from the checkpoint.  The prefix stops before the
    first entry that is newer than the cut-off, belongs to a decision still
    inside its validity window, or (v1.3.0) is a record not judged yet, and
    never splits a decision from its justification or evidence, or (v1.3.0) a
    record from its judgement. v1.5.0: it never goes past ``through_sequence``
    (what was archived, or what the operator asked for), and no longer stops
    at the latest record of a resource: the checkpoint carries every removed
    resource's head.
    """
    ordered = sorted(entries, key=lambda e: e.store_sequence)
    n = 0
    for e in ordered:
        if through_sequence is not None and e.store_sequence > through_sequence:
            break
        if e.recorded_at >= cutoff:
            break
        if e.decision_valid_until is not None and e.decision_valid_until >= now:
            break
        if e.pinned:
            break
        n = e.store_sequence
    changed = True
    while changed and n > 0:
        changed = False
        first_by_group: dict[str, int] = {}
        split: set[str] = set()
        for e in ordered:
            group = e.decision_id or e.group_id
            if group is None:
                continue
            first_by_group.setdefault(group, e.store_sequence)
            if e.store_sequence > n and first_by_group[group] <= n:
                split.add(group)
        if split:
            n = min(first_by_group[g] for g in split) - 1
            changed = True
    return max(n, 0)


def sign_retention_checkpoint(
    checkpoint: RetentionCheckpoint, signing_key: SigningKeyLike, key_id: str
) -> RetentionCheckpoint:
    """Return the checkpoint signed by the NA."""
    return checkpoint.model_copy(update={"signature": sign_model(checkpoint, signing_key, key_id)})


#: NA public keys: a list (valid at every time) or, since 1.5.0, the NA's key history.
NAKeys = typing.Union[Sequence[str], NAKeyHistory]


def verify_retention_checkpoint(checkpoint: RetentionCheckpoint, na_public_keys: NAKeys) -> bool:
    """True when the checkpoint carries a valid NA signature (v1.5.0: by the key valid at its ``created_at``)."""
    sig = checkpoint.signature
    keys = na_keys_at(na_public_keys, _utc(checkpoint.created_at))
    return sig is not None and any(verify_model_signature(checkpoint, sig, k) for k in keys)


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
    #: v1.3.0 counts, reported only when the run holds such entries.
    observations: int = 0
    break_glass: int = 0
    judgements: int = 0
    quarantined: int = 0
    #: v1.4.0 counts, reported only when the run holds such entries.
    remediations: int = 0
    reviews: int = 0
    #: v1.5.0 counts, reported only when the run holds such entries.
    key_successions: int = 0
    archives: int = 0
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
        for name in ("observations", "break_glass", "judgements", "quarantined", "remediations", "reviews",
                     "key_successions", "archives"):
            if getattr(self, name):
                out[name] = getattr(self, name)
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
    # v1.3.0
    "observation": "ObservationRecord",
    "break_glass": "BreakGlassRecord",
    "judgement": "JudgementRecord",
    "quarantine": "QuarantineRecord",
    "registry": "RegistryRecord",
    # v1.4.0
    "remediation": "RemediationRecord",
    "review": "ReviewRecord",
    # v1.5.0
    "key_succession": "KeySuccessionRecord",
    "archive": "ArchiveRecord",
}

#: Kinds signed by a registered key (the rest are signed by the NA; a key succession by the
#: root key and the outgoing NA key).
_KEY_SIGNED_KINDS = frozenset({"execution", "observation", "break_glass", "remediation"})

#: v1.3.1: the payload field holding each kind's record ID, which appears once
#: per kind in a run (``duplicate_record``); a decision's is its decision's.
_RECORD_ID: dict[str, str] = {
    "decision": "decision_id",
    "justification": "proof_id",
    "execution": "evidence_id",
    "retention_checkpoint": "checkpoint_id",
    "observation": "observation_id",
    "break_glass": "break_glass_id",
    "judgement": "judgement_id",
    "quarantine": "quarantine_id",
    "registry": "registry_record_id",
    "remediation": "remediation_id",
    "review": "review_id",
    "key_succession": "succession_id",
    "archive": "archive_id",
}

#: v1.3.1: envelope field -> payload field, for the envelope fields a Stage 2
#: entry derives from its record (``trust.out_of_band.entry_index``, as the NA
#: writes them; an absent field is null). The NA searches and matches on
#: them, so each must name what the signed record says (``envelope_mismatch``).
_ENVELOPE_FIELDS: dict[str, dict[str, str]] = {
    "observation": {
        "record_id": "observation_id", "resource_id": "resource_id", "resource_action": "action",
        "capability": "capability", "executor_sovereign_id": "observer_sovereign_id",
    },
    "break_glass": {
        "record_id": "break_glass_id", "resource_id": "resource_id", "resource_action": "resource_action",
        "capability": "capability", "executor_sovereign_id": "executor_sovereign_id",
        "attestation_id": "attestation_id", "outcome": "outcome",
    },
    "judgement": {
        "record_id": "judgement_id", "subject_id": "subject_id", "resource_id": "resource_id",
        "resource_action": "action", "capability": "capability", "outcome": "verdict",
        "matched_evidence_id": "matched_evidence_id",
    },
    "quarantine": {"record_id": "quarantine_id", "resource_id": "resource_id", "outcome": "rejection_code"},
    "registry": {"record_id": "registry_record_id", "outcome": "event"},
    # v1.4.0 (``trust.remediation.entry_index``)
    "remediation": {
        "record_id": "remediation_id", "subject_id": "subject_id", "resource_id": "resource_id",
        "executor_sovereign_id": "executor_sovereign_id", "outcome": "outcome",
    },
    "review": {
        "record_id": "review_id", "subject_id": "subject_id", "resource_id": "resource_id",
        "capability": "capability", "outcome": "verdict",
    },
    # v1.5.0
    "key_succession": {"record_id": "succession_id"},
    "archive": {"record_id": "archive_id"},
}


def _unknown_payload_fields(
    kind: str,
    payload: Any,
    na_public_keys: NAKeys,
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
        if found and isinstance(decision, dict) and signed_as_received("BoundaryDecision", decision,
                                                                       na_keys_at(na_public_keys, None)):
            return found, unsigned
        return [], unsigned + found
    model = _PAYLOAD_MODELS.get(kind)
    found = unknown_fields(model, payload) if model else []
    if not found or model is None:
        return [], []
    if kind in _KEY_SIGNED_KINDS:
        sig = payload.get("signature")
        key = executor_keys.get(str(sig.get("key_id"))) if isinstance(sig, dict) else None
        keys = [key.public_key] if key is not None else []
    else:
        keys = na_keys_at(na_public_keys, None)
        if kind == "key_succession" and isinstance(na_public_keys, NAKeyHistory) and na_public_keys.root_public_key:
            keys.append(na_public_keys.root_public_key)
    return (found, []) if signed_as_received(model, payload, keys) else ([], found)


def _utc(value: datetime) -> datetime:
    """A timestamp without an offset is read as UTC, as every SDK reads it (v1.3.1: it raised TypeError)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _received_digest(model: str, payload: dict[str, Any]) -> str:
    """SHA-256 of a record's signed form as received (v1.3.1), unknown fields set aside.

    What every SDK hashes for a chain link; equal to the model's ``digest()``
    for a record in canonical form.
    """
    from ..models.canonical_registry import received_canonical, without_unknown_fields

    body = received_canonical(model, without_unknown_fields(model, payload))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _verify_payload(
    event: EvidenceEvent,
    result: EvidenceVerification,
    na_public_keys: NAKeys,
    executor_keys: dict[str, ExecutorKey],
) -> Any:
    """Verify one payload's signature; return the parsed model (or None).

    v1.5.0: an NA signature must be made by the key valid at the entry's
    ``recorded_at`` (the NA's key history); a signature by another key of the
    history is ``na_key_not_valid_at_time``.
    """
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
    from ..models import audit_pack as pack
    from ..models import key_succession as ks
    from ..models import out_of_band as oob
    from ..models import remediation as rem

    stage2: dict[str, Any] = {
        "observation": oob.ObservationRecord, "break_glass": oob.BreakGlassRecord,
        "judgement": oob.JudgementRecord, "quarantine": oob.QuarantineRecord, "registry": oob.RegistryRecord,
        "remediation": rem.RemediationRecord, "review": rem.ReviewRecord,
        "key_succession": ks.KeySuccessionRecord, "archive": pack.ArchiveRecord,
    }
    try:
        if kind == "decision":
            model: Any = BoundaryDecision.model_validate(event.payload["decision"])
        elif kind == "justification":
            model = JustificationProof.model_validate(event.payload)
        elif kind == "execution":
            model = ExecutionEvidence.model_validate(event.payload)
        elif kind in stage2:
            model = stage2[kind].model_validate(event.payload)
        else:
            model = RetentionCheckpoint.model_validate(event.payload)
    except (ValueError, KeyError, TypeError):
        result.fail(entry.store_sequence, "payload_invalid")
        return None
    if kind == "key_succession":
        _check_succession_entry(entry.store_sequence, model, event.payload, result, na_public_keys)
        return model
    sig = model.signature
    if kind in _KEY_SIGNED_KINDS:
        # The key must belong to the record's sovereign and sign for its role (v1.3.0).
        # v1.4.0: a remediation record is signed by an executor key, as execution evidence is.
        sovereign = model.observer_sovereign_id if kind == "observation" else model.executor_sovereign_id
        role = "observer" if kind == "observation" else "executor"
        key = executor_keys.get(sig.key_id) if sig is not None else None
        keys = [key.public_key] if key is not None and key.executor_sovereign_id == sovereign \
            and key.role == role else []
        all_keys = keys
    else:
        keys = na_keys_at(na_public_keys, _utc(entry.recorded_at))
        all_keys = na_keys_at(na_public_keys, None)
    ok = sig is not None and any(verify_model_signature(model, sig, k) for k in keys)
    # v1.3.0: the signature must cover the record as received, in the form the reference
    # writes, as every SDK verifier checks it: a record rewritten into another spelling of
    # the same values (a timestamp's offset) is not the record that was signed.
    # v1.3.1: also when it carries fields outside its signature: those are set aside and the
    # part the signer signed is checked as received (1.3.0 skipped the check for such a record).
    model_name = "BoundaryDecision" if kind == "decision" else _PAYLOAD_MODELS.get(kind)
    raw = event.payload.get("decision") if kind == "decision" else event.payload
    if model_name is not None and isinstance(raw, dict) and sig is not None:
        from ..models.canonical_registry import strict_refusal, without_unknown_fields

        refusal = strict_refusal(model_name, without_unknown_fields(model_name, raw) if unsigned else raw, all_keys)
        if refusal is not None:
            result.fail(entry.store_sequence, "invalid_signature" if refusal == "unknown_field" else refusal, kind)
            return model
    if not ok:
        # v1.5.0: signed by a key of the NA's history, but not the one valid at the record's time.
        late = sig is not None and any(verify_model_signature(model, sig, k) for k in all_keys if k not in keys)
        result.fail(entry.store_sequence, "na_key_not_valid_at_time" if late else "invalid_signature", kind)
    return model


def _check_succession_entry(
    seq: int, model: Any, raw: dict[str, Any], result: EvidenceVerification, na_public_keys: NAKeys,
) -> None:
    """v1.5.0: a key succession entry is signed by its outgoing key, an NA key; given the NA's key
    history with its root key, it is one of the history's successions and the root key signed it."""
    from ..crypto import verify_signature
    from ..models.canonical_registry import strict_refusal

    body = model.to_canonical_json().encode("utf-8")

    def signed_by(public_key: str) -> bool:
        return any(verify_signature(body, s.sig, public_key) for s in model.signatures)

    history = na_public_keys if isinstance(na_public_keys, NAKeyHistory) else None
    keys = na_keys_at(na_public_keys, None)
    root = history.root_public_key if history is not None else None
    refusal = strict_refusal("KeySuccessionRecord", raw, [*keys, *([root] if root else [])])
    if refusal is not None:
        result.fail(seq, "invalid_signature" if refusal == "unknown_field" else refusal, "key_succession")
        return
    if model.previous_public_key not in keys or not signed_by(model.previous_public_key):
        result.fail(seq, "invalid_signature", "key_succession")
        return
    if root is not None and not signed_by(root):
        result.fail(seq, "succession_invalid_root_signature", model.succession_id)
        return
    if root is not None and history is not None \
            and model.digest() not in {s.digest() for s in history.successions}:
        result.fail(seq, "succession_not_in_history", model.succession_id)


def verify_evidence_events(
    events: Iterable[EvidenceEvent],
    *,
    na_public_keys: NAKeys,
    executor_keys: dict[str, ExecutorKey],
    contiguous: bool = True,
    checkpoint: RetentionCheckpoint | None = None,
    prior: Sequence[EvidenceEvent] | None = None,
) -> EvidenceVerification:
    """Verify stored entries: envelopes, store chain, signatures and chains.

    ``contiguous`` asserts the events are an unbroken run of the store (an
    export or the whole store); for a filtered history (one resource or vendor)
    set it False: store links are then checked only between adjacent
    positions.  ``checkpoint`` supplies resource heads for chains whose early
    records were removed by retention; since 1.3.1 its NA signature must
    verify, as every SDK checks it, or nothing else is checked.

    A run that starts at entry 1, or right after ``checkpoint``, holds each
    chain from its start. A run that starts anywhere else (a later export
    page, an export since a position) takes the first record it holds of
    each resource as that chain's start (v1.3.1, as for observations since
    1.3.0).

    v1.3.1, records of changes made outside the controlled path and the store
    itself (``docs/reference/evidence-event-schema.md``):

    * a record's ID appears once per kind (``duplicate_record``): a copied
      entry is a replay, not a second record;
    * a Stage 2 entry's envelope names what its payload says
      (``envelope_mismatch``, every field ``_ENVELOPE_FIELDS`` lists);
    * a judgement's matched record is in the run when the run starts at entry
      1 (``judgement_match_missing``), as its subject is when the run reaches
      back to the subject's position (``judgement_subject_missing``);
    * a retention checkpoint removed as many entries as positions
      (``retention_count_mismatch``), checked against the checkpoint before it
      when the run holds that one, or from entry 1 when there is none.

    v1.4.0, remediations and reviews:

    * one remediation per judgement or decision (``duplicate_remediation``);
      it names its judgement's resource (``remediation_subject_mismatch``);
      in a run from its start (entry 1, or right after the retention
      checkpoint) its subject and its forward rotation's execution evidence
      are held before it (``remediation_subject_missing``,
      ``remediation_rotation_missing``; retention keeps a remediation with
      its subject); it names its judgement's change and the version that
      change made (``remediation_subject_mismatch``); the rotation is of the
      same resource (``remediation_rotation_mismatch``), by the remediation's
      own executor sovereign (``remediation_rotation_other_executor``), made
      after the change (``remediation_rotation_before_change``) and cited by
      no earlier remediation (``remediation_rotation_reused``);
    * a review's embedded admin requests verify offline
      (``review_approval_invalid``), with the public key the holder registry
      records for each operator key when the run holds it
      (``review_approval_key_mismatch``); its decider is a second holder
      (``review_same_holder``); it names its subject's digest
      (``review_subject_mismatch``; ``review_subject_missing`` in a run from
      its start); and no waiver follows a recorded remediation
      (``review_waiver_after_remediation``).

    v1.5.0, key succession and audit packs:

    * ``na_public_keys`` may be the NA's key history: an NA signature must be
      made by the key valid at the entry's ``recorded_at``
      (``na_key_not_valid_at_time`` for another key of the history);
    * a ``key_succession`` entry is signed by its outgoing key and, given a
      history with its root key, is one of the history's successions signed by
      the root key (``succession_invalid_root_signature``,
      ``succession_not_in_history``); an ``archive`` entry is NA-signed;
    * ``prior`` (an audit pack's cited records, outside the run) seeds what
      the run's records rest on: their decisions, subjects and matched
      records, and the heads of the chains the run continues. They are
      verified for authenticity (signatures, digests) but not as a run; the
      run then holds every chain from its start, and a record it cites that
      neither holds is ``cited_record_missing``.
    """
    result = EvidenceVerification()
    if checkpoint is not None and not verify_retention_checkpoint(checkpoint, na_public_keys):
        result.fail(None, "invalid_signature", "retention_checkpoint")
        return result
    prev: EvidenceStoreEntry | None = None
    prev_digest: str | None = None
    decisions: dict[str, BoundaryDecision] = {}
    contexts: dict[str, ContextRecord] = {}
    last_exec: dict[str, tuple[ExecutionEvidence, str]] = {}
    resource_heads: dict[str, ResourceHeadState] = {}
    if checkpoint is not None:
        resource_heads = {
            rid: ResourceHeadState(h.resource_sequence, h.record_digest)
            for rid, h in checkpoint.resource_heads.items()
        }
    # v1.3.0: observation positions per resource, judged records, matched evidence.
    observation_heads: dict[str, int] = dict((checkpoint.observation_heads or {}) if checkpoint else {})
    # v1.3.1: judgement subjects and judged records by kind and ID.
    subjects: dict[tuple[str, str], tuple[str, int]] = {}
    judged: set[tuple[str, str]] = set()
    matched: set[str] = set()
    not_decisions: set[str] = set()
    # v1.3.1: the record IDs seen per kind, the records a judgement can match,
    # and the retention checkpoints seen.
    record_ids: dict[str, set[str]] = {}
    matchable: set[str] = set()
    checkpoints: dict[str, RetentionCheckpoint] = {}
    # v1.4.0: judgements and decisions by ID (payload digest, resource), execution evidence's
    # resources, remediated subjects, and operator keys as the holder registry records them.
    judged_records: dict[str, _Subject] = {}
    executed: dict[str, _Execution] = {}
    remediated: set[str] = set()
    # v1.4.0 review fixes: the version each observation or break-glass record names, and the
    # forward rotations remediations already cite.
    versions: dict[tuple[str, str], str | None] = {}
    cited: set[str] = set()
    operator_keys: dict[str, list[tuple[datetime, str | None, str | None]]] = {}
    first_sequence: int | None = None
    from_start = False
    # v1.5.0: with ``prior`` (an audit pack's cited records) every record the run cites is supplied,
    # and the chains continue from the records it holds.
    pack = prior is not None

    def visit(event: EvidenceEvent, result: EvidenceVerification, cited_run: bool) -> None:
        nonlocal prev, prev_digest, first_sequence, from_start
        entry = event.entry
        digest = event.received_entry_digest()
        result.checked_entries += 1
        if digest != event.entry_digest:
            result.fail(entry.store_sequence, "entry_digest_mismatch")
        if payload_digest(event.payload) != entry.payload_digest:
            result.fail(entry.store_sequence, "payload_digest_mismatch")
        linked = contiguous and not cited_run
        if prev is not None and (linked or entry.store_sequence == prev.store_sequence + 1):
            if entry.store_sequence != prev.store_sequence + 1:
                result.fail(entry.store_sequence, "store_sequence_gap")
            elif entry.prev_entry_digest != prev_digest:
                result.fail(entry.store_sequence, "store_chain_break")
        elif prev is None and checkpoint is not None and entry.store_sequence == checkpoint.removed_through_sequence + 1:
            if entry.prev_entry_digest != checkpoint.last_removed_entry_digest:
                result.fail(entry.store_sequence, "store_chain_break", "does not continue from the checkpoint")
        if first_sequence is None and not cited_run:
            first_sequence = entry.store_sequence
            from_start = pack or entry.store_sequence == 1 or (
                checkpoint is not None and entry.store_sequence == checkpoint.removed_through_sequence + 1
            )
        prev, prev_digest = entry, digest
        if entry.entry_kind not in _KNOWN_ENTRY_KINDS:
            # v1.2.0: a kind from a later release; its envelope still chains.
            result.fail(entry.store_sequence, "unknown_entry_kind", entry.entry_kind)
            return

        failed_before = len(result.failures)
        model = _verify_payload(event, result, na_public_keys, executor_keys)
        if model is None:
            return
        authentic = len(result.failures) == failed_before
        record_id = str(getattr(model, _RECORD_ID[entry.entry_kind]))
        seen = record_ids.setdefault(entry.entry_kind, set())
        if record_id in seen:
            result.fail(entry.store_sequence, "duplicate_record", f"{entry.entry_kind} {record_id}")
        seen.add(record_id)
        expected_envelope = _ENVELOPE_FIELDS.get(entry.entry_kind)
        if expected_envelope is not None:
            wrong = [f for f, source in expected_envelope.items() if getattr(entry, f) != getattr(model, source)]
            if wrong:
                result.fail(entry.store_sequence, "envelope_mismatch", f"{entry.entry_kind}: {', '.join(wrong)}")
        # Checks that need a record's predecessors in the run; a pack's cited records are not a run.
        chained = not cited_run
        if entry.entry_kind == "decision":
            result.decisions += 1
            decisions[model.decision_id] = model
            judged_records[model.decision_id] = _Subject(entry.payload_digest, None)
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
                elif not (_utc(decision.decision_made_at) <= _utc(ev.executed_at)
                          <= _utc(decision.decision_valid_until)):
                    result.fail(entry.store_sequence, "evidence_outside_decision_window")
                elif ctx is not None and ev.executed_capability != ctx.requested_capability:
                    result.fail(entry.store_sequence, "evidence_capability_mismatch")
            elif pack and chained:
                # v1.5.0: a pack holds the decision every execution in its range rests on.
                result.fail(entry.store_sequence, "cited_record_missing", f"decision {ev.decision_id}")
            if ev.decision_id in not_decisions:
                # v1.3.0: execution evidence never rests on a judgement or a record of one.
                result.fail(entry.store_sequence, "evidence_cites_judgement", ev.decision_id)
            # v1.3.1: the chains link to each record as received, as every SDK hashes it.
            received = _received_digest("ExecutionEvidence", event.payload)
            before, before_digest = last_exec.get(ev.decision_id, (None, None))
            expected_seq = before.sequence_no + 1 if before else None
            if chained and before is not None and (
                    ev.sequence_no != expected_seq or ev.prev_evidence_digest != before_digest):
                result.fail(entry.store_sequence, "evidence_chain_break")
            elif chained and before is None and decision is not None and (
                    ev.sequence_no != 1 or ev.prev_evidence_digest is not None):
                result.fail(entry.store_sequence, "evidence_chain_break")
            last_exec[ev.decision_id] = (ev, received)
            matchable.add(ev.evidence_id)
            executed[ev.evidence_id] = _Execution(ev.resource_id, entry.store_sequence, _utc(ev.executed_at),
                                                  ev.executor_sovereign_id, ev.decision_id)
            if ev.resource_id is not None:
                head = resource_heads.get(ev.resource_id)
                # v1.3.1: a run that does not start at entry 1 or right after the checkpoint
                # takes the first record it holds of a resource as that chain's start.
                if chained and (head is not None or from_start):
                    exp = head.resource_sequence + 1 if head else 1
                    if ev.resource_sequence != exp or ev.prev_resource_digest != (head.record_digest if head else None):
                        result.fail(entry.store_sequence, "resource_chain_break", ev.resource_id)
                resource_heads[ev.resource_id] = ResourceHeadState(ev.resource_sequence or 0, received)
        elif entry.entry_kind == "retention_checkpoint":
            # v1.3.1: a checkpoint signed over a store missing entries removed fewer than it says.
            cp: RetentionCheckpoint = model
            earlier = checkpoints.get(cp.previous_checkpoint_id) if cp.previous_checkpoint_id else None
            if cp.previous_checkpoint_id is None or earlier is not None:
                start = earlier.removed_through_sequence if earlier is not None else 0
                if cp.removed_count != cp.removed_through_sequence - start:
                    result.fail(entry.store_sequence, "retention_count_mismatch",
                                f"removed {cp.removed_count} of {cp.removed_through_sequence - start} entries "
                                f"after #{start} through #{cp.removed_through_sequence}")
            checkpoints[cp.checkpoint_id] = cp
        elif entry.entry_kind in ("observation", "break_glass"):
            subjects[(entry.entry_kind, record_id)] = (entry.payload_digest, entry.store_sequence)
            version = model.version_id if entry.entry_kind == "observation" \
                else model.execution_parameters.get("version_id")
            versions[(entry.entry_kind, record_id)] = version if isinstance(version, str) and version else None
            not_decisions.add(record_id)
            if entry.entry_kind == "observation":
                result.observations += 1
                rid = model.resource_id
                position = entry.observation_sequence
                if chained and (rid in observation_heads or from_start):
                    if position != observation_heads.get(rid, 0) + 1:
                        result.fail(entry.store_sequence, "observation_chain_break", rid)
                observation_heads[rid] = position or observation_heads.get(rid, 0)
            else:
                result.break_glass += 1
                matchable.add(record_id)
        elif entry.entry_kind == "judgement":
            result.judgements += 1
            not_decisions.add(model.judgement_id)
            judged_records[model.judgement_id] = _Subject(
                entry.payload_digest, model.resource_id, model.subject_kind, model.subject_id,
                model.subject_store_sequence, _utc(model.evaluated_as_of))
            key = (model.subject_kind, model.subject_id)
            if key in judged:
                result.fail(entry.store_sequence, "duplicate_judgement", model.subject_id)
            judged.add(key)
            subject = subjects.get(key)
            if subject is not None:
                if subject != (model.subject_digest, model.subject_store_sequence):
                    result.fail(entry.store_sequence, "judgement_subject_mismatch", model.subject_id)
            elif chained and contiguous and first_sequence is not None \
                    and model.subject_store_sequence >= first_sequence:
                result.fail(entry.store_sequence, "judgement_subject_missing", model.subject_id)
            elif pack and chained:
                result.fail(entry.store_sequence, "cited_record_missing", f"{model.subject_kind} {model.subject_id}")
            if model.matched_evidence_id is not None:
                if model.matched_evidence_id in matched:
                    result.fail(entry.store_sequence, "match_reused", model.matched_evidence_id)
                matched.add(model.matched_evidence_id)
                # v1.3.1: the NA matches a record it already holds, so a run from entry 1 holds it.
                if chained and contiguous and first_sequence == 1 and model.matched_evidence_id not in matchable:
                    result.fail(entry.store_sequence, "judgement_match_missing", model.matched_evidence_id)
                elif pack and chained and model.matched_evidence_id not in matchable:
                    result.fail(entry.store_sequence, "cited_record_missing",
                                f"matched record {model.matched_evidence_id}")
        elif entry.entry_kind == "quarantine":
            result.quarantined += 1
            if payload_digest(model.record) != model.record_digest:
                result.fail(entry.store_sequence, "quarantine_digest_mismatch")
        elif entry.entry_kind == "registry":
            # v1.4.0 review fixes: only a registry record the NA signed binds an operator key.
            if authentic and model.event == "operator_key_holder" and model.key_id is not None:
                operator_keys.setdefault(model.key_id, []).append(
                    (_utc(model.effective_at), model.public_key, model.holder))
        elif entry.entry_kind == "remediation":
            result.remediations += 1
            not_decisions.add(model.remediation_id)
            _check_remediation_entry(entry.store_sequence, model, result, judged_records, executed, remediated,
                                     versions, cited, held_from_start=chained and contiguous and from_start)
        elif entry.entry_kind == "review":
            result.reviews += 1
            not_decisions.add(model.review_id)
            _check_review_entry(entry.store_sequence, model, result, judged_records, remediated, operator_keys,
                                na_keys_at(na_public_keys, None), held_from_start=chained and contiguous and from_start)
        elif entry.entry_kind == "key_succession":
            result.key_successions += 1
        elif entry.entry_kind == "archive":
            result.archives += 1

    if prior is not None:
        # The cited records first, in store order: their failures fail the run, their counts do not count.
        cited_result = EvidenceVerification()
        for event in sorted(prior, key=lambda e: e.entry.store_sequence):
            visit(event, cited_result, True)
        for failure in cited_result.failures:
            result.fail(failure["store_sequence"], failure["reason"], f"cited {failure['detail']}".rstrip())
        result.warnings.extend(cited_result.warnings)
        prev, prev_digest = None, None
    for event in events:
        visit(event, result, False)
    return result


@dataclass(frozen=True)
class _Subject:
    """What a remediation or review checks of its judgement or decision (v1.4.0)."""

    digest: str
    resource_id: str | None
    change_kind: str | None = None
    change_id: str | None = None
    change_sequence: int | None = None
    changed_at: datetime | None = None


@dataclass(frozen=True)
class _Execution:
    """What a remediation checks of execution evidence (v1.4.0)."""

    resource_id: str | None
    store_sequence: int
    executed_at: datetime
    executor_sovereign_id: str
    decision_id: str


def _check_remediation_entry(
    seq: int, model: Any, result: EvidenceVerification, judged: dict[str, _Subject],
    executed: dict[str, _Execution], remediated: set[str], versions: dict[tuple[str, str], str | None],
    cited: set[str], *, held_from_start: bool,
) -> None:
    """v1.4.0: one remediation per subject, of its subject's change and resource, after a forward
    rotation of its own made after the change and cited once."""
    from .remediation import rotation_problem

    if model.subject_id in remediated:
        result.fail(seq, "duplicate_remediation", model.subject_id)
    remediated.add(model.subject_id)
    subject = judged.get(model.subject_id)
    change_sequence: int | None = None
    changed_at: datetime | None = None
    if subject is None:
        if held_from_start:
            result.fail(seq, "remediation_subject_missing", model.subject_id)
    elif model.subject_kind == "judgement":
        version = versions.get((model.change_kind, model.change_id))
        if subject.resource_id != model.resource_id or (model.change_kind, model.change_id) != (
                subject.change_kind, subject.change_id) or (
                model.disabled_version_id is not None and version is not None and model.disabled_version_id != version):
            result.fail(seq, "remediation_subject_mismatch", model.subject_id)
        change_sequence, changed_at = subject.change_sequence, subject.changed_at
    elif model.change_id != model.subject_id:
        # A decision's change is its execution evidence (or, never executed, the decision itself).
        change = executed.get(model.change_id)
        if model.change_kind != "execution" or (change is not None and (
                change.decision_id != model.subject_id or change.resource_id != model.resource_id)):
            result.fail(seq, "remediation_subject_mismatch", model.subject_id)
        elif change is not None:
            change_sequence, changed_at = change.store_sequence, change.executed_at
    rotation = model.rotation_evidence_id
    if rotation is not None:
        held = executed.get(rotation)
        if held is not None:
            if held.resource_id != model.resource_id:
                result.fail(seq, "remediation_rotation_mismatch", rotation)
            problem = rotation_problem(
                rotation_executor=held.executor_sovereign_id, rotation_sequence=held.store_sequence,
                rotation_executed_at=held.executed_at, record_executor=model.executor_sovereign_id,
                change_sequence=change_sequence, changed_at=changed_at, already_cited=rotation in cited)
            if problem is not None:
                result.fail(seq, problem[0], rotation)
        elif held_from_start:
            result.fail(seq, "remediation_rotation_missing", rotation)
        elif rotation in cited:
            result.fail(seq, "remediation_rotation_reused", rotation)
        cited.add(rotation)


def _check_review_entry(
    seq: int, model: Any, result: EvidenceVerification, judged: dict[str, _Subject],
    remediated: set[str], operator_keys: dict[str, list[tuple[datetime, str | None, str | None]]],
    na_public_keys: Sequence[str], *, held_from_start: bool,
) -> None:
    """v1.4.0: a review's approvals verify offline, from a second holder, on the subject it names."""
    from .remediation import review_approval_problem, review_holder_problem

    problem = review_approval_problem(model, na_public_keys)
    if problem is not None:
        result.fail(seq, "review_approval_invalid", problem)
    for key_id, approval, holder, at in (
        (model.decided_by, model.approval, model.decider_holder, model.decided_at),
        (model.requested_by, model.request_approval, model.requester_holder, model.requested_at),
    ):
        if key_id is None or approval is None or key_id not in operator_keys:
            continue
        recorded = [r for r in operator_keys[key_id] if r[0] <= _utc(at)]
        latest = max(recorded, key=lambda r: r[0]) if recorded else None
        if latest is None or latest[1] != approval.public_key or latest[2] != holder:
            result.fail(seq, "review_approval_key_mismatch", key_id)
    if review_holder_problem(decided_by=model.decided_by, decider_holder=model.decider_holder,
                             requested_by=model.requested_by, requester_holder=model.requester_holder,
                             actor=model.actor, actor_holder=model.actor_holder) is not None:
        result.fail(seq, "review_same_holder", model.decided_by)
    subject = judged.get(model.subject_id)
    if subject is None:
        if held_from_start:
            result.fail(seq, "review_subject_missing", model.subject_id)
    elif subject.digest != model.subject_digest:
        result.fail(seq, "review_subject_mismatch", model.subject_id)
    if model.verdict == "waive_until" and model.subject_id in remediated:
        result.fail(seq, "review_waiver_after_remediation", model.subject_id)


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
    na_public_keys: NAKeys | None,
    sovereign_id: str | None = None,
) -> AnchorVerification:
    """Verify a run of anchors: signatures, the anchor chain and monotonic heads.

    ``anchors`` must be ordered by ``anchor_sequence`` and need not start at 1
    (an auditor may hold only recent anchors); a run that starts at 1 must
    start with no previous anchor. ``sovereign_id`` pins whose anchors these
    are. ``na_public_keys=None`` skips the signatures (a database check
    without the NA key) and checks everything else. v1.5.0: given the NA's key
    history, each anchor must be signed by the key valid at its ``anchored_at``
    (``na_key_not_valid_at_time`` for another key of the history).
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
        keys = na_keys_at(na_public_keys, _utc(anchor.anchored_at)) if na_public_keys is not None else []
        if na_public_keys is not None and (
            sig is None or not any(verify_model_signature(anchor, sig, k) for k in keys)
        ):
            late = sig is not None and any(verify_model_signature(anchor, sig, k)
                                           for k in na_keys_at(na_public_keys, None) if k not in keys)
            result.fail(n, "na_key_not_valid_at_time" if late else "anchor_invalid_signature")
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
    return _starting_checkpoint(events, first) is not None


def _starting_checkpoint(events: Sequence[EvidenceEvent], first: EvidenceEvent) -> RetentionCheckpoint | None:
    for event in events:
        if event.entry.entry_kind != "retention_checkpoint":
            continue
        try:
            cp = RetentionCheckpoint.model_validate(event.payload)
        except ValueError:
            continue
        if (cp.removed_through_sequence == first.entry.store_sequence - 1
                and cp.last_removed_entry_digest == first.entry.prev_entry_digest):
            return cp
    return None


def export_checkpoint(events: Sequence[EvidenceEvent]) -> RetentionCheckpoint | None:
    """The retention checkpoint in an export that explains where it starts, or None.

    An export of a store after retention starts right after what was
    removed; its chains continue from the checkpoint's resource and
    observation positions, so pass it to ``verify_evidence_events``. The
    checkpoint is itself an entry of the export, verified with the rest.
    """
    if not events:
        return None
    return _starting_checkpoint(events, min(events, key=lambda e: e.entry.store_sequence))


def check_events_against_anchors(
    events: Sequence[EvidenceEvent],
    anchors: Sequence[StoreAnchor],
    result: EvidenceVerification,
    *,
    partial: bool = False,
    from_anchor: bool = False,
) -> None:
    """Check a contiguous run of entries against anchors held out of band.

    The run must be tied to the anchors at both ends:

    * its start: the run starts at entry 1, or right after a retention
      checkpoint recorded in the run (whose signature and count the event
      verification checks). With ``from_anchor`` (v1.3.1), also right after a
      held anchor whose digest its first entry names: an export since an
      anchored position, which says nothing of the entries before it. Without
      it such a run is not tied (1.2 and 1.3.0 accepted it, so a store whose
      entries through an anchored one were deleted still verified). A run
      that is not tied while anchors are held leaves entries before it
      unaccounted for (``export_not_linked_to_anchors``);
    * its end: an anchor after the run's last entry means the run stops short
      of history the anchors prove exists (``export_ends_before_anchor``).

    ``partial`` accepts a deliberate slice and skips both ends. Inside the run,
    each anchor must name its entry's digest as received; because entries are
    hash-linked, a match covers every earlier entry of the run.
    """
    by_sequence = {e.entry.store_sequence: e for e in events}
    ordered = sorted(events, key=lambda e: e.entry.store_sequence)
    first = ordered[0] if ordered else None
    last_seq = ordered[-1].entry.store_sequence if ordered else None
    first_seq = first.entry.store_sequence if first else None
    matched = before = beyond = 0
    anchored_through: int | None = None
    linked_start = first is not None and (first_seq == 1 or _checkpoint_start(ordered, first))
    after_anchor: int | None = None
    for anchor in anchors:
        seq = anchor.store_sequence
        if first is None or last_seq is None or first_seq is None or seq > last_seq:
            beyond += 1
            continue
        if seq == first_seq - 1:
            if first.entry.prev_entry_digest == anchor.entry_digest:
                after_anchor = anchor.anchor_sequence
                linked_start = linked_start or from_anchor
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
        elif event.entry_digest != anchor.entry_digest or event.received_entry_digest() != anchor.entry_digest:
            result.fail(seq, "anchor_mismatch", f"anchor {anchor.anchor_sequence}")
        else:
            matched += 1
            anchored_through = max(anchored_through or 0, seq)
    # A held anchor commits to every entry before the one it names, so a run
    # that is not tied at its start (entry 1, a checkpoint in the run, or a
    # held anchor the caller says it continues from) leaves entries the anchors
    # prove exist unaccounted for, whether the anchors fall before the run or
    # inside it (fixed in 1.3.0: only anchors before the run were counted).
    if anchors and first is not None and not linked_start and not partial:
        if after_anchor is not None:
            why = (f"the export starts right after held anchor {after_anchor}, which proves the entries "
                   f"before it existed, not that they are kept: export from entry 1 (with the retention "
                   f"checkpoint that removed entries, if any), or verify it as an export since that anchor "
                   f"(--from-anchor)")
        else:
            why = (f"the export starts at entry {first_seq} and holds neither entry 1 nor the retention "
                   f"checkpoint that removed the entries before it ({before} held anchor(s) before it): "
                   f"export from entry 1, or include that checkpoint's entry")
        result.fail(first_seq, "export_not_linked_to_anchors", why)
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


#: v1.3.1: the envelope of an export line as every SDK reads it.
_ENVELOPE_NULLABLE_STRINGS = (
    "prev_entry_digest", "decision_id", "context_id", "vendor_id", "attestation_id", "capability", "outcome",
    "evidence_id", "executor_sovereign_id", "resource_id", "resource_action",
)
_ENVELOPE_ABSENT_STRINGS = ("record_id", "subject_id", "matched_evidence_id")
_EVENT_KEYS = frozenset({"schema", "schema_version", "entry", "entry_digest", "payload"})
_ENVELOPE_KEYS = frozenset({
    "store_sequence", "entry_kind", "recorded_at", "payload_digest", "exec_sequence_no", "resource_sequence",
    "observation_sequence", *_ENVELOPE_NULLABLE_STRINGS, *_ENVELOPE_ABSENT_STRINGS,
})
#: JavaScript's safe integers: what every SDK reads as an integer exactly.
_MAX_SAFE_INTEGER = 2**53 - 1
_RECEIVED_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,6})?(?:Z|[+-]([0-9]{2}):([0-9]{2}))?"
)


def _safe_integer(value: Any, minimum: int | None = None) -> bool:
    return type(value) is int and abs(value) <= _MAX_SAFE_INTEGER and (minimum is None or value >= minimum)


def _received_timestamp(value: Any) -> bool:
    match = _RECEIVED_TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return False
    year, month, day, hour, minute, second, zone_h, zone_m = match.groups()
    if zone_h is not None and (int(zone_h) > 23 or int(zone_m) > 59):
        return False
    try:
        datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
    except ValueError:
        return False
    return True


def _valid_event(data: Any) -> bool:
    """Whether an export line is a ``gm.evidence.event`` as every SDK reads it (v1.3.1).

    Exactly the event's five fields; ``schema_version`` the integer 1; an
    envelope with exactly its fields: every 1.2 search field present as a
    string or null, ``store_sequence`` a positive integer and the sequence
    numbers integers (within 2**53 - 1), ``recorded_at`` an ISO 8601
    timestamp (``YYYY-MM-DDTHH:MM:SS``, up to six fraction digits, ``Z`` or an
    offset), and the 1.3.0 fields absent, null or of their type.
    """
    if not isinstance(data, dict) or set(data) != _EVENT_KEYS:
        return False
    entry = data["entry"]
    if (data["schema"] != "gm.evidence.event" or not _safe_integer(data["schema_version"])
            or data["schema_version"] != 1 or not isinstance(data["entry_digest"], str)
            or not isinstance(data["payload"], dict)
            or not isinstance(entry, dict) or not set(entry) <= _ENVELOPE_KEYS):
        return False
    return (
        all(k in entry and (entry[k] is None or isinstance(entry[k], str)) for k in _ENVELOPE_NULLABLE_STRINGS)
        and all(entry.get(k) is None or isinstance(entry[k], str) for k in _ENVELOPE_ABSENT_STRINGS)
        and _safe_integer(entry.get("store_sequence"), 1)
        and isinstance(entry.get("entry_kind"), str)
        and _received_timestamp(entry.get("recorded_at"))
        and isinstance(entry.get("payload_digest"), str)
        and all(k in entry and (entry[k] is None or _safe_integer(entry[k])) for k in ("exec_sequence_no",
                                                                                      "resource_sequence"))
        and (entry.get("observation_sequence") is None or _safe_integer(entry["observation_sequence"], 1))
    )


def parse_export_lines(lines: Iterable[str]) -> list[EvidenceEvent]:
    """Parse ``gm.evidence.event`` JSON Lines (blank lines ignored).

    v1.2.0: each line is parsed strictly (``genesis_mesh.strict_json``); a
    line every implementation would not read alike raises ``StrictJSONError``.
    v1.3.1: a line that is not an event as every SDK reads it (``_valid_event``:
    a ``store_sequence`` written ``"6"``, a missing search field) raises
    ``ValueError``, and each event keeps the digest of its envelope as received,
    which verification checks (``EvidenceEvent.received``).
    """
    events = []
    for line in lines:
        line = line.strip(" \t\r\n")  # JSON whitespace only, as every SDK trims a line
        if line:
            data = strict_json.loads(line)
            if not _valid_event(data):
                raise ValueError("invalid evidence event envelope or unsupported schema")
            events.append(EvidenceEvent.received(data))
    return events
