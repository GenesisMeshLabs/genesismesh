"""Remediation and reviews of changes governed after the fact (v1.4.0, Stage 3).

A change judged DENY after the fact (Stage 2) is cancelled after a grace
window, without breaking what reads it, and its author is told; a second
person can review a judgement, or a decision made under a policy that
requires it, and uphold, deny or waive the change. This module holds the two
records that bring this into the evidence store:

``RemediationRecord`` (entry kind ``remediation``)
    What a controller did about a judged change, signed by the executor key
    that carried it out: ``cancelled`` (a forward rotation then a disable,
    or a disable of something nothing reads yet) or ``alerted`` (the denial
    recorded, nothing changed). Metadata only: the versions it issued and
    disabled, never a value.
``ReviewRecord`` (entry kind ``review``)
    A second person's verdict on a judged change or a decision: ``uphold``,
    ``deny`` or ``waive_until`` (a bounded time). Built and signed by the NA
    when the decision is made, with the decider's signed admin request
    embedded (``AdminApproval``), so the approval verifies offline.

Canonical forms follow the Stage 2 records: every field but ``signature``,
absent optional top-level fields omitted; nested models keep their usual
form. Frozen from 1.4.0 on. Timestamps are UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .genesis import Signature
from .out_of_band import _SignedRecord

#: What a remediation or review is about: a judgement of a change made outside
#: the controlled path, or a decision made under a policy that requires review.
RemediationSubjectKind = Literal["judgement", "decision"]

#: The record of the change a remediation acts on.
ChangeKind = Literal["observation", "break_glass", "execution"]

#: What the controller did. ``rotate_forward_then_disable``: a new version
#: issued under a governed decision first, then the denied version disabled
#: (a versioned resource others read); ``disable`` or ``delete``: a resource
#: nothing reads yet; ``none``: nothing changed (``alerted``).
RemediationSteps = Literal["rotate_forward_then_disable", "disable", "delete", "none"]

RemediationOutcome = Literal["cancelled", "alerted"]

#: A review's verdict on the change: it stands (``uphold``), it does not
#: (``deny``: remediation becomes due), or it stands until a time
#: (``waive_until``: remediation becomes due at that time).
ReviewVerdict = Literal["uphold", "deny", "waive_until"]

#: Why a review was opened: an operator asked for it, the judgement was
#: flagged for review (Stage 2), or the policy requires it.
ReviewOpenedFor = Literal["requested", "flagged_for_review", "review_required"]

#: Longest a waiver may run, whatever the NA's configuration (v1.4.0).
MAX_WAIVER_SECONDS = 90 * 24 * 3600


class AdminApproval(BaseModel):
    """An operator's signed admin request, kept whole (signature version 2, v1.4.0).

    The fields of the canonical payload the operator signed (``method``,
    ``path``, ``query``, ``audience``, ``body``, ``key_id``, ``timestamp``,
    ``nonce``), the base64 signature from ``X-Admin-Signature``, and the
    operator key's public key as the NA held it. ``timestamp`` is kept as sent:
    the signature covers its exact text.
    """

    model_config = ConfigDict(extra="forbid")

    key_id: str = Field(..., min_length=1, max_length=256)
    public_key: str = Field(..., min_length=1, max_length=256)
    method: str = Field(..., min_length=1, max_length=16)
    path: str = Field(..., min_length=1, max_length=2048)
    query: dict[str, list[str]] = Field(default_factory=dict)
    audience: str = Field(..., min_length=1, max_length=256)
    body: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(..., min_length=1, max_length=256)
    nonce: str = Field(..., min_length=1, max_length=256)
    admin_signature: str = Field(..., min_length=1, max_length=256)


class RemediationRecord(_SignedRecord):
    """What a controller did about a judged change, signed by its executor key (v1.4.0).

    ``subject_kind`` / ``subject_id``: the judgement (or the decision) that
    made the remediation due; ``change_kind`` / ``change_id``: the record of
    the change itself (the observation, break-glass record or execution
    evidence). For ``rotate_forward_then_disable``, ``rotation_evidence_id``
    names the execution evidence of the forward rotation (a governed action
    of its own, stored first), ``version_id`` the version it issued and
    ``disabled_version_id`` the denied version disabled after it.
    """

    remediation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    executor_sovereign_id: str = Field(..., min_length=1, max_length=256)
    subject_kind: RemediationSubjectKind
    subject_id: str = Field(..., min_length=1, max_length=128)
    change_kind: ChangeKind
    change_id: str = Field(..., min_length=1, max_length=128)
    resource_id: str = Field(..., min_length=1, max_length=256)
    outcome: RemediationOutcome
    steps: RemediationSteps
    rotation_evidence_id: str | None = Field(default=None, min_length=1, max_length=128)
    version_id: str | None = Field(default=None, min_length=1, max_length=256,
                                   description="The version the forward rotation issued")
    disabled_version_id: str | None = Field(default=None, min_length=1, max_length=256,
                                            description="The version disabled or deleted")
    remediated_at: datetime
    detail: str | None = Field(default=None, min_length=1, max_length=1024)
    signature: Signature | None = None

    @model_validator(mode="after")
    def _steps_match_outcome(self) -> "RemediationRecord":
        if (self.outcome == "alerted") != (self.steps == "none"):
            raise ValueError("an alerted remediation changes nothing (steps none); a cancelled one does")
        rotated = self.steps == "rotate_forward_then_disable"
        if rotated:
            if self.rotation_evidence_id is None or self.version_id is None or self.disabled_version_id is None:
                raise ValueError("a forward rotation names its evidence, the version it issued and the one disabled")
            if self.version_id == self.disabled_version_id:
                raise ValueError("the forward rotation issues another version than the one disabled")
        elif self.rotation_evidence_id is not None or self.version_id is not None:
            raise ValueError("only a forward rotation names rotation evidence or a new version")
        if self.steps == "none" and self.disabled_version_id is not None:
            raise ValueError("an alerted remediation disables nothing")
        return self


class ReviewRecord(_SignedRecord):
    """A second person's verdict on a judged change or a decision, signed by the NA (v1.4.0).

    ``requested_by`` (an operator key, with its ``justification`` and its
    signed request in ``request_approval``) is absent when the NA opened the
    review itself (``opened_for``: ``flagged_for_review`` or
    ``review_required``). ``decided_by`` is a privileged key whose holder
    (``decider_holder``) differs from the requester's and from the holder the
    NA mapped the observed actor to (``actor_holder``); its signed request is
    ``approval``. ``waive_until`` is present exactly for a waiver.
    """

    review_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    subject_kind: RemediationSubjectKind
    subject_id: str = Field(..., min_length=1, max_length=128)
    subject_digest: str = Field(..., min_length=64, max_length=64,
                                description="SHA-256 of the subject's stored payload")
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)
    capability: str | None = Field(default=None, min_length=1, max_length=256)
    opened_for: ReviewOpenedFor
    requested_by: str | None = Field(default=None, min_length=1, max_length=256)
    requester_holder: str | None = Field(default=None, min_length=1, max_length=128)
    justification: str | None = Field(default=None, min_length=1, max_length=1024)
    request_approval: AdminApproval | None = None
    requested_at: datetime
    actor: str | None = Field(default=None, min_length=1, max_length=256,
                              description="The actor as the source reported it; not authenticated")
    actor_holder: str | None = Field(default=None, min_length=1, max_length=128)
    verdict: ReviewVerdict
    waive_until: datetime | None = None
    note: str | None = Field(default=None, min_length=1, max_length=1024)
    decided_by: str = Field(..., min_length=1, max_length=256)
    decider_holder: str = Field(..., min_length=1, max_length=128)
    approval: AdminApproval
    decided_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "ReviewRecord":
        if (self.verdict == "waive_until") != (self.waive_until is not None):
            raise ValueError("waive_until is given exactly for a waiver")
        if self.waive_until is not None and not (
                self.decided_at < self.waive_until <= self.decided_at + timedelta(seconds=MAX_WAIVER_SECONDS)):
            raise ValueError("a waiver ends after it is decided and within the longest waiver")
        requested = self.opened_for == "requested"
        given = (self.requested_by, self.requester_holder, self.justification, self.request_approval)
        if requested and any(v is None for v in given):
            raise ValueError("a requested review names its requester, holder, justification and request")
        if not requested and any(v is not None for v in given):
            raise ValueError("a review the NA opened has no requester")
        return self


#: Optional fields each Stage 3 record omits from its signed form when absent.
REMEDIATION_OMIT_WHEN_NONE: dict[str, tuple[str, ...]] = {
    model.__name__: tuple(
        name for name, info in model.model_fields.items()
        if name != "signature" and not info.is_required() and info.default is None
    )
    for model in (RemediationRecord, ReviewRecord)
}
