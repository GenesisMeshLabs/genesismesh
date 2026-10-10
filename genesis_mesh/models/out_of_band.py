"""Changes made outside the controlled path (v1.3.0, Stage 2).

A governed change has a decision before it and execution evidence after it.
Other changes still happen: someone changes a secret in the cloud console, or
a controller acts while the Network Authority (NA) cannot be reached. This
module holds the records that bring them into the evidence store:

``ObservationRecord`` (entry kind ``observation``)
    A change an observer saw at its source (a cloud audit log, a
    reconciliation run), signed by an observer key. It takes no
    ``resource_sequence``: the controller's own evidence owns that chain.
``BreakGlassRecord`` (entry kind ``break_glass``)
    A change a controller made while evaluation failed transiently (network
    error, timeout, ``5xx``, ``429``), with the justification its caller gave,
    signed by an executor key. Never a way past a DENY.
``JudgementRecord`` (entry kind ``judgement``)
    The NA's one verdict on an observation or a break-glass record, signed by
    the NA: matched to governed execution evidence, or judged after the fact
    under the policies active when the change happened. It has no
    ``authorized`` field, so no verifier can read it as an approval, and
    execution evidence can never cite one.
``QuarantineRecord`` (entry kind ``quarantine``)
    An authentic record the NA refused after the action had already happened,
    kept with the refusal so the change is not lost from the history.
``RegistryRecord`` (entry kind ``registry``)
    Signed history of the NA's own state that judgements depend on: policy
    activations, executor and observer keys, and which holder each operator
    key belongs to.

Canonical forms
---------------
Each record signs its fields except ``signature``, with optional top-level
fields omitted when absent (``to_canonical_json``); nested models keep their
usual form. The forms are frozen from 1.3.0 on, because these records sit in
audit packs for years. Timestamps are UTC.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .boundary_policy import PolicyBinding
from .context import GateResult
from .execution import ResourceAction
from .genesis import Signature

#: How the NA came to know a change (Stage 2): before it, through a decision,
#: or after it, by judging a record of it. Stage 5 adds ``grant``.
GovernedBy = Literal["prior_decision", "after_the_fact"]

#: A judgement's verdict. ``indeterminate``: the NA cannot tell what applied
#: at the time (no policy covered the change, or its history does not reach
#: back that far).
Verdict = Literal["allow", "deny", "indeterminate"]

#: Why a controller broke the glass: evaluation failed in a way a later
#: attempt can overcome. A DENY is never one of them.
EvaluationFailure = Literal["network_error", "timeout", "server_error", "rate_limited"]

#: What a registry record records.
RegistryEvent = Literal[
    "policy_history_started",
    "policy_activated",
    "policy_deactivated",
    "executor_key_registered",
    "executor_key_retired",
    "operator_key_holder",
]

#: Roles a registered key signs for (v1.3.0): execution evidence and
#: break-glass records, or observations.
KeyRole = Literal["executor", "observer"]


def _canonical(data: Any) -> str:
    import json

    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _utc(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC timestamp")
    return value


class _SignedRecord(BaseModel):
    """Shared canonical form: every field but ``signature``, absent optionals omitted."""

    model_config = ConfigDict(extra="forbid")

    def _fields(self, *, signature: bool) -> dict[str, Any]:
        # Absent optional fields are left out at the top level only: a nested
        # model (a judgement's PolicyBinding) keeps the form it has everywhere.
        data = self.model_dump(exclude=None if signature else {"signature"}, mode="json")
        return {k: v for k, v in data.items() if v is not None}

    def to_canonical_json(self) -> str:
        """Canonical form the signer signs: ``signature`` excluded, absent optional fields omitted."""
        return _canonical(self._fields(signature=False))

    def to_wire(self) -> dict[str, Any]:
        """The JSON form submitted, stored and exported: the canonical fields plus the signature."""
        return self._fields(signature=True)

    def digest(self) -> str:
        """SHA-256 of the canonical form."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()

    @field_validator("*", mode="after")
    @classmethod
    def _timestamps_are_utc(cls, value: Any, info: Any) -> Any:
        if isinstance(value, datetime):
            _utc(value, info.field_name)
        return value


