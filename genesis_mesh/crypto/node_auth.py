"""Node request signatures (``/join``, ``/heartbeat``, ``/renew`` and ``/node/*``).

A node signs the JSON body of each request with its node key. The signature
is Ed25519 over the canonical JSON of the body without its ``signature``
field: sorted keys, no whitespace, ASCII escapes (``\\uXXXX`` for every
character outside ASCII) and Python's float form (``0.1``, ``1e-07``). The
body carries ``timestamp`` (RFC 3339, within 300 seconds of the Network
Authority's clock) and ``nonce`` (single use per node key), which the
signature therefore covers.

v1.7.0 (beta) adds two things for the edge agent:

* the ``/node/*`` routes also require ``purpose`` (the route) and
  ``audience`` (the Network Authority's public key) inside the signed body,
  so a captured request cannot be replayed against another route or NA;
* an edge ``/join`` carries an executor key, which proves possession by
  co-signing the body (``executor_signature``, over the body without
  ``signature`` and ``executor_signature``) before the node key signs it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Mapping

from .signing import SigningKeyLike, sign_data

#: The ``purpose`` each node-scoped route requires (v1.7.0).
NODE_PURPOSES: dict[str, str] = {
    "/node/boundary/evaluate": "node_boundary_evaluate",
    "/node/state": "node_state",
    "/node/evidence/resource-head": "node_resource_head",
}

#: Prefix of an edge node's executor key ID (v1.7.0).
EXECUTOR_KEY_ID_PREFIX = "edge-"


def _canonical_json(body: Mapping[str, Any], *excluded: str) -> bytes:
    payload = {k: v for k, v in sorted(body.items()) if k not in excluded}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def node_signing_payload(body: Mapping[str, Any]) -> bytes:
    """The bytes a node key signs: the canonical body without ``signature``."""
    return _canonical_json(body, "signature")


def executor_proof_payload(body: Mapping[str, Any]) -> bytes:
    """The bytes an executor key signs at ``/join``: the body without either signature."""
    return _canonical_json(body, "signature", "executor_signature")


def decode_ed25519_public_key(public_key_b64: Any) -> bytes:
    """The raw 32 bytes of a base64 Ed25519 public key; ``ValueError`` otherwise."""
    if not isinstance(public_key_b64, str) or not public_key_b64:
        raise ValueError("public key must be a non-empty base64 string")
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public key is not valid base64") from exc
    if len(raw) != 32:
        raise ValueError("public key must be 32 bytes")
    return raw


def executor_key_id(public_key_b64: str) -> str:
    """An edge node's executor key ID: ``edge-`` and the first 32 hex digits of SHA-256 of the raw key."""
    raw = decode_ed25519_public_key(public_key_b64)
    return EXECUTOR_KEY_ID_PREFIX + hashlib.sha256(raw).hexdigest()[:32]


def sign_node_request(body: Mapping[str, Any], node_key: SigningKeyLike) -> dict[str, Any]:
    """``body`` with its node ``signature`` added (it must already carry ``timestamp`` and ``nonce``)."""
    signed = dict(body)
    signed.pop("signature", None)
    signed["signature"] = sign_data(node_signing_payload(signed), node_key)
    return signed


def sign_executor_proof(body: Mapping[str, Any], executor_key: SigningKeyLike) -> dict[str, Any]:
    """``body`` with its ``executor_signature`` added; sign it with the node key afterwards."""
    signed = {k: v for k, v in body.items() if k not in ("signature", "executor_signature")}
    signed["executor_signature"] = sign_data(executor_proof_payload(signed), executor_key)
    return signed
