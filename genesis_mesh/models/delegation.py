"""Attenuable Delegation Chain models.

A DelegatedAgreementRecord lets a party holding an AgreementRecord (or another
DelegatedAgreementRecord) sub-delegate a strict subset of its rights to a third
party.  Every hop in the chain must narrow authority.  Any hop that widens scope
makes the entire chain unverifiable.

Signing invariant
-----------------
DelegatedAgreementRecord uses the same canonical-JSON discipline as
AgreementRecord: ``to_canonical_json()`` excludes ``signatures``, sorted keys,
compact separators.  Both the delegator and delegate sign the same canonical
form, so the terminal holder can verify both signatures in one pass.

Chain invariant
---------------
``delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities`` at every hop.
``expires_at ≤ parent.expires_at`` at every hop.
The root of every chain is an ``AgreementRecord``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .agreement import AgreementRecord, AgreementTerms
from .genesis import Signature


class DelegatedAgreementRecord(BaseModel):
    """One hop in an attenuable delegation chain.

    Signed by both the delegator (the party passing authority) and the delegate
    (the party receiving it).  Neither can produce the record alone.

    ``parent_terms_digest`` binds this delegation to the specific terms of the
    parent record.  If the parent's terms change, the digest breaks and the
    delegation requires renewal.
    """

    delegation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique delegation identifier",
    )
    parent_id: str = Field(
        ...,
        description="agreement_id or delegation_id of the parent record",
    )
    parent_kind: str = Field(
        ...,
        description='"agreement" or "delegation"',
    )
    parent_terms_digest: str = Field(
        ...,
        description="SHA-256 hex of the parent record's canonical agreed_terms JSON",
    )
    delegator_sovereign_id: str = Field(
        ...,
        description="Party delegating authority (must be a party in the parent)",
    )
    delegate_sovereign_id: str = Field(
        ...,
        description="Party receiving authority",
    )
    delegated_terms: AgreementTerms = Field(
        ...,
        description="Terms being delegated — MUST be ⊆ parent terms",
    )
    delegator_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence (delegator → delegate direction)",
    )
    delegate_evidence: dict[str, Any] = Field(
        ...,
        description="TrustEvidence (delegate → delegator direction)",
    )
    graph_digest: str = Field(
        ...,
        description="SHA-256 of the delegator's recognition graph at delegation time",
    )
    established_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the delegation was established",
    )
    expires_at: datetime = Field(
        ...,
        description="Delegation validity ceiling (≤ parent expires_at)",
    )
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Signatures from both delegator and delegate",
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the delegator and delegate both sign.

        Excludes ``signatures``, ``delegation_id``, ``established_at``, and
        ``delegate_evidence``.

        ``delegate_evidence`` is excluded for the same reason ``expires_at`` is
        excluded from AgreementRecord: it is populated at cosign time (after the
        delegator has already signed), so including it would produce different
        canonical forms for the two signing steps.  The delegator's signature
        already binds delegator_evidence + terms + chain linkage + identities;
        the delegate's own signature is their binding claim of acceptance.
        """
        data = {
            "delegate_sovereign_id": self.delegate_sovereign_id,
            "delegated_terms": self.delegated_terms.model_dump(mode="json"),
            "delegator_evidence": self.delegator_evidence,
            "delegator_sovereign_id": self.delegator_sovereign_id,
            "graph_digest": self.graph_digest,
            "parent_id": self.parent_id,
            "parent_kind": self.parent_kind,
            "parent_terms_digest": self.parent_terms_digest,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# DelegationChain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegationChain:
    """A root AgreementRecord followed by an ordered list of delegation hops.

    ``root`` is the AgreementRecord that anchors the chain.
    ``hops`` is ordered from the first delegation (root's party) to the terminal.
    An empty ``hops`` list is not useful; chains must have at least one hop.
    """

    root: AgreementRecord
    hops: list[DelegatedAgreementRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Digest helper
# ---------------------------------------------------------------------------


def terms_digest(terms: AgreementTerms) -> str:
    """SHA-256 hex of the canonical JSON of an AgreementTerms block."""
    payload = json.dumps(terms.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