class ObservationRecord(_SignedRecord):
    """A change seen at its source, signed by an observer key (v1.3.0).

    ``changed_at`` is when the source says the change happened. A
    reconciliation finding, which knows only that the resource changed
    between two scans, gives ``changed_not_before`` and ``changed_not_after``
    instead. ``actor`` is recorded as the source reported it, not
    authenticated: use a pseudonymous identifier, never a credential.
    ``metadata`` passes the same guard as execution metadata (field names,
    versions and timestamps, never values).
    """

    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    observer_sovereign_id: str = Field(..., min_length=1, max_length=256)
    resource_id: str = Field(..., min_length=1, max_length=256)
    action: ResourceAction
    capability: str = Field(
        ..., min_length=1, max_length=256,
        description="The capability the change exercises, as a governed action would request it",
    )
    changed_at: datetime | None = None
    changed_not_before: datetime | None = None
    changed_not_after: datetime | None = None
    observed_at: datetime
    actor: str | None = Field(default=None, min_length=1, max_length=256)
    source: str = Field(..., min_length=1, max_length=128, description="Where the change was seen")
    source_event_id: str = Field(..., min_length=1, max_length=256)
    version_id: str | None = Field(
        default=None, min_length=1, max_length=256,
        description="The source's version of the resource after the change; matches execution evidence",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    signature: Signature | None = None

    @model_validator(mode="after")
    def _change_time(self) -> "ObservationRecord":
        window = (self.changed_not_before, self.changed_not_after)
        if self.changed_at is not None:
            if any(w is not None for w in window):
                raise ValueError("give changed_at, or changed_not_before and changed_not_after, not both")
        elif any(w is None for w in window):
            raise ValueError("changed_at, or both changed_not_before and changed_not_after, is required")
        elif window[0] > window[1]:  # type: ignore[operator]
            raise ValueError("changed_not_before is after changed_not_after")
        return self

    @property
    def change_window(self) -> tuple[datetime, datetime]:
        """(earliest, latest) time the change can have happened."""
        if self.changed_at is not None:
            return self.changed_at, self.changed_at
        assert self.changed_not_before is not None and self.changed_not_after is not None
        return self.changed_not_before, self.changed_not_after


class BreakGlassRecord(_SignedRecord):
    """A change a controller made while it could not obtain a decision (v1.3.0).

    Signed by the executor key, with the justification its caller gave and
    the evaluation it attempted (``attestation_id``, ``request_parameters``,
    ``attributes``, and the digest of the request that failed). The NA judges
    it after the fact as that evaluation would have gone at ``executed_at``.
    Only a transient failure (``evaluation_failure``) can lead to one: a
    controller that received a DENY never breaks the glass.
    """

    break_glass_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    executor_sovereign_id: str = Field(..., min_length=1, max_length=256)
    resource_id: str = Field(..., min_length=1, max_length=256)
    resource_action: ResourceAction
    capability: str = Field(..., min_length=1, max_length=256)
    attestation_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_parameters: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    justification: str = Field(..., min_length=1, max_length=1024)
    evaluation_request_digest: str = Field(..., min_length=64, max_length=64)
    evaluation_failure: EvaluationFailure
    executed_at: datetime
    outcome: str = Field(..., description='"success", "failure" or "partial"')
    outcome_detail: str | None = Field(default=None, max_length=1024)
    execution_parameters: dict[str, Any] = Field(default_factory=dict)
    signature: Signature | None = None


class JudgementRecord(_SignedRecord):
    """The NA's verdict on one observation or break-glass record (v1.3.0).

    ``governed_by: prior_decision`` means the change matched recorded
    execution evidence (``matched_evidence_id``, consumed by the match);
    ``after_the_fact`` means the NA evaluated it, as of ``evaluated_as_of``,
    under the policies active then (``policy_binding``, ``gate_results``).
    ``current_verdict`` is the verdict under the policies active when the
    NA judged; when the two differ, ``flagged_for_review`` is set.

    No ``authorized`` field, deliberately: a judgement records what the NA
    concluded about a change that already happened, never permission for one.
    """

    judgement_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    subject_kind: Literal["observation", "break_glass"]
    subject_id: str = Field(..., min_length=1, max_length=128)
    subject_digest: str = Field(..., min_length=64, max_length=64)
    subject_store_sequence: int = Field(..., ge=1)
    resource_id: str = Field(..., min_length=1, max_length=256)
    action: ResourceAction
    capability: str = Field(..., min_length=1, max_length=256)
    governed_by: GovernedBy
    verdict: Verdict
    reason: str | None = Field(default=None, max_length=1024)
    evaluated_as_of: datetime
    evaluated_from: datetime | None = Field(
        default=None, description="Start of the change window, for a change known only within one"
    )
    policy_binding: PolicyBinding | None = None
    gate_results: list[GateResult] = Field(default_factory=list)
    current_verdict: Verdict | None = None
    current_policy_set_digest: str | None = None
    flagged_for_review: bool | None = Field(default=None, description="Present (true) only when flagged")
    matched_evidence_id: str | None = None
    matched_decision_id: str | None = None
    possible_match_evidence_id: str | None = Field(
        default=None, description="Execution evidence that may be this change (no version ID to confirm it)"
    )
    judged_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None


class QuarantineRecord(_SignedRecord):
    """An authentic record the NA refused after its action happened (v1.3.0).

    ``record`` is the signed record exactly as received; ``record_digest`` its
    SHA-256 (canonical JSON). The NA signs the wrapper: the refusal is its
    statement. A record that is not authentic (unsigned, signed by an unknown
    key, malformed) is refused outright and never quarantined.
    """

    quarantine_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    record_kind: Literal["execution", "observation", "break_glass"]
    record: dict[str, Any]
    record_digest: str = Field(..., min_length=64, max_length=64)
    rejection_code: str = Field(..., min_length=1, max_length=128)
    detail: str = Field(default="", max_length=1024)
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)
    quarantined_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None


