"""Justification Proof models — gate trace artefacts for BoundaryEngine decisions.

A JustificationProof is a cryptographic attestation that the named operator
applied the named gates, in the named order, to the named inputs, and reached
the named decision.  Any auditor holding the issuer's public key can verify
it offline.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .genesis import Signature


class GateTraceEntry(BaseModel):
    """Record of a single gate evaluation within a BoundaryEngine run."""

    gate_name: str = Field(..., description="Gate identifier (matches GateResult.gate_name)")
    gate_type: str = Field(..., description="Class name of the gate, e.g. 'CapabilityGate'")
    evaluated_at: datetime = Field(..., description="UTC timestamp when this gate was called")
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Gate-specific inputs (serialisable); empty for custom gates",
    )
    result: bool = Field(..., description="True if the gate passed")
    reason: str = Field(..., description="Human-readable explanation from the gate")
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateTrace(BaseModel):
    """Ordered record of every gate evaluation during one BoundaryEngine.evaluate() call."""

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str = Field(..., description="Links to the BoundaryDecision produced by this run")
    agreement_id: str = Field(..., description="Underlying AgreementRecord")
    operator_sovereign_id: str = Field(..., description="Sovereign that ran the engine")
    traced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entries: list[GateTraceEntry] = Field(
        default_factory=list,
        description="Gate evaluations in evaluation order; short-circuited runs end early",
    )
    short_circuited_at: str | None = Field(
        default=None,
        description="gate_name of the first failed gate; None if all gates passed",
    )
    final_authorized: bool = Field(..., description="Matches BoundaryDecision.authorized")


class JustificationProof(BaseModel):
    """Signed attestation binding a GateTrace to a BoundaryDecision.

    Signing convention: to_canonical_json() excludes `signature`, uses
    sort_keys=True and compact separators — identical to all other GM models.
    """

    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str = Field(..., description="Links to BoundaryDecision.decision_id")
    trace: GateTrace = Field(..., description="The full gate trace for this decision")
    proof_issued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this proof was signed",
    )
    issuer_sovereign_id: str = Field(..., description="Sovereign whose key signed this proof")
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()
