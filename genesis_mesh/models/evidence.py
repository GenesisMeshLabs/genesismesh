"""TrustEvidence: a signed, portable proof of a trust decision.

A TrustEvidence record binds a trust verdict to the recognition-graph state
that produced it via ``graph_digest`` (SHA-256 of the canonical graph export).
The record can be passed to a second sovereign, which verifies the Ed25519
signature and, optionally, re-derives the digest to confirm the graph evidence
has not changed since the decision was made.

Follows the canonical-JSON signing convention used by ``RecognitionTreaty``,
``MembershipAttestation``, and ``SovereignRevocationFeed``:
- ``to_canonical_json`` serialises every field *except* ``signatures`` with
  ``sort_keys=True`` and compact separators.
- ``signatures`` carries one or more ``Signature`` entries produced by
  ``sign_model`` / verified by ``verify_model_signature``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .genesis import Signature


class TrustEvidence(BaseModel):
    """Signed proof of a trust decision between two sovereigns.

    The evidence record is self-describing: a verifier needs only the record,
    the issuer's public key, and -- for strict graph binding -- the original
    recognition-graph export.
    """

    evidence_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique evidence record identifier",
    )
    issuer_sovereign_id: str = Field(
        ...,
        description="Sovereign that produced and signed this evidence",
    )
    source_sovereign_id: str = Field(
        ...,
        description="Sovereign that evaluated trust (usually the issuer)",
    )
    target_sovereign_id: str = Field(
        ...,
        description="Sovereign whose recognition was evaluated",
    )
    verdict: str = Field(
        ...,
        description="Trust verdict: allow, warn, block, or escalate",
    )
    reason: str = Field(
        ...,
        description="Machine-readable primary reason code for the verdict",
    )
    requested_roles: list[str] = Field(
        default_factory=list,
        description="Roles that were checked against treaty scope",
    )
    trusted: bool = Field(
        ...,
        description="Whether an active recognition path was found",
    )
    hop_count: int = Field(
        ...,
        ge=0,
        description="Number of treaty hops on the trust path",
    )
    signals: list[dict[str, str]] = Field(
        default_factory=list,
        description="Ordered list of {code, severity, detail} signals",
    )
    graph_digest: str = Field(
        ...,
        description="SHA-256 hex digest of the canonical recognition-graph export used during evaluation",
    )
    evaluated_at: str = Field(
        ...,
        description="UTC ISO-8601 timestamp at which the decision was evaluated",
    )
    issued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp at which this evidence record was issued",
    )
    issued_by: str = Field(
        ...,
        description="Issuer signing key identifier",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional operator metadata",
    )
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Issuer signatures over the canonical evidence body",
    )

    def to_canonical_json(self) -> str:
        """Return canonical JSON used for signing and verification.

        Excludes ``signatures`` so the evidence body is stable across
        re-signings.
        """
        data = self.model_dump(exclude={"signatures"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
