"""Invocation-Bound Capability Token (IBCT) models.

An InvocationToken fuses sovereign identity, an attenuated capability scope
derived from an AgreementRecord or DelegationRecord, and an optional invocation
budget into a single signed artefact.

Any verifier holding the issuer's public key can validate the token offline
without querying the GM stack.  When a budget is set (max_invocations), the
verifier counts InvocationUseRecords to determine remaining budget.

Use-records form their own append-only chain via prev_use_digest, giving the
same tamper-evident linkage as ExecutionEvidence.

Based on: arXiv:2603.24775 (AIP — Agent Identity Protocol)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class InvocationToken(BaseModel):
    """A compact signed token that authorises a bearer to invoke specific capabilities.

    Issued by a sovereign (typically the party that holds or granted the
    AgreementRecord) on behalf of a bearer.  The token's capabilities are
    always a subset of the source agreement or delegation.
    """

    token_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    issued_at: datetime
    expires_at: datetime
    issuer_sovereign_id: str
    bearer_sovereign_id: str
    agreement_id: str
    delegation_id: str | None = Field(
        default=None,
        description="delegation_id of the source DelegatedAgreementRecord, when applicable",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Attenuated subset of capabilities from the source agreement or delegation",
    )
    max_invocations: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of uses; None means unlimited",
    )
    policy_constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Structured policy predicates enforced at verification time. "
            "Supported: 'not_before:ISO8601', 'peer_sovereign:sovereign_id'"
        ),
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        """Return deterministic JSON bytes the issuer signs."""
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """SHA-256 hex of the canonical JSON."""
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class InvocationUseRecord(BaseModel):
    """Record of a single token invocation.

    Use-records form an append-only chain via prev_use_digest, mirroring the
    ExecutionEvidence hash-chain pattern.  Each record is signed by the bearer.
    """

    use_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_id: str
    used_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used_by_sovereign_id: str
    action_tag: str = Field(description="Short label for the invoked action")
    outcome: str = Field(description='"success" | "failure"')
    prev_use_digest: str | None = Field(
        default=None,
        description="SHA-256 hex of the prior InvocationUseRecord's canonical JSON (None for first)",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        """Return deterministic JSON bytes the bearer signs."""
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """SHA-256 hex of the canonical JSON."""
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()
