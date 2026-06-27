"""JOSE/JWT interop bridge.

Maps a BoundaryDecision to a JWT suitable for REST API consumption.
Uses EdDSA (RFC 8037) with Ed25519, so the JWT can be verified by any
JOSE library that supports OKP key types.

Manual JWT implementation:
- Header: {"alg": "EdDSA", "crv": "Ed25519", "kid": key_id}
- Payload: standard JWT claims + "gm:*" namespace for GM-specific fields
- Signature: base64url(nacl.sign(header_b64 + "." + payload_b64))

No external JWT library required — uses PyNaCl (already a project dependency).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import nacl.exceptions
import nacl.signing

from ..models.context import BoundaryDecision


_BRIDGE_SOURCE = "genesis_mesh.interop.jose"
_BRIDGE_VERSION = "1.0"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Re-pad to multiple of 4
    pad = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def decision_to_jwt(
    decision: BoundaryDecision,
    signing_key: nacl.signing.SigningKey,
    *,
    key_id: str = "gm-bridge",
) -> str:
    """Encode a BoundaryDecision as a signed EdDSA JWT.

    Standard claims:
    - ``jti``: decision_id
    - ``iss``: operator_sovereign_id
    - ``sub``: requester (context_id-based)
    - ``iat``: decision_made_at (Unix timestamp)
    - ``exp``: decision_valid_until (Unix timestamp)

    GM-specific claims (namespace ``gm:``):
    - ``gm:agreement_id``, ``gm:context_id``, ``gm:authorized``
    - ``gm:gate_results``, ``gm:denial_reason``

    Args:
        decision: The BoundaryDecision to encode.
        signing_key: Ed25519 signing key for the JWT signature.
        key_id: Key ID embedded in the JWT header.

    Returns:
        A compact serialisation JWT string (header.payload.signature).
    """
    header: dict[str, Any] = {
        "alg": "EdDSA",
        "crv": "Ed25519",
        "kid": key_id,
        "typ": "JWT",
    }
    payload: dict[str, Any] = {
        "jti": decision.decision_id,
        "iss": decision.operator_sovereign_id,
        "sub": f"gm:decision:{decision.decision_id}",
        "iat": int(decision.decision_made_at.timestamp()),
        "exp": int(decision.decision_valid_until.timestamp()),
        "gm:agreement_id": decision.agreement_id,
        "gm:context_id": decision.context_id,
        "gm:authorized": decision.authorized,
        "gm:gate_results": [g.model_dump(mode="json") for g in decision.gate_results],
        "gm:bridge_source": _BRIDGE_SOURCE,
        "gm:bridge_version": _BRIDGE_VERSION,
    }
    if decision.denial_reason:
        payload["gm:denial_reason"] = decision.denial_reason

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    sig = signing_key.sign(signing_input).signature
    sig_b64 = _b64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def jwt_to_decision_claims(
    token: str,
    verify_key_b64: str,
) -> dict[str, Any] | None:
    """Verify a GM-bridge JWT and return its claims.

    Verifies the EdDSA signature.  Returns the decoded payload dict if valid,
    None if the token is malformed or the signature does not verify.

    Args:
        token: Compact JWT string.
        verify_key_b64: Base64-encoded Ed25519 verify key.

    Returns:
        Payload dict with GM claims, or None on failure.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode()

    try:
        sig = _b64url_decode(sig_b64)
        vk_bytes = base64.b64decode(verify_key_b64)
        vk = nacl.signing.VerifyKey(vk_bytes)
        vk.verify(signing_input, sig)
    except (nacl.exceptions.BadSignatureError, Exception):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None

    return payload
