"""W3C Verifiable Credentials interop bridge.

Maps GenesisMesh TrustEvidence and AgreementRecord to W3C VC format.
The output is a JSON-LD VC dict with:
- Standard ``@context``, ``type``, ``id``, ``issuer``, ``issuanceDate``
- GM-specific ``credentialSubject`` fields
- GM signature preserved in ``proof`` (not a standard LD-Proof — see note)

Note: A proper W3C VC proof requires a Data Integrity suite (e.g., Ed25519
Signature 2020) which needs DID resolution.  We produce the structural VC
body and attach the raw GM signature as an extension.  A conformant DID
resolver can verify the signature against the GM public key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.agreement import AgreementRecord
from ..models.evidence import TrustEvidence


_BRIDGE_SOURCE = "genesis_mesh.interop.w3c_vc"
_BRIDGE_VERSION = "1.0"
_VC_CONTEXT = [
    "https://www.w3.org/2018/credentials/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1",
]


def trust_evidence_to_vc(evidence: TrustEvidence) -> dict[str, Any]:
    """Map a TrustEvidence record to a W3C Verifiable Credential.

    The ``issuer`` is derived from ``issuer_sovereign_id``.
    The ``credentialSubject.id`` is the source sovereign.

    Args:
        evidence: A signed TrustEvidence record.

    Returns:
        W3C VC dict with ``_gm_bridge_source`` sentinel.
    """
    return {
        "@context": _VC_CONTEXT,
        "type": ["VerifiableCredential", "GMTrustEvidence"],
        "id": f"urn:gm:evidence:{evidence.evidence_id}",
        "issuer": f"did:gm:{evidence.issuer_sovereign_id}",
        "issuanceDate": evidence.issued_at.isoformat(),
        "credentialSubject": {
            "id": f"did:gm:{evidence.source_sovereign_id}",
            "trustedBy": f"did:gm:{evidence.target_sovereign_id}",
            "verdict": evidence.verdict,
            "graphDigest": evidence.graph_digest,
            "signals": evidence.signals,
        },
        "proof": {
            "type": "Ed25519Signature2020",
            "verificationMethod": f"did:gm:{evidence.issuer_sovereign_id}#key-1",
            "proofPurpose": "assertionMethod",
            "_gm_signatures": [sig.model_dump(mode="json") for sig in evidence.signatures],
            "_gm_issued_by": evidence.issued_by,
        },
        "_gm_bridge_source": _BRIDGE_SOURCE,
        "_gm_bridge_version": _BRIDGE_VERSION,
    }


def agreement_to_vc(record: AgreementRecord) -> dict[str, Any]:
    """Map an AgreementRecord to a W3C Verifiable Credential.

    Both parties are represented in the ``credentialSubject``.
    Signatures from both parties are embedded in the ``proof`` section.

    Args:
        record: A fully-signed AgreementRecord.

    Returns:
        W3C VC dict.
    """
    terms = record.agreed_terms
    return {
        "@context": _VC_CONTEXT,
        "type": ["VerifiableCredential", "GMAgreementRecord"],
        "id": f"urn:gm:agreement:{record.agreement_id}",
        "issuer": f"did:gm:{record.offerer_sovereign_id}",
        "issuanceDate": record.established_at.isoformat(),
        "expirationDate": terms.valid_until.isoformat(),
        "credentialSubject": {
            "id": f"did:gm:{record.responder_sovereign_id}",
            "agreementWith": f"did:gm:{record.offerer_sovereign_id}",
            "capabilities": list(terms.capabilities),
            "validFrom": terms.valid_from.isoformat(),
            "validUntil": terms.valid_until.isoformat(),
            "freshnessCommitment": terms.freshness_commitment,
        },
        "proof": {
            "type": "Ed25519MultiSignature2020",
            "proofPurpose": "agreementBinding",
            "_gm_signatures": [sig.model_dump(mode="json") for sig in record.signatures],
        },
        "_gm_bridge_source": _BRIDGE_SOURCE,
        "_gm_bridge_version": _BRIDGE_VERSION,
    }


def vc_to_trust_evidence_fields(vc: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort reverse mapping: extract GM fields from a bridge VC.

    Returns GM field dict if the VC was produced by this bridge, None otherwise.
    Does NOT reconstruct a signed TrustEvidence.
    """
    if _BRIDGE_SOURCE not in str(vc.get("_gm_bridge_source", "")):
        return None
    if "GMTrustEvidence" not in vc.get("type", []):
        return None
    cs = vc.get("credentialSubject", {})
    proof = vc.get("proof", {})
    return {
        "evidence_id": vc.get("id", "").removeprefix("urn:gm:evidence:"),
        "issuer_sovereign_id": vc.get("issuer", "").removeprefix("did:gm:"),
        "source_sovereign_id": cs.get("id", "").removeprefix("did:gm:"),
        "target_sovereign_id": cs.get("trustedBy", "").removeprefix("did:gm:"),
        "verdict": cs.get("verdict"),
        "graph_digest": cs.get("graphDigest"),
        "issued_at": vc.get("issuanceDate"),
        "gm_signatures": proof.get("_gm_signatures", []),
        "gm_issued_by": proof.get("_gm_issued_by"),
    }
