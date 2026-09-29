"""Relationship Context models: ContextRecord, BoundaryDecision, GateResult.

A ContextRecord is an unsigned assertion by the requester that they want to
invoke a specific capability under a specific AgreementRecord.  The
BoundaryEngine evaluates it against a set of ordered gates and produces a
signed BoundaryDecision.

An AgreementRecord proves that two parties agreed to terms.
A ContextRecord + BoundaryDecision proves that a specific interaction is
authorised under those terms, right now, given current conditions.

BoundaryDecision signing invariant
------------------------------------
``BoundaryDecision.to_canonical_json()`` excludes ``signature`` only.
Sorted keys, compact separators.  The operator signs this canonical form.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .boundary_policy import PolicyBinding
from .freshness import FreshnessProof
from .genesis import Signature


class GateResult(BaseModel):
    """Outcome of a single gate evaluation."""

    gate_name: str = Field(..., description="Gate identifier")
    passed: bool = Field(..., description="True if the gate passed")
    detail: str = Field(..., description="Human-readable explanation (always present)")


class ContextRecord(BaseModel):
    """Unsigned assertion by the requester for a specific capability invocation.

    The ContextRecord is created by the requester and passed to the
    BoundaryEngine.  It is not signed — it is an input to the evaluation.
    The BoundaryEngine's signed BoundaryDecision is the authoritative output.
    """

    context_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique context identifier",
    )
    agreement_id: str = Field(
        ...,
        description="AgreementRecord or DelegatedAgreementRecord this context is under",
    )
    parent_kind: str = Field(
        default="agreement",
        description='"agreement" or "delegation"',
    )
    requester_sovereign_id: str = Field(
        ..., description="Party requesting the capability"
    )
    provider_sovereign_id: str = Field(
        ..., description="Party providing the capability"
    )
    requested_capability: str = Field(
        ...,
        description="Capability identifier being requested (must be in agreed_terms.capabilities)",
    )
    request_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-defined parameters for this invocation",
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the request was made",
    )
    context_freshness_seq: int = Field(
        default=0,
        ge=0,
        description="Revocation-feed sequence number observed at request time",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Normalized facts supplied by the external system for policy gates "
            "(e.g. an upstream risk tier).  Never place credentials, tokens or "
            "secret values here -- supply metadata about them instead."
        ),
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON of the full context (sorted keys, compact)."""
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """SHA-256 hex digest of the canonical context."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


class BoundaryDecision(BaseModel):
    """Signed output of BoundaryEngine.evaluate().

    The decision is bounded in time (decision_valid_until) and is signed by the
    operator's key.  It is auditable, revocable independent of the agreement, and
    references both the ContextRecord and the underlying AgreementRecord.

    authorized=True means all gates passed and execution may proceed until
    decision_valid_until.  authorized=False means at least one gate failed.
    """

    decision_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique decision identifier",
    )
    context_id: str = Field(..., description="Links to the ContextRecord")
    agreement_id: str = Field(..., description="Underlying AgreementRecord or DelegatedAgreementRecord")
    authorized: bool = Field(..., description="True if all gates passed")
    denial_reason: str | None = Field(
        default=None,
        description="Human-readable denial reason when authorized=False",
    )
    gate_results: list[GateResult] = Field(
        default_factory=list,
        description="Ordered list of gate evaluation results",
    )
    decision_made_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the decision was made",
    )
    decision_valid_until: datetime = Field(
        ...,
        description="Ceiling of this authorization; not a permanent grant",
    )
    operator_sovereign_id: str = Field(
        ..., description="Operator whose key signed this decision"
    )
    freshness_proof: FreshnessProof | None = Field(
        default=None,
        description="Optional FreshnessProof embedded by the BoundaryEngine "
        "when require_freshness_proof=True; included in canonical form",
    )
    policy_binding: PolicyBinding | None = Field(
        default=None,
        description="Policy basis for policy-aware decisions (v0.58); signed "
        "when present, omitted from the canonical form when absent",
    )
    signature: Signature | None = Field(
        default=None,
        description="Ed25519 signature by the operator over canonical decision body",
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the operator signs.

        Excludes ``signature`` only.  ``freshness_proof`` (including the proof's
        own nested signature) IS included — the operator signs over the whole
        proof structure.  ``policy_binding`` is included when present and the
        key is omitted entirely when it is None, so decisions produced before
        v0.58 keep byte-identical canonical forms.  Sorted keys, compact
        separators.
        """
        exclude: set[str] = {"signature"}
        if self.policy_binding is None:
            exclude.add("policy_binding")
        data = self.model_dump(exclude=exclude, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
