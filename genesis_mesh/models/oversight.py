"""Human Oversight models — policy, approval workflow, and dual-signed commitments.

The oversight layer sits between authorization (can the agent?) and execution
(has the human approved this specific high-stakes action?).

Signing invariants
------------------
- HumanOversightPolicy.to_canonical_json() excludes `signature`
- HumanApprovalRequest.to_canonical_json() excludes `agent_signature`
- HumanApprovalResponse.to_canonical_json() excludes `human_signature`
- DualSignedCommitment.to_canonical_json() excludes BOTH `agent_signature`
  and `human_signature`; both parties sign the same canonical form.
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
    agent_signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"agent_signature"}, mode="json")
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


class DualSignedCommitment(BaseModel):
    """Commitment that requires both the agent key and the human custodian key.

    Both parties sign the same canonical form (excluding both signatures).
    The commitment cannot be forged by either party alone.
    """

    commitment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = Field(..., description="Links to HumanApprovalRequest")
    response_id: str = Field(..., description="Links to HumanApprovalResponse")
    agreement_id: str = Field(..., description="Underlying AgreementRecord")
    acting_sovereign_id: str = Field(..., description="Agent performing the action")
    human_sovereign_id: str = Field(..., description="Human custodian who approved")
    proposed_action: dict[str, Any] = Field(..., description="The approved action (copied from request)")
    committed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Commitment validity ceiling")
    agent_signature: Signature | None = Field(
        default=None,
        description="Acting sovereign's Ed25519 signature over canonical form",
    )
    human_signature: Signature | None = Field(
        default=None,
        description="Human custodian's Ed25519 signature over canonical form",
    )

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"agent_signature", "human_signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()

    def is_fully_signed(self) -> bool:
        return self.agent_signature is not None and self.human_signature is not None
