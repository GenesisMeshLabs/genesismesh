"""Derived recognition-treaty lifecycle state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_EXPIRY_WARNING_HOURS = 72


def treaty_lifecycle(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    expiring_within_hours: int = DEFAULT_EXPIRY_WARNING_HOURS,
) -> dict[str, Any]:
    """Derive operator-facing lifecycle state from a persisted treaty row."""
    current = now or datetime.now(timezone.utc)
    treaty = row["treaty"]
    persisted_status = row.get("status", treaty.status)
    reason = row.get("revocation_reason")
    replacement_id = _replacement_id(reason)
    if persisted_status == "revoked":
        state = "replaced" if replacement_id else "revoked"
        return {
            "state": state,
            "expiry_risk": "none",
            "seconds_until_expiry": None,
            "expires_at": treaty.expires_at.isoformat(),
            "revoked_at": row.get("revoked_at"),
            "revocation_reason": reason,
            "replacement_treaty_id": replacement_id,
        }

    seconds = int((treaty.expires_at - current).total_seconds())
    if seconds <= 0:
        state = "expired"
        risk = "expired"
    elif seconds <= 24 * 3600:
        state = "expiring_soon"
        risk = "high"
    elif seconds <= expiring_within_hours * 3600:
        state = "expiring_soon"
        risk = "medium"
    else:
        state = "active"
        risk = "low"

    return {
        "state": state,
        "expiry_risk": risk,
        "seconds_until_expiry": max(seconds, 0),
        "expires_at": treaty.expires_at.isoformat(),
        "revoked_at": row.get("revoked_at"),
        "revocation_reason": reason,
        "replacement_treaty_id": None,
    }


def is_lifecycle_active(lifecycle: dict[str, Any]) -> bool:
    """Return whether lifecycle state currently contributes active trust."""
    return lifecycle.get("state") in {"active", "expiring_soon"}


def _replacement_id(reason: str | None) -> str | None:
    if not reason:
        return None
    for prefix in ("replaced_by:", "renewed_by:"):
        if reason.startswith(prefix):
            return reason.split(":", 1)[1] or None
    return None