class RegistryRecord(_SignedRecord):
    """Signed history of the NA state judgements rest on (v1.3.0).

    One record per change: a policy version activated or deactivated, an
    executor or observer key registered or retired, an operator key's
    holder. ``reconstructed`` marks history backfilled from audit events when
    a store was upgraded to 1.3.0; ``policy_history_started`` marks how far
    back the policy history reaches. ``approved_by`` names the second
    holder's privileged key that approved a holder change.
    """

    registry_record_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    event: RegistryEvent
    effective_at: datetime
    reconstructed: bool | None = Field(default=None, description="Present (true) only for backfilled history")
    policy_id: str | None = None
    policy_version: int | None = Field(default=None, ge=1)
    policy_digest: str | None = None
    key_id: str | None = None
    public_key: str | None = None
    executor_sovereign_id: str | None = None
    key_role: KeyRole | None = None
    resource_prefix: str | None = None
    operator_tier: str | None = None
    holder: str | None = None
    approved_by: str | None = None
    recorded_by: str | None = Field(default=None, description="Operator key that made the change")
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None


#: Optional fields each Stage 2 record omits from its signed form when absent.
OUT_OF_BAND_OMIT_WHEN_NONE: dict[str, tuple[str, ...]] = {
    model.__name__: tuple(
        name for name, info in model.model_fields.items()
        if name != "signature" and not info.is_required() and info.default is None
    )
    for model in (ObservationRecord, BreakGlassRecord, JudgementRecord, QuarantineRecord, RegistryRecord)
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
