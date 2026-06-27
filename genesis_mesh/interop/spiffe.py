"""SPIFFE/SVID interop bridge.

Maps GenesisMesh AgreementRecord to a SPIFFE-compatible representation.
This bridge is lossy: SPIFFE uses X.509 or JWT SVIDs; we produce a JSON
summary that carries the essential SPIFFE fields for ecosystem integration.

The output is NOT a self-contained SPIFFE SVID (it does not include an X.509
certificate or a signed JWT).  It carries the GM signatures as extensions so
the receiving system can verify them against GM public keys if desired.
"""

from __future__ import annotations

from typing import Any

from ..models.agreement import AgreementRecord


_BRIDGE_SOURCE = "genesis_mesh.interop.spiffe"
_BRIDGE_VERSION = "1.0"


def agreement_to_svid(record: AgreementRecord) -> dict[str, Any]:
    """Map an AgreementRecord to a SPIFFE SVID-like representation.

    Produces a JSON dict with:
    - ``spiffe_id`` in the form ``spiffe://<trust-domain>/<agreement-id>``
    - ``trust_domain`` derived from ``offerer_sovereign_id``
    - SVID validity window from ``agreed_terms``
    - GM signatures preserved as ``gm_signatures`` extensions

    Args:
        record: A fully-signed AgreementRecord.

    Returns:
        Dict suitable for JSON serialisation.  Carrying the ``_gm_bridge_source``
        sentinel so consumers know the provenance.
    """
    terms = record.agreed_terms
    return {
        "_gm_bridge_source": _BRIDGE_SOURCE,
        "_gm_bridge_version": _BRIDGE_VERSION,
        "spiffe_id": f"spiffe://{record.offerer_sovereign_id}/{record.agreement_id}",
        "trust_domain": record.offerer_sovereign_id,
        "workload_id": record.agreement_id,
        "subject": record.responder_sovereign_id,
        "valid_from": terms.valid_from.isoformat(),
        "valid_until": terms.valid_until.isoformat(),
        "capabilities": list(terms.capabilities),
        "freshness_commitment": terms.freshness_commitment,
        "parties": {
            "offerer": record.offerer_sovereign_id,
            "responder": record.responder_sovereign_id,
        },
        "gm_agreement_id": record.agreement_id,
        "gm_signatures": [sig.model_dump(mode="json") for sig in record.signatures],
    }


def svid_to_agreement_fields(svid: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort reverse mapping: extract GM fields from a bridge SVID.

    Returns a dict of GM fields if the SVID carries GM bridge metadata,
    otherwise None.  Does NOT reconstruct a signed AgreementRecord — the
    original signatures are in ``gm_signatures``.
    """
    if svid.get("_gm_bridge_source") != _BRIDGE_SOURCE:
        return None
    return {
        "agreement_id": svid.get("gm_agreement_id"),
        "offerer_sovereign_id": svid.get("parties", {}).get("offerer"),
        "responder_sovereign_id": svid.get("parties", {}).get("subject") or svid.get("subject"),
        "capabilities": svid.get("capabilities", []),
        "valid_from": svid.get("valid_from"),
        "valid_until": svid.get("valid_until"),
        "gm_signatures": svid.get("gm_signatures", []),
    }
