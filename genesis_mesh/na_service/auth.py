"""Authentication helpers for Network Authority HTTP requests."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from flask import request

from ..crypto import verify_signature
from .errors import ForbiddenError

logger = logging.getLogger(__name__)


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
    except Exception as exc:
        # Authentication must fail closed even if audit persistence is
        # unavailable, but the lost event must stay observable: count it and
        # log event_type/reason only (never signed bodies or nonces).
        service.audit_write_failures += 1
        logger.error(
            "Failed to persist %s audit event (reason=%s): %s",
            event_type,
            details.get("reason"),
            exc,
        )


OperatorTier = Literal["standard", "privileged"]

OPERATOR_TIERS: tuple[str, ...] = ("standard", "privileged")

# A privileged key satisfies a standard requirement; the reverse is not true.
_TIER_RANK: dict[str, int] = {"standard": 0, "privileged": 1}


def load_operator_key_tiers(specs: Optional[list[str]]) -> dict[str, str]:
    """Load operator key tiers from ``key-id=tier`` CLI specifications."""
    tiers: dict[str, str] = {}
    for spec in specs or []:
        if "=" not in spec:
            raise ValueError("Operator key tier must use key-id=tier format")
        key_id, tier = spec.split("=", 1)
        key_id = key_id.strip()
        tier = tier.strip()
        if not key_id or not tier:
            raise ValueError("Operator key id and tier must be non-empty")
        if tier not in OPERATOR_TIERS:
            raise ValueError(
                f"Unknown operator tier {tier!r} for key {key_id!r}; "
                f"expected one of {', '.join(OPERATOR_TIERS)}"
            )
        tiers[key_id] = tier
    return tiers


def validate_operator_key_tiers(
    operator_public_keys: dict[str, str], operator_key_tiers: dict[str, str]
) -> None:
    """Raise unless every configured operator key declares a valid tier (F-21).

    Called at service construction so a misconfigured deployment fails loudly at
    boot rather than at 3am with an unexpected 403.  There is deliberately no
    default tier: defaulting to privileged would leave every existing key
    all-powerful (the flat model this fix exists to end), and defaulting to
    standard would silently strip revocation and policy publication from the
    very keys an operator reaches for during an incident.
    """
    missing = sorted(k for k in operator_public_keys if k not in operator_key_tiers)
    if missing:
        raise ValueError(
            "operator keys have no tier: "
            + ", ".join(repr(k) for k in missing)
            + f". Declare each as one of {', '.join(OPERATOR_TIERS)}."
        )

    bad = sorted(
        (k, v) for k, v in operator_key_tiers.items() if v not in OPERATOR_TIERS
    )
    if bad:
        raise ValueError(
            "operator keys have an unknown tier: "
            + ", ".join(f"{k!r}={v!r}" for k, v in bad)
            + f". Expected one of {', '.join(OPERATOR_TIERS)}."
        )

    unknown = sorted(k for k in operator_key_tiers if k not in operator_public_keys)
    if unknown:
        raise ValueError(
            "operator key tiers reference unconfigured keys: "
            + ", ".join(repr(k) for k in unknown)
        )


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
        # Keep the caller-facing message identical to a plain bad signature;
        # the underlying exception stays server-side only.
        logger.warning("Signature verification raised for scope %s: %s", nonce_scope, exc)
        return False, "Invalid signature"

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


def verify_admin_request(
    service, data: dict, required_tier: OperatorTier = "standard"
) -> tuple[bool, str | None]:
    """Verify operator-key authentication and authorisation for admin endpoints.

    Returns (False, message) for authentication failures, which callers turn
    into 401. Raises ForbiddenError (403) when the key authenticates but its
    tier does not permit the operation.
    """
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

    # F-21: a key revoked at runtime is refused here, before its signature is
    # verified and before its nonce is consumed. A revoked key therefore cannot
    # perform any admin action -- including revoking other operators -- and
    # cannot burn nonces.
    #
    # The caller is told only "Unknown admin key" either way: whoever holds a
    # stolen key learns nothing about whether the compromise was noticed. The
    # audit event carries the real reason.
    public_key = service.operator_public_keys.get(key_id)
    if not public_key or service.db.is_operator_key_revoked(key_id):
        _audit_auth_failure(
            service,
            "admin_auth_failed",
            {
                "key_id": key_id,
                "reason": "revoked_key" if public_key else "unknown_key",
            },
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

    # F-21: authorisation, after authentication has succeeded. The request is
    # genuine, so its nonce stays spent -- it simply asks for more than this key
    # is allowed. That is a 403, not a 401, and is raised rather than returned:
    # every caller turns a False return into 401, and conflating "who are you?"
    # with "you may not do that" would lose a distinction that matters during an
    # incident.
    holder_tier = service.operator_key_tiers.get(key_id)
    if _TIER_RANK.get(holder_tier or "", -1) < _TIER_RANK[required_tier]:
        _audit_auth_failure(
            service,
            "admin_authz_denied",
            {
                "key_id": key_id,
                "scope": scope,
                "holder_tier": holder_tier,
                "required_tier": required_tier,
                "reason": "insufficient_operator_tier",
            },
        )
        raise ForbiddenError(
            f"This operation requires the {required_tier} operator tier.",
            code="insufficient_operator_tier",
        )

    return True, None
