"""Authentication helpers for Network Authority HTTP requests."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import request

from ..crypto import verify_signature


def _audit_auth_failure(service, event_type: str, details: dict) -> None:
    """Persist an auth failure without exposing signed request bodies."""
    try:
        service.db.add_audit_event(
            event_type,
            {
                **details,
                "remote_addr": request.remote_addr or "unknown",
            },
        )
    except Exception:
        # Authentication must fail closed even if audit persistence is unavailable.
        pass


def load_operator_public_keys(specs: Optional[list[str]]) -> dict[str, str]:
    """Load operator public keys from ``key_id=value`` CLI specifications."""
    operator_keys: dict[str, str] = {}
    for spec in specs or []:
        if "=" not in spec:
            raise ValueError("Operator key must use key-id=public-key-or-path format")
        key_id, value = spec.split("=", 1)
        key_id = key_id.strip()
        value = value.strip()
        if not key_id or not value:
            raise ValueError("Operator key id and value must be non-empty")
        path = Path(value)
        if path.exists():
            lines = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            value = "".join(lines)
        operator_keys[key_id] = value
    return operator_keys


def verify_node_request_signature(
    service,
    data: dict,
    node_public_key: str,
    scope: Optional[str] = None,
) -> tuple[bool, str | None]:
    """
    Verify a signed node API request with nonce replay protection.

    The request body must include ``signature``, ``timestamp``, and ``nonce``.
    The signature covers canonical JSON of the request body excluding the
    ``signature`` field.
    """
    signature_b64 = data.get("signature")
    timestamp_str = data.get("timestamp")
    nonce = data.get("nonce")

    if not signature_b64 or not timestamp_str or not nonce:
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": scope or f"node:{node_public_key}", "reason": "missing_fields"},
        )
        return False, "Missing authentication fields: signature, timestamp, and nonce required"

    try:
        request_time = datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": scope or f"node:{node_public_key}", "reason": "invalid_timestamp"},
        )
        return False, "Invalid timestamp format"

    now = datetime.now(timezone.utc)
    age = abs((now - request_time).total_seconds())
    if age > service._nonce_max_age:
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": scope or f"node:{node_public_key}", "reason": "stale_timestamp"},
        )
        return False, f"Request timestamp too old ({age:.0f}s > {service._nonce_max_age:.0f}s)"

    nonce_scope = scope or f"node:{node_public_key}"
    if service.db.has_nonce(nonce_scope, nonce):
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": nonce_scope, "nonce": nonce, "reason": "nonce_replay"},
        )
        return False, "Nonce already used (replay detected)"

    payload = {k: v for k, v in sorted(data.items()) if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    try:
        if not verify_signature(canonical.encode("utf-8"), signature_b64, node_public_key):
            _audit_auth_failure(
                service,
                "node_auth_failed",
                {"scope": nonce_scope, "reason": "invalid_signature"},
            )
            return False, "Invalid signature"
    except Exception as exc:
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": nonce_scope, "reason": "signature_error"},
        )
        return False, f"Signature verification error: {exc}"

    try:
        service.db.add_nonce(nonce_scope, nonce, now)
    except Exception:
        _audit_auth_failure(
            service,
            "node_auth_failed",
            {"scope": nonce_scope, "nonce": nonce, "reason": "nonce_replay"},
        )
        return False, "Nonce already used (replay detected)"

    service.db.cleanup_expired_nonces(int(service._nonce_max_age * 2))
    return True, None


def verify_admin_request(service, data: dict) -> tuple[bool, str | None]:
    """Verify operator-key authentication headers for admin endpoints."""
    key_id = request.headers.get("X-Admin-Key-Id")
    signature_b64 = request.headers.get("X-Admin-Signature")
    timestamp_str = request.headers.get("X-Admin-Timestamp")
    nonce = request.headers.get("X-Admin-Nonce")

    if not key_id or not signature_b64 or not timestamp_str or not nonce:
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id or "missing", "reason": "missing_headers"},
        )
        return False, "Missing admin authentication headers"

    public_key = service.operator_public_keys.get(key_id)
    if not public_key:
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "reason": "unknown_key"},
        )
        return False, "Unknown admin key"

    try:
        request_time = datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "reason": "invalid_timestamp"},
        )
        return False, "Invalid admin timestamp"

    now = datetime.now(timezone.utc)
    age = abs((now - request_time).total_seconds())
    if age > service._nonce_max_age:
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "reason": "stale_timestamp"},
        )
        return False, "Admin request timestamp too old"

    scope = f"admin:{key_id}"
    if service.db.has_nonce(scope, nonce):
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "scope": scope, "nonce": nonce, "reason": "nonce_replay"},
        )
        return False, "Admin nonce already used"

    canonical = json.dumps(
        {
            "body": data,
            "key_id": key_id,
            "timestamp": timestamp_str,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if not verify_signature(canonical.encode("utf-8"), signature_b64, public_key):
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "scope": scope, "reason": "invalid_signature"},
        )
        return False, "Invalid admin signature"

    try:
        service.db.add_nonce(scope, nonce, now)
    except Exception:
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {"key_id": key_id, "scope": scope, "nonce": nonce, "reason": "nonce_replay"},
        )
        return False, "Admin nonce already used"
    return True, None
