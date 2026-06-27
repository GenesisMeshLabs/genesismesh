"""Build and verify Relationship Agreements.

Protocol: Offer → Counter-offer (optional) → Acceptance.
All functions are pure: no I/O, no side effects, no signing of unrelated data.

Key signing invariant
---------------------
``CapabilityCounter`` and ``AgreementRecord`` share an identical canonical-JSON
form (same fields, same serialization).  This means the responder's counter
signature is also valid over the AgreementRecord canonical form.  ``accept_counter``
exploits this to produce a dual-signed AgreementRecord in one call — the counter's
signatures are carried into the AgreementRecord unchanged, then the offerer adds
their own signature over the same canonical form.

For direct acceptance (no counter), ``accept_offer`` produces a half-signed
AgreementRecord (responder's signature only).  The offerer calls
``cosign_agreement`` to add the second signature.

Scope invariant
---------------
Counter terms MUST be a subset of the offer's requested capabilities.
``build_counter`` enforces this.  ``accept_counter`` re-checks.  Nothing in
this module can produce an AgreementRecord whose terms exceed treaty scope,
because the embedded TrustEvidence records (which come from the trust decision
engine) capture what treaties permit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import (
    AgreementRecord,
    AgreementTerms,
    CapabilityCounter,
    CapabilityOffer,
)
from ..models.genesis import Signature
from .decision import evaluate_trust_decision
from .evidence import build_trust_evidence, graph_digest_from_export


# ---------------------------------------------------------------------------
# AgreementVerificationResult
# ---------------------------------------------------------------------------

AgreementVerificationReason = Literal[
    "accepted",
    "missing_offerer_signature",
    "missing_responder_signature",
    "invalid_offerer_signature",
    "invalid_responder_signature",
    "graph_digest_mismatch",
    "terms_mismatch",
]


@dataclass(frozen=True)
class AgreementVerificationResult:
    """Structured outcome of an AgreementRecord verification attempt."""

    accepted: bool
    reason: AgreementVerificationReason
    agreement_id: str
    offerer_sovereign_id: str
    responder_sovereign_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "agreement_id": self.agreement_id,
            "offerer_sovereign_id": self.offerer_sovereign_id,
            "responder_sovereign_id": self.responder_sovereign_id,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _check_capabilities_subset(
    offered: list[str],
    requested: list[str],
    label: str = "Counter",
) -> None:
    """Raise ValueError if ``offered`` capabilities exceed ``requested``."""
    offered_set = set(offered)
    requested_set = set(requested)
    excess = offered_set - requested_set
    if excess:
        raise ValueError(
            f"{label} capabilities exceed offer scope: {sorted(excess)!r} "
            f"not in {sorted(requested_set)!r}"
        )


def _build_evidence_dict(
    graph: dict[str, Any],
    source_id: str,
    target_id: str,
    signing_key: nacl.signing.SigningKey,
    issued_by: str,
    now: datetime,
) -> dict[str, Any]:
    """Evaluate trust and build a signed TrustEvidence dict."""
    decision = evaluate_trust_decision(graph, source_id, target_id)
    digest = graph_digest_from_export(graph)
    evidence = build_trust_evidence(
        decision,
        issuer_sovereign_id=source_id,
        graph_digest=digest,
        issued_by=issued_by,
        signing_key=signing_key,
        now=now,
    )
    return evidence.model_dump(mode="json")


def _reject(
    record: AgreementRecord,
    reason: AgreementVerificationReason,
) -> AgreementVerificationResult:
    return AgreementVerificationResult(
        accepted=False,
        reason=reason,
        agreement_id=record.agreement_id,
        offerer_sovereign_id=record.offerer_sovereign_id,
        responder_sovereign_id=record.responder_sovereign_id,
    )


# ---------------------------------------------------------------------------
# Step 1: build_offer
# ---------------------------------------------------------------------------


def build_offer(
    offerer_sovereign_id: str,
    responder_sovereign_id: str,
    requested_terms: AgreementTerms,
    graph: dict[str, Any],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> CapabilityOffer:
    """Build and sign a CapabilityOffer (Step 1 of the Agreement protocol).

    Internally evaluates trust from the offerer toward the responder and
    embeds the result as ``offerer_evidence``.  The evidence captures whatever
    verdict the trust engine produces (allow, warn, escalate, block) — it is
    never silently promoted to ``allow``.

    Args:
        offerer_sovereign_id: Sovereign initiating the offer.
        responder_sovereign_id: Sovereign receiving the offer.
        requested_terms: Capabilities and scope being requested.
        graph: Offerer's recognition-graph export (used for trust evaluation
            and for computing ``graph_digest``).
        signing_key: Ed25519 key used to sign the offer and the embedded evidence.
        issued_by: Key identifier recorded in both signatures.
        expires_at: Offer validity ceiling.
        now: Override for the current timestamp.
    """
    ts = _now(now)
    offerer_evidence = _build_evidence_dict(
        graph, offerer_sovereign_id, responder_sovereign_id,
        signing_key, issued_by, ts,
    )
    digest = graph_digest_from_export(graph)
    offer = CapabilityOffer(
        offerer_sovereign_id=offerer_sovereign_id,
        responder_sovereign_id=responder_sovereign_id,
        requested_terms=requested_terms,
        graph_digest=digest,
        offerer_evidence=offerer_evidence,
        expires_at=expires_at,
        created_at=ts,
    )
    sig = sign_model(offer, signing_key, issued_by)
    offer.signatures.append(sig)
    return offer


# ---------------------------------------------------------------------------
# Step 2: build_counter (optional)
# ---------------------------------------------------------------------------


def build_counter(
    offer: CapabilityOffer,
    offered_terms: AgreementTerms,
    graph: dict[str, Any],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> CapabilityCounter:
    """Build and sign a CapabilityCounter (Step 2, optional).

    The counter's canonical form is IDENTICAL to the AgreementRecord canonical
    form.  Any signature produced here remains valid over the final
    AgreementRecord, enabling single-step finalization in ``accept_counter``.

    Raises:
        ValueError: If ``offered_terms.capabilities`` exceed the offer's
            ``requested_terms.capabilities`` (scope widening is forbidden).
        ValueError: If the offer's offerer_evidence verdict is ``"block"``
            (cannot form an agreement when trust is blocked in the offer
            direction).
    """
    ts = _now(now)

    # Scope narrowing enforcement
    _check_capabilities_subset(
        offered_terms.capabilities,
        offer.requested_terms.capabilities,
        label="Counter",
    )

    # Refuse to counter-offer when the offerer's own evidence blocks trust
    offerer_verdict = offer.offerer_evidence.get("verdict", "")
    if offerer_verdict == "block":
        raise ValueError(
            f"Cannot form agreement: offerer_evidence verdict is 'block' "
            f"(offerer {offer.offerer_sovereign_id!r} → responder "
            f"{offer.responder_sovereign_id!r})"
        )

    responder_evidence = _build_evidence_dict(
        graph,
        offer.responder_sovereign_id,
        offer.offerer_sovereign_id,
        signing_key, issued_by, ts,
    )

    counter = CapabilityCounter(
        offer_id=offer.offer_id,
        offerer_sovereign_id=offer.offerer_sovereign_id,
        responder_sovereign_id=offer.responder_sovereign_id,
        agreed_terms=offered_terms,
        offerer_evidence=offer.offerer_evidence,
        responder_evidence=responder_evidence,
        graph_digest=offer.graph_digest,
        expires_at=offer.expires_at,
    )
    sig = sign_model(counter, signing_key, issued_by)
    counter.signatures.append(sig)
    return counter


# ---------------------------------------------------------------------------
# Step 3a: accept_offer (responder accepts directly, no counter)
# ---------------------------------------------------------------------------


def accept_offer(
    offer: CapabilityOffer,
    graph: dict[str, Any],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> AgreementRecord:
    """Responder accepts the CapabilityOffer directly (no counter-offer).

    Returns a half-signed AgreementRecord containing only the responder's
    signature.  The offerer must call ``cosign_agreement`` to finalize.

    Raises:
        ValueError: If the offer's offerer_evidence verdict is ``"block"``.
        ValueError: If the offer has expired.
    """
    ts = _now(now)

    if ts > offer.expires_at:
        raise ValueError(
            f"Offer {offer.offer_id!r} expired at {offer.expires_at.isoformat()}"
        )

    offerer_verdict = offer.offerer_evidence.get("verdict", "")
    if offerer_verdict == "block":
        raise ValueError(
            f"Cannot accept offer: offerer_evidence verdict is 'block'"
        )

    responder_evidence = _build_evidence_dict(
        graph,
        offer.responder_sovereign_id,
        offer.offerer_sovereign_id,
        signing_key, issued_by, ts,
    )

    record = AgreementRecord(
        offer_id=offer.offer_id,
        offerer_sovereign_id=offer.offerer_sovereign_id,
        responder_sovereign_id=offer.responder_sovereign_id,
        agreed_terms=offer.requested_terms,
        offerer_evidence=offer.offerer_evidence,
        responder_evidence=responder_evidence,
        graph_digest=offer.graph_digest,
        established_at=ts,
        expires_at=offer.requested_terms.valid_until,
    )
    sig = sign_model(record, signing_key, issued_by)
    record.signatures.append(sig)
    return record


# ---------------------------------------------------------------------------
# Step 3b: accept_counter (offerer accepts counter)
# ---------------------------------------------------------------------------


def accept_counter(
    counter: CapabilityCounter,
    original_offer: CapabilityOffer,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> AgreementRecord:
    """Offerer accepts the CapabilityCounter (finalization step).

    Returns a DUAL-signed AgreementRecord.  The counter's signatures (responder's)
    are carried over unchanged — they remain valid over the AgreementRecord
    canonical form because both models share the same canonical JSON structure.
    The offerer then adds their own signature over the same canonical form.

    Raises:
        ValueError: If ``counter.offer_id`` does not match
            ``original_offer.offer_id``.
        ValueError: If the counter's capabilities exceed the original offer's
            requested capabilities (re-checked as defense-in-depth).
    """
    ts = _now(now)

    if counter.offer_id != original_offer.offer_id:
        raise ValueError(
            f"Counter offer_id {counter.offer_id!r} does not match "
            f"original offer_id {original_offer.offer_id!r}"
        )

    _check_capabilities_subset(
        counter.agreed_terms.capabilities,
        original_offer.requested_terms.capabilities,
        label="Counter",
    )

    # Carry counter's signatures into the agreement (same canonical form)
    record = AgreementRecord(
        offer_id=original_offer.offer_id,
        offerer_sovereign_id=original_offer.offerer_sovereign_id,
        responder_sovereign_id=original_offer.responder_sovereign_id,
        agreed_terms=counter.agreed_terms,
        offerer_evidence=counter.offerer_evidence,
        responder_evidence=counter.responder_evidence,
        graph_digest=original_offer.graph_digest,
        established_at=ts,
        expires_at=counter.agreed_terms.valid_until,
        signatures=list(counter.signatures),  # carry responder's sig
    )
    sig = sign_model(record, signing_key, issued_by)
    record.signatures.append(sig)
    return record


# ---------------------------------------------------------------------------
# cosign_agreement (offerer finalizes after direct acceptance)
# ---------------------------------------------------------------------------


def cosign_agreement(
    record: AgreementRecord,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
) -> AgreementRecord:
    """Add a second party's signature to a half-signed AgreementRecord.

    Used when the responder accepted the offer directly (``accept_offer``), which
    produces a half-signed record.  The offerer calls this to finalize.

    The signature is computed over the SAME canonical JSON as the existing
    signature — no fields change, only the ``signatures`` list grows.
    """
    sig = sign_model(record, signing_key, issued_by)
    return record.model_copy(update={"signatures": list(record.signatures) + [sig]})


# ---------------------------------------------------------------------------
# verify_agreement
# ---------------------------------------------------------------------------


def verify_agreement(
    record: AgreementRecord,
    offerer_public_keys: list[str],
    responder_public_keys: list[str],
    *,
    expected_graph_digest: str | None = None,
) -> AgreementVerificationResult:
    """Verify an AgreementRecord's dual signatures and optional graph binding.

    Checks that at least one signature in ``record.signatures`` verifies against
    ``offerer_public_keys`` AND at least one verifies against
    ``responder_public_keys``.  For the counter-acceptance flow this is always
    satisfied because both signatures were produced over the same canonical form.
    For the direct-acceptance flow, ``cosign_agreement`` must have been called
    first.

    Args:
        record: AgreementRecord to verify.
        offerer_public_keys: One or more base64 Ed25519 public keys for the
            offerer.
        responder_public_keys: One or more base64 Ed25519 public keys for the
            responder.
        expected_graph_digest: Optional SHA-256 hex to enforce graph binding.
    """
    if not record.signatures:
        return _reject(record, "missing_offerer_signature")

    # Check offerer
    offerer_valid = any(
        verify_model_signature(record, sig, pub)
        for sig in record.signatures
        for pub in offerer_public_keys
    )
    if not offerer_valid:
        reason: AgreementVerificationReason = (
            "missing_offerer_signature"
            if len(record.signatures) < 1
            else "invalid_offerer_signature"
        )
        return _reject(record, reason)

    # Check responder
    responder_valid = any(
        verify_model_signature(record, sig, pub)
        for sig in record.signatures
        for pub in responder_public_keys
    )
    if not responder_valid:
        reason = (
            "missing_responder_signature"
            if len(record.signatures) < 2
            else "invalid_responder_signature"
        )
        return _reject(record, reason)

    # Optional graph-digest binding
    if expected_graph_digest is not None and record.graph_digest != expected_graph_digest:
        return _reject(record, "graph_digest_mismatch")

    return AgreementVerificationResult(
        accepted=True,
        reason="accepted",
        agreement_id=record.agreement_id,
        offerer_sovereign_id=record.offerer_sovereign_id,
        responder_sovereign_id=record.responder_sovereign_id,
    )
