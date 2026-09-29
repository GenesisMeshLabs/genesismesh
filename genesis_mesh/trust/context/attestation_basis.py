"""Attestation basis for boundary evaluation (v0.58.1).

A request may be evaluated under a MembershipAttestation instead of an
AgreementRecord.  ``assess_attestation_basis`` turns the attestation and the
revocation state the Network Authority observed into an ``AttestationBasis``;
the attestation gates below read only that basis and the ContextRecord.

The caller (the NA) performs the I/O -- loading the attestation, its stored
status and the imported revocation feed -- and passes the results in.  This
module does no I/O and never reads the clock except through ``at``.

Fail closed: a missing, tampered, revoked, expired or not-yet-valid
attestation, or a requester other than its subject, denies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from ...crypto import verify_model_signature
from ...models.context import AttestationBinding, ContextRecord, GateResult
from ...models.sovereign import MembershipAttestation

AttestationFailure = Literal[
    "attestation_not_found",
    "attestation_invalid",
    "attestation_revoked",
    "attestation_subject_mismatch",
    "attestation_expired",
    "attestation_not_yet_valid",
]

#: gate_name -> trace gate_type for the attestation gates.
ATTESTATION_GATE_TYPES: dict[str, str] = {
    "attestation_status": "AttestationStatusGate",
    "attestation_validity": "AttestationValidityGate",
}

#: Claim key listing the capabilities an attestation permits.
CAPABILITIES_CLAIM = "capabilities"


@dataclass(frozen=True)
class AttestationBasis:
    """An attestation and the checks the NA ran on it.

    ``status_failure`` covers existence, signature, revocation and subject;
    the validity window is checked per request by ``attestation_validity_gate``.
    """

    attestation_id: str
    attestation: MembershipAttestation | None
    status_failure: AttestationFailure | None
    status_detail: str
    revocation_seq_checked: int

    @property
    def verified(self) -> bool:
        """True when the attestation exists and its signature verified."""
        return self.attestation is not None and self.status_failure not in (
            "attestation_not_found",
            "attestation_invalid",
        )

    def binding(self) -> AttestationBinding:
        """Signed decision binding for this basis."""
        att = self.attestation
        return AttestationBinding(
            attestation_id=self.attestation_id,
            subject_id=att.subject_id if att else None,
            issuer_sovereign_id=att.issuer_sovereign_id if att else None,
            attestation_digest=att.digest() if att else None,
            revocation_seq_checked=self.revocation_seq_checked,
        )

    def facts(self) -> dict[str, Any] | None:
        """Read-only fact root for policy gates; None unless the signature verified."""
        if not self.verified or self.attestation is None:
            return None
        att = self.attestation
        return {
            "subject_id": att.subject_id,
            "roles": list(att.roles),
            "claims": dict(att.claims),
        }


def assess_attestation_basis(
    attestation_id: str,
    attestation: MembershipAttestation | None,
    *,
    issuer_public_keys: Sequence[str],
    stored_status: str | None,
    feed_revoked: bool,
    revocation_seq_checked: int,
    requester_id: str,
) -> AttestationBasis:
    """Check existence, signature, revocation and subject of an attestation.

    ``stored_status`` is the NA's issuer-side status for the attestation;
    ``feed_revoked`` is True when an imported revocation feed lists it.
    """

    def _basis(failure: AttestationFailure | None, detail: str) -> AttestationBasis:
        return AttestationBasis(
            attestation_id=attestation_id,
            attestation=attestation,
            status_failure=failure,
            status_detail=detail,
            revocation_seq_checked=revocation_seq_checked,
        )

    if attestation is None:
        return _basis("attestation_not_found", f"attestation {attestation_id!r} is not in the NA store")
    if attestation.attestation_id != attestation_id:
        return _basis("attestation_invalid", "stored attestation does not match the requested id")
    if not attestation.signatures or not any(
        verify_model_signature(attestation, sig, key)
        for sig in attestation.signatures
        for key in issuer_public_keys
    ):
        return _basis("attestation_invalid", "attestation signature does not verify")
    if stored_status == "revoked" or feed_revoked:
        source = "an imported revocation feed" if feed_revoked and stored_status != "revoked" else "its issuer"
        return _basis("attestation_revoked", f"attestation was revoked by {source}")
    if attestation.status != "active" or (stored_status is not None and stored_status != "active"):
        status = stored_status if stored_status not in (None, "active") else attestation.status
        return _basis("attestation_revoked", f"attestation status is {status!r}, not 'active'")
    if requester_id != attestation.subject_id:
        return _basis("attestation_subject_mismatch", "requester is not the attestation subject")
    return _basis(None, "attestation is active, signed by a trusted key, and not revoked")


def attestation_status_gate(basis: AttestationBasis) -> GateResult:
    """Pass when the attestation exists, verifies, is not revoked and names the requester."""
    return GateResult(
        gate_name="attestation_status",
        passed=basis.status_failure is None,
        detail=basis.status_detail if basis.status_failure is None else f"{basis.status_failure}: {basis.status_detail}",
    )


def attestation_validity_gate(basis: AttestationBasis, context: ContextRecord) -> GateResult:
    """Pass when the request time is within [valid_from, expires_at]."""
    att = basis.attestation
    if att is None:
        return GateResult(gate_name="attestation_validity", passed=False, detail="attestation_not_found: no attestation")
    at = context.requested_at
    window = f"[{att.valid_from.isoformat()}, {att.expires_at.isoformat()}]"
    if at < att.valid_from:
        return GateResult(
            gate_name="attestation_validity", passed=False,
            detail=f"attestation_not_yet_valid: request at {at.isoformat()} is before {window}",
        )
    if at > att.expires_at:
        return GateResult(
            gate_name="attestation_validity", passed=False,
            detail=f"attestation_expired: request at {at.isoformat()} is after {window}",
        )
    return GateResult(
        gate_name="attestation_validity", passed=True,
        detail=f"request at {at.isoformat()} is within {window}",
    )


def attested_capabilities(basis: AttestationBasis) -> list[str] | None:
    """Return ``claims.capabilities`` when it is a list of strings, else None."""
    if basis.attestation is None:
        return None
    caps = basis.attestation.claims.get(CAPABILITIES_CLAIM)
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        return None
    return caps


def attestation_capability_gate(basis: AttestationBasis, context: ContextRecord) -> GateResult:
    """Pass when the requested capability is in ``claims.capabilities``."""
    caps = attested_capabilities(basis)
    if caps is None:
        return GateResult(
            gate_name="capability_check", passed=False,
            detail="attestation has no capabilities claim (list of strings)",
        )
    if context.requested_capability in caps:
        return GateResult(
            gate_name="capability_check", passed=True,
            detail=f"capability '{context.requested_capability}' is in attested capabilities",
        )
    return GateResult(
        gate_name="capability_check", passed=False,
        detail=f"capability '{context.requested_capability}' not in attested capabilities {caps!r}",
    )


def attestation_freshness_gate(context: ContextRecord) -> GateResult:
    """``freshness_check`` against a commitment of 0: attestations carry none.

    Revocation freshness comes from the NA's own check at evaluation time,
    recorded as ``AttestationBinding.revocation_seq_checked``.
    """
    return GateResult(
        gate_name="freshness_check", passed=True,
        detail=f"freshness seq {context.context_freshness_seq} >= commitment 0",
    )


def attestation_gate_inputs(gate_name: str, basis: AttestationBasis, context: ContextRecord) -> dict[str, Any]:
    """Proof inputs for the attestation-basis gates (identifiers only, no claims)."""
    att = basis.attestation
    if gate_name == "attestation_status":
        return {
            "attestation_id": basis.attestation_id,
            "found": att is not None,
            "revocation_seq_checked": basis.revocation_seq_checked,
        }
    if gate_name == "attestation_validity":
        out: dict[str, Any] = {"requested_at": context.requested_at.isoformat()}
        if att is not None:
            out.update(valid_from=att.valid_from.isoformat(), expires_at=att.expires_at.isoformat())
        return out
    if gate_name == "capability_check":
        return {"requested_capability": context.requested_capability, "capabilities": attested_capabilities(basis)}
    if gate_name == "freshness_check":
        return {"context_freshness_seq": context.context_freshness_seq, "freshness_commitment": 0}
    return {}


def attestation_denial_reason(gate: GateResult) -> str | None:
    """Stable reason code for a failed attestation gate, else None."""
    if gate.gate_name in ATTESTATION_GATE_TYPES:
        return gate.detail.split(":", 1)[0]
    return None

