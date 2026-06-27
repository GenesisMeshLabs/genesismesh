"""Relationship Agreement models: Offer → Counter-offer → AgreementRecord.

The canonical-JSON signing convention follows the rest of the GM model layer:
``to_canonical_json()`` excludes ``signatures``, uses sorted keys and compact
separators, producing deterministic bytes for Ed25519 signing.

Key invariant preserved in the canonical form:
``CapabilityCounter.to_canonical_json()`` and
``AgreementRecord.to_canonical_json()`` produce **identical JSON** for the same
content.  This means the responder's counter signature (produced over the
counter canonical form) is also valid when verified against the AgreementRecord
canonical form.  ``accept_counter`` exploits this to produce a dual-signed
AgreementRecord in a single step.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .genesis import Signature


# ---------------------------------------------------------------------------
# AgreementTerms
# ---------------------------------------------------------------------------


class AgreementTerms(BaseModel):
    """The negotiable content of a Relationship Agreement.

    Capabilities are always a subset of what existing treaties permit.
    An AgreementTerms block cannot create new rights.
    """

    capabilities: list[str] = Field(
        default_factory=list,
        description="Capability identifiers agreed between the parties",
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Operator-defined scope constraints (e.g. delegation, region)",
    )
    valid_from: datetime = Field(
        ...,
        description="Start of the agreed capability window (UTC)",
    )
    valid_until: datetime = Field(
        ...,
        description="End of the agreed capability window (UTC)",
    )
    freshness_commitment: int = Field(
        default=0,
        ge=0,
        description="Minimum revocation-feed sequence the responder guarantees",
    )


# ---------------------------------------------------------------------------
# CapabilityOffer  (Step 1)
# ---------------------------------------------------------------------------


class CapabilityOffer(BaseModel):
    """Step 1: Offerer proposes terms and embeds their own TrustEvidence.

    The offer is signed by the offerer.  It carries:
    - The specific capabilities and scope being requested.
    - The offerer's TrustEvidence (offerer → responder direction), which the
      responder uses to assess whether to proceed.
    - A graph_digest that anchors the agreement to the offerer's graph state.
    - An ``expires_at`` limiting how long the responder has to accept.
    """

    offer_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique offer identifier",
    )
    offerer_sovereign_id: str = Field(..., description="Sovereign initiating the offer")
    responder_sovereign_id: str = Field(..., description="Sovereign receiving the offer")
    requested_terms: AgreementTerms = Field(
        ..., description="Capabilities and scope the offerer is requesting"
    )
    graph_digest: str = Field(
        ...,
        description="SHA-256 hex of the offerer's recognition-graph export at offer time",
    )
    offerer_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence from offerer toward responder (offerer→responder direction)",
    )
    expires_at: datetime = Field(
        ..., description="Offer validity ceiling; responder must accept before this time"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Offer creation timestamp",
    )
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Offerer signature over canonical offer body",
    )

    def to_canonical_json(self) -> str:
        """Return the canonical bytes the offerer signs."""
        data = self.model_dump(exclude={"signatures"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# CapabilityCounter  (Step 2 — optional)
# ---------------------------------------------------------------------------


def _agreement_canonical_dict(obj: Any) -> dict[str, Any]:
    """Extract the shared canonical fields for Counter and AgreementRecord.

    Both ``CapabilityCounter`` and ``AgreementRecord`` serialize these fields
    identically, which allows the responder's counter signature to remain valid
    when the offerer wraps the counter into a final ``AgreementRecord``.

    ``expires_at`` is intentionally excluded: the validity window is already
    captured inside ``agreed_terms.valid_until``, which IS in the canonical body.
    Including ``expires_at`` separately would diverge between counter (which
    inherits the offer's expiry window) and agreement (which uses the terms'
    valid_until), breaking cross-verification.
    """
    return {
        "agreed_terms": obj.agreed_terms.model_dump(mode="json"),
        "graph_digest": obj.graph_digest,
        "offer_id": obj.offer_id,
        "offerer_evidence": obj.offerer_evidence,
        "offerer_sovereign_id": obj.offerer_sovereign_id,
        "responder_evidence": obj.responder_evidence,
        "responder_sovereign_id": obj.responder_sovereign_id,
    }


class CapabilityCounter(BaseModel):
    """Step 2 (optional): Responder proposes narrower or equivalent terms.

    The counter is signed by the responder.  Its canonical form is IDENTICAL to
    the AgreementRecord canonical form (same fields, same structure).  When the
    offerer calls ``accept_counter``, the responder's counter signatures are
    carried into the AgreementRecord unchanged and remain verifiable.

    Counter terms must never widen the offerer's requested capabilities.
    """

    offer_id: str = Field(..., description="Links this counter to the original CapabilityOffer")
    offerer_sovereign_id: str
    responder_sovereign_id: str
    agreed_terms: AgreementTerms = Field(
        ...,
        description="Terms the responder proposes (subset of requested_terms)",
    )
    offerer_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence carried forward from the offer (offerer→responder direction)",
    )
    responder_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence from responder toward offerer (responder→offerer direction)",
    )
    graph_digest: str = Field(
        ...,
        description="Graph digest carried from the original offer",
    )
    expires_at: datetime = Field(
        ...,
        description="Inherited from the original offer's expires_at",
    )
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Responder signature over canonical counter body",
    )

    def to_canonical_json(self) -> str:
        """Return canonical bytes — identical structure to AgreementRecord."""
        return json.dumps(
            _agreement_canonical_dict(self),
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# AgreementRecord  (Step 3 — final artifact)
# ---------------------------------------------------------------------------


class AgreementRecord(BaseModel):
    """Dual-signed Relationship Agreement.

    The AgreementRecord is the first GM artifact that requires two independent
    signatures.  Neither party can produce it alone.

    Its ``to_canonical_json()`` is IDENTICAL to ``CapabilityCounter.to_canonical_json()``
    for the same content.  This is a deliberate design decision: it allows the
    responder's counter signature to be valid over the final AgreementRecord
    without requiring the responder to sign a second time.

    What this proves:
    - Both parties signed the same terms (mutual agreement).
    - Terms are bounded to a specific graph state (graph_digest).
    - Independent TrustEvidence from both directions is embedded.
    - Transport independence: validity is independent of how the files were
      exchanged (email, API, USB, Noise XX session).

    What this does NOT prove:
    - That a new treaty exists (agreements evaluate existing rights only).
    - That capabilities exceed treaty scope (impossible by construction).
    """

    agreement_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique agreement identifier",
    )
    offer_id: str = Field(..., description="The CapabilityOffer that started this agreement")
    offerer_sovereign_id: str
    responder_sovereign_id: str
    agreed_terms: AgreementTerms
    offerer_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence offerer→responder direction",
    )
    responder_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence responder→offerer direction",
    )
    graph_digest: str = Field(
        ...,
        description="SHA-256 of the offerer's recognition graph at agreement time",
    )
    established_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the agreement was established",
    )
    expires_at: datetime = Field(..., description="Agreement validity ceiling")
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Signatures from both parties over the canonical agreement body",
    )

    def to_canonical_json(self) -> str:
        """Return canonical bytes — identical structure to CapabilityCounter."""
        return json.dumps(
            _agreement_canonical_dict(self),
            sort_keys=True,
            separators=(",", ":"),
        )
