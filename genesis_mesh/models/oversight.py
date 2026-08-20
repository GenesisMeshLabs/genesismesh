"""Human Oversight models — policy, approval workflow, and dual-signed commitments.

The oversight layer sits between authorization (can the agent?) and execution
(has the human approved this specific high-stakes action?).

Signing invariants
------------------
- HumanOversightPolicy.to_canonical_json() excludes `signature`
- HumanApprovalRequest.to_canonical_json() excludes `agent_signature` and
  `commitment_core_signature`
- HumanApprovalResponse.to_canonical_json() excludes `human_signature`
- DualSignedCommitment.to_canonical_json() excludes BOTH `agent_signature`
  and `human_signature`.

The two parties do NOT sign the same bytes, and it matters:

- the human signs the DualSignedCommitment's canonical form;
- the agent signs a CommitmentCore — the subset of the commitment that is fixed
  at request time — which a verifier can rebuild from the commitment alone.

That asymmetry is what makes the commitment self-verifiable without also
shipping the original HumanApprovalRequest alongside it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .genesis import Signature

OversightEscalationLevel = Literal["automatic", "human_approve", "block"]


class HumanOversightPolicy(BaseModel):
    """Signed policy defining which actions require human approval.

    The policy is scoped to an AgreementRecord and signed by the operator
    (or human custodian) who owns the oversight responsibility.
    """

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agreement_id: str = Field(..., description="AgreementRecord this policy governs")
    human_sovereign_id: str = Field(..., description="Sovereign who must countersign commitments")
    allowed_capabilities: list[str] = Field(
        ..., description="Only these capabilities are permitted; others block immediately"
    )
    counterparty_allowlist: list[str] = Field(
        default_factory=list,
        description="If non-empty, requesting sovereign must appear here or action escalates",
    )
    value_threshold: float | None = Field(
        default=None,
        description="Actions with proposed_action['value'] > threshold escalate",
    )
    allowed_hours: tuple[int, int] | None = Field(
        default=None,
        description="[start_hour_utc, end_hour_utc) window; requests outside this escalate",
    )
    frequency_limit: tuple[int, int] | None = Field(
        default=None,
        description="[max_count, window_seconds]; escalates if recent_action_count >= max_count",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class HumanApprovalRequest(BaseModel):
    """Signed proposal for a high-stakes action requiring human approval.

    The agent signs this request with its own key, proposing that the action
    be approved by the human custodian.  The agent_signature is the agent's
    attestation that it proposes this action.
    """

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str = Field(..., description="Policy being applied")
    requesting_sovereign_id: str = Field(..., description="Agent requesting approval")
    proposed_action: dict[str, Any] = Field(
        ..., description="Action to be approved; must include 'capability' key"
    )
    escalation_level: OversightEscalationLevel = Field(
        ..., description="human_approve (only valid value here; automatic/block handled earlier)"
    )
    escalation_reasons: list[str] = Field(
        ..., description="Human-readable reasons from failed policy checks"
    )
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Agent must receive approval before this time")
    agent_signature: Signature | None = Field(
        default=None,
        description="Agent's Ed25519 signature over this request's canonical form",
    )
    commitment_core_signature: Signature | None = Field(
        default=None,
        description="Agent's Ed25519 signature over the CommitmentCore for this "
                    "request.  Copied into DualSignedCommitment.agent_signature so "
                    "the commitment can be verified without this request.",
    )

    def to_canonical_json(self) -> str:
        data = self.model_dump(
            exclude={"agent_signature", "commitment_core_signature"}, mode="json"
        )
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class HumanApprovalResponse(BaseModel):
    """Signed response from the human custodian to an approval request."""

    response_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = Field(..., description="Links to HumanApprovalRequest")
    human_sovereign_id: str = Field(..., description="Human custodian who responded")
    approved: bool = Field(..., description="True if the custodian approved")
    responded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    response_note: str | None = Field(default=None, description="Optional approval/rejection note")
    human_signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"human_signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class CommitmentCore(BaseModel):
    """The agent's attestation, reconstructible from a DualSignedCommitment.

    The agent signs this at request time, when all four fields are already
    known.  Every field is also carried on the finished DualSignedCommitment, so
    a verifier can rebuild this object from the commitment alone and check the
    agent's signature without holding the original HumanApprovalRequest.

    proposed_action is included deliberately rather than relying on
    request_digest to cover it.  If the core bound only the digest, a party
    holding the human key could lift a genuine (digest, signature) pair onto a
    commitment carrying a different action, and a verifier without the request
    could not detect the swap.
    """

    request_id: str = Field(..., description="HumanApprovalRequest being attested")
    acting_sovereign_id: str = Field(..., description="Agent proposing the action")
    proposed_action: dict[str, Any] = Field(..., description="Action the agent proposed")
    request_digest: str = Field(..., description="SHA-256 of the agent-signed request")

    def to_canonical_json(self) -> str:
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class DualSignedCommitment(BaseModel):
    """Commitment that requires both the agent key and the human custodian key.

    The two parties sign different bytes: the human signs this commitment's
    canonical form, and the agent signs the CommitmentCore (which this
    commitment can reproduce).  Neither party can produce a valid commitment
    alone, and it verifies without the original request.
    """

    commitment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = Field(..., description="Links to HumanApprovalRequest")
    response_id: str = Field(..., description="Links to HumanApprovalResponse")
    agreement_id: str = Field(..., description="Underlying AgreementRecord")
    acting_sovereign_id: str = Field(..., description="Agent performing the action")
    human_sovereign_id: str = Field(..., description="Human custodian who approved")
    proposed_action: dict[str, Any] = Field(..., description="The approved action (copied from request)")
    request_digest: str | None = Field(
        default=None,
        description="SHA-256 of the agent-signed HumanApprovalRequest.  Part of "
                    "the CommitmentCore the agent signed and of the body the human "
                    "signed, so both parties are bound to one specific request.  "
                    "None only on commitments predating the self-verifiable format, "
                    "which no longer verify.",
    )
    committed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Commitment validity ceiling")
    agent_signature: Signature | None = Field(
        default=None,
        description="Acting sovereign's Ed25519 signature over the CommitmentCore "
                    "(NOT over this commitment's canonical form)",
    )
    human_signature: Signature | None = Field(
        default=None,
        description="Human custodian's Ed25519 signature over this commitment's "
                    "canonical form",
    )

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"agent_signature", "human_signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def core(self) -> "CommitmentCore | None":
        """Rebuild the CommitmentCore the agent signed, from this commitment.

        Returns None for a commitment with no request_digest — i.e. one issued
        before the self-verifiable format, whose agent signature covers the
        request rather than the core and therefore cannot be checked here.
        """
        if self.request_digest is None:
            return None
        return CommitmentCore(
            request_id=self.request_id,
            acting_sovereign_id=self.acting_sovereign_id,
            proposed_action=self.proposed_action,
            request_digest=self.request_digest,
        )

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()

    def is_fully_signed(self) -> bool:
        return self.agent_signature is not None and self.human_signature is not None
