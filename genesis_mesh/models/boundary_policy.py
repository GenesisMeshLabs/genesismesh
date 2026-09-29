"""Declarative Boundary Policy models (v0.57).

A BoundaryPolicy is a signed, versioned document that selects requests by
generic ContextRecord facts and configures gates drawn from the Network
Authority's trusted gate registry.  Policies carry configuration only -- a
``gate_type`` is a lookup key into code the operator already installed, never
code itself.

A PolicyBinding is embedded in a policy-aware BoundaryDecision.  It lives
inside the decision's signed body, so the operator signature covers the exact
policy versions, gate configuration digest, evaluation order and per-gate
outcomes that produced the decision.

Signing invariant
-----------------
``BoundaryPolicy.to_canonical_json()`` excludes ``signature`` only.  Sorted
keys, compact separators -- identical to every other GM signed model.
Activation state is deliberately *not* part of the signed body: activating,
deactivating or rolling back a version never changes signed bytes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .genesis import Signature

JsonScalar = Union[str, int, float, bool, None]

GateMode = Literal["enforce", "observe"]

GateOutcome = Literal["pass", "fail", "missing_context", "invalid_context", "gate_error"]

PolicyResolutionStatus = Literal["resolved", "failed"]

MAX_GATES_PER_POLICY = 64
MAX_LIST_VALUES = 256


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


class PolicySelector(BaseModel):
    """Which requests a policy applies to.

    AND across fields, OR within a field.  An empty field places no
    constraint; a selector with every field empty is a global policy.
    """

    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(
        default_factory=list,
        max_length=MAX_LIST_VALUES,
        description='Exact capability ids, or a prefix pattern ending in ".*"',
    )
    requester_sovereign_ids: list[str] = Field(default_factory=list, max_length=MAX_LIST_VALUES)
    provider_sovereign_ids: list[str] = Field(default_factory=list, max_length=MAX_LIST_VALUES)
    agreement_ids: list[str] = Field(default_factory=list, max_length=MAX_LIST_VALUES)
    parent_kinds: list[str] = Field(default_factory=list, max_length=MAX_LIST_VALUES)
    parameter_equals: dict[str, list[JsonScalar]] = Field(
        default_factory=dict,
        description="Fact path -> allowed scalar values (OR within one path, AND across paths)",
    )

    def is_global(self) -> bool:
        return not any(
            (
                self.capabilities,
                self.requester_sovereign_ids,
                self.provider_sovereign_ids,
                self.agreement_ids,
                self.parent_kinds,
                self.parameter_equals,
            )
        )


class GateSpec(BaseModel):
    """One configured gate inside a BoundaryPolicy."""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(..., description="Unique within the policy; [a-z0-9_-]{1,64}")
    gate_type: str = Field(..., description='Trusted registry key, e.g. "max_value.v1"')
    order: int = Field(..., description="Evaluation order within the policy; unique, >= 0")
    mode: GateMode = Field(
        default="enforce",
        description='"enforce" denies on failure; "observe" records the failure only',
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Gate configuration, validated by the gate type's config model",
    )
    disclose_input: bool = Field(
        default=False,
        description="Record the raw input value in the proof; default records presence and type only",
    )


class BoundaryPolicy(BaseModel):
    """Signed, versioned declarative authorization policy for BoundaryEngine."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(..., description="Stable policy identity across versions")
    version: int = Field(..., ge=1, description="Assigned by the Network Authority")
    description: str = Field(default="", max_length=1024)
    valid_from: datetime = Field(..., description="Policy does not apply before this instant")
    valid_until: datetime = Field(..., description="An active policy past this instant fails closed")
    selector: PolicySelector = Field(default_factory=PolicySelector)
    gates: list[GateSpec] = Field(default_factory=list)
    issued_at: datetime = Field(..., description="UTC time the NA signed this version")
    issued_by: str = Field(..., description="NA key id that signed this version")
    issuer_sovereign_id: str = Field(..., description="Sovereign operating the issuing NA")
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the NA signs (excludes ``signature`` only)."""
        return _canonical(self.model_dump(exclude={"signature"}, mode="json"))

    def digest(self) -> str:
        """SHA-256 hex digest of the canonical signed body."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


class AppliedPolicy(BaseModel):
    """A policy version that applied to a decision."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    version: int
    policy_digest: str = Field(..., description="BoundaryPolicy.digest() of the applied version")
    signed_by: str = Field(..., description="Key id on the policy signature")


class PolicyGateEvaluation(BaseModel):
    """Outcome of one configured gate within a policy-aware evaluation."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    policy_version: int
    gate_id: str
    gate_type: str
    order: int
    mode: GateMode
    passed: bool
    outcome: GateOutcome


class PolicyBinding(BaseModel):
    """Policy basis of a BoundaryDecision; covered by the decision signature."""

    model_config = ConfigDict(extra="forbid")

    policies: list[AppliedPolicy] = Field(
        default_factory=list, description="Applied policies in resolution order"
    )
    policy_set_digest: str = Field(
        ..., description="SHA-256 over the ordered (policy_id, version, policy_digest) list"
    )
    gate_evaluations: list[PolicyGateEvaluation] = Field(
        default_factory=list, description="Configured gate outcomes in evaluation order"
    )
    context_digest: str = Field(..., description="SHA-256 of the canonical ContextRecord")
    registry_gate_types: list[str] = Field(
        default_factory=list, description="Sorted gate types referenced by applied policies"
    )
    resolution_status: PolicyResolutionStatus
    resolution_failure: str | None = Field(
        default=None, description="Stable failure code when resolution_status is 'failed'"
    )


def policy_set_digest(policies: list[AppliedPolicy]) -> str:
    """Digest the ordered applied-policy list (pure helper used by engine and verifier)."""
    payload = [[p.policy_id, p.version, p.policy_digest] for p in policies]
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
