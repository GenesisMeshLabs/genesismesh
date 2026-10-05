"""Operator signatures for Network Authority admin requests.

An admin request carries four headers: ``X-Admin-Key-Id``,
``X-Admin-Timestamp``, ``X-Admin-Nonce`` and ``X-Admin-Signature``. The
signature is Ed25519 over a canonical JSON payload (sorted keys, no
whitespace, ASCII escapes).

Version 2 (v1.0.2) binds the signature to the request it authorises:

* ``method`` -- the HTTP method, upper case;
* ``path`` -- the request path as the Network Authority serves it, without
  the query string (for example ``/admin/recognition-treaties/<id>/revoke``);
* ``query`` -- every query parameter as ``{name: [values...]}`` in the order
  sent (``{}`` when there are none);
* ``audience`` -- the public key (base64) of the Network Authority the
  request is for, as in its genesis block and ``/sovereign.json``
  (``network_authority.public_key``). Unlike the network name, which its
  operator chooses, it differs between any two Network Authorities, so a
  request signed for one is refused by every other;
* ``body`` -- the JSON request body (``{}`` for requests without one).

Version 1 signed only the body, key ID, timestamp and nonce. Network
Authorities refuse it: 1.0.2 accepted it while ``NA_ADMIN_LEGACY_SIGNATURES``
was ``accept``, and 1.1.0 removed that setting.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from .signing import SigningKeyLike, sign_data

ADMIN_SIGNATURE_VERSION = 2

ADMIN_HEADERS = ("X-Admin-Key-Id", "X-Admin-Timestamp", "X-Admin-Nonce", "X-Admin-Signature")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_query(query: Optional[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Return query parameters as ``{name: [values...]}`` with string values.

    A scalar value becomes a one-item list; a list or tuple keeps its order.
    """
    if not query:
        return {}
    normalized: dict[str, list[str]] = {}
    for name, value in query.items():
        values: Iterable[Any] = value if isinstance(value, (list, tuple)) else [value]
        normalized[str(name)] = [str(item) for item in values]
    return normalized


def admin_signing_payload(
    *,
    method: str,
    path: str,
    audience: str,
    body: Any,
    key_id: str,
    timestamp: str,
    nonce: str,
    query: Optional[Mapping[str, Any]] = None,
) -> bytes:
    """Return the version 2 canonical bytes an operator signs."""
    # The decoded path may itself contain '?' (from %3F in an identifier), so
    # only its leading '/' is checked; query parameters are passed separately.
    if not path.startswith("/"):
        raise ValueError("admin request path must start with '/'")
    return _canonical_json({
        "v": ADMIN_SIGNATURE_VERSION,
        "method": method.upper(),
        "path": path,
        "query": normalize_query(query),
        "audience": audience,
        "body": {} if body is None else body,
        "key_id": key_id,
        "timestamp": timestamp,
        "nonce": nonce,
    })


def legacy_admin_signing_payload(*, body: Any, key_id: str, timestamp: str, nonce: str) -> bytes:
    """Return the version 1 canonical bytes (body only, no request binding).

    Network Authorities refuse version 1; this builds the reference vectors
    and lets tests prove the refusal.
    """
    return _canonical_json({
        "body": {} if body is None else body,
        "key_id": key_id,
        "timestamp": timestamp,
        "nonce": nonce,
    })


def sign_admin_request(
    private_key: SigningKeyLike,
    key_id: str,
    *,
    method: str,
    path: str,
    audience: str,
    body: Any = None,
    query: Optional[Mapping[str, Any]] = None,
    timestamp: Optional[str] = None,
    nonce: Optional[str] = None,
) -> dict[str, str]:
    """Return the four admin headers for one request (signature version 2)."""
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    nonce = nonce or str(uuid.uuid4())
    payload = admin_signing_payload(
        method=method,
        path=path,
        audience=audience,
        body=body,
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        query=query,
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(payload, private_key),
    }
