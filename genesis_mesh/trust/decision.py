"""Trust decision engine: turn a recognition graph into an operator verdict.

``explain_trust_path`` answers a binary question: does one sovereign currently
recognize another?  Operators need more than a boolean.  They need a verdict
that folds in revocation pressure, treaty lifecycle, and requested scope, plus
the signals that justify it, so the result can be acted on and later proven.

This module computes that verdict (``allow`` / ``warn`` / ``block`` /
``escalate``) over the same recognition-graph export the Connectome consumes
(see ``NetworkAuthorityTrustStore.export_recognition_graph``).  It is pure: no
I/O, no signing.  Receipts are built from a :class:`TrustDecision` in
``genesis_mesh.trust.receipt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .connectome import explain_trust_path

TrustVerdict = Literal["allow", "warn", "block", "escalate"]
SignalSeverity = Literal["info", "warn", "escalate", "block"]

_SEVERITY_RANK: dict[SignalSeverity, int] = {
    "info": 0,
    "warn": 1,
    "escalate": 2,
    "block": 3,
}

_SEVERITY_TO_VERDICT: dict[SignalSeverity, TrustVerdict] = {
    "info": "allow",
    "warn": "warn",
    "escalate": "escalate",
    "block": "block",
}


@dataclass(frozen=True)
class TrustSignal:
    """One justification contributing to a trust verdict."""

    code: str
    severity: SignalSeverity
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class TrustDecision:
    """Structured, serializable outcome of a trust evaluation."""

    source_sovereign_id: str
    target_sovereign_id: str
    verdict: TrustVerdict
    reason: str
    requested_roles: list[str]
    trusted: bool
    trust_path: list[dict[str, Any]]
    hop_count: int
    signals: list[TrustSignal]
    evaluated_at: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation suitable for receipts and Atlas."""
        return {
            "source_sovereign_id": self.source_sovereign_id,
            "target_sovereign_id": self.target_sovereign_id,
            "verdict": self.verdict,
            "reason": self.reason,
            "requested_roles": list(self.requested_roles),
            "trusted": self.trusted,
            "trust_path": self.trust_path,
            "hop_count": self.hop_count,
            "signals": [s.to_dict() for s in self.signals],
            "evaluated_at": self.evaluated_at,
        }


def _treaty_scope_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map active treaty IDs to their recognition scope."""
    scopes: dict[str, dict[str, Any]] = {}
    for treaty in graph.get("active_treaties", []):
        treaty_id = str(treaty.get("treaty_id", ""))
        if treaty_id:
            scopes[treaty_id] = treaty.get("scope") or {}
    return scopes


def _scope_signals(
    path: list[dict[str, Any]],
    requested_roles: list[str],
    scopes: dict[str, dict[str, Any]],
) -> list[TrustSignal]:
    """Block roles not permitted at every hop on the trust path.

    An empty ``allowed_roles`` list on a treaty means "any role is permitted",
    matching the ``RecognitionTreatyScope.allows_roles`` contract.
    """
    if not requested_roles:
        return []

    blocked: list[str] = []
    for role in requested_roles:
        for edge in path:
            scope = scopes.get(str(edge.get("treaty_id", "")), {})
            allowed = scope.get("allowed_roles") or []
            if allowed and role not in allowed:
                blocked.append(role)
                break

    if blocked:
        return [
            TrustSignal(
                code="scope_not_in_treaty",
                severity="block",
                detail=f"roles not granted across the full path: {', '.join(sorted(set(blocked)))}",
            )
        ]
    return []


def _lifecycle_signals(path: list[dict[str, Any]]) -> list[TrustSignal]:
    """Warn when any treaty on the path is approaching expiry."""
    signals: list[TrustSignal] = []
    for edge in path:
        if edge.get("lifecycle_state") == "expiring_soon" or edge.get("expiry_risk"):
            signals.append(
                TrustSignal(
                    code="treaty_expiring_soon",
                    severity="warn",
                    detail=(
                        f"treaty {edge.get('treaty_id')} "
                        f"({edge.get('from')} -> {edge.get('to')}) "
                        f"expires {edge.get('expires_at')}"
                    ),
                )
            )
    return signals


def _revocation_pressure_signals(
    graph: dict[str, Any],
    path: list[dict[str, Any]],
) -> list[TrustSignal]:
    """Escalate when imported revocations target a sovereign on the active path.

    An active path can still be live while a revocation feed propagates against
    one of its issuers.  That state deserves human review rather than a silent
    allow, because the feed may not have reached all consumers yet.
    """
    path_sovereigns = {str(edge.get("from", "")) for edge in path} | {
        str(edge.get("to", "")) for edge in path
    }
    signals: list[TrustSignal] = []
    for item in graph.get("revoked_trust_material", []):
        if item.get("type") != "membership_attestation":
            continue
        issuer = str(item.get("issuer_sovereign_id", ""))
        if issuer and issuer in path_sovereigns:
            signals.append(
                TrustSignal(
                    code="recognition_under_revocation_pressure",
                    severity="escalate",
                    detail=(
                        f"revocation feed {item.get('feed_id')} "
                        f"seq {item.get('sequence')} targets {issuer} on the trust path"
                    ),
                )
            )
    return signals


def evaluate_trust_decision(
    graph: dict[str, Any],
    source_sovereign_id: str,
    target_sovereign_id: str,
    *,
    requested_roles: list[str] | None = None,
    now: datetime | None = None,
) -> TrustDecision:
    """Evaluate a trust decision from source toward target over a graph export.

    Verdict precedence (highest wins): ``block`` > ``escalate`` > ``warn`` >
    ``allow``.  An unblocked active path with no risk signals yields ``allow``.

    Args:
        graph: Recognition graph export from
            ``NetworkAuthorityTrustStore.export_recognition_graph``.
        source_sovereign_id: The sovereign evaluating trust.
        target_sovereign_id: The sovereign being evaluated.
        requested_roles: Optional roles the source wants to accept from the
            target under the active treaty scope.
        now: Evaluation timestamp; defaults to ``datetime.now(UTC)``.
    """
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    roles = list(requested_roles or [])

    path_result = explain_trust_path(graph, source_sovereign_id, target_sovereign_id)
    trusted = bool(path_result.get("trusted"))
    path = list(path_result.get("path", []))
    hop_count = int(path_result.get("hop_count", 0))

    if not trusted:
        signal = TrustSignal(
            code=str(path_result.get("reason", "no_active_treaty_path")),
            severity="block",
            detail="no active recognition path between sovereigns",
        )
        return TrustDecision(
            source_sovereign_id=source_sovereign_id,
            target_sovereign_id=target_sovereign_id,
            verdict="block",
            reason=signal.code,
            requested_roles=roles,
            trusted=False,
            trust_path=path,
            hop_count=hop_count,
            signals=[signal],
            evaluated_at=evaluated_at,
        )

    scopes = _treaty_scope_by_id(graph)
    signals: list[TrustSignal] = []
    signals.extend(_scope_signals(path, roles, scopes))
    signals.extend(_revocation_pressure_signals(graph, path))
    signals.extend(_lifecycle_signals(path))

    if signals:
        top = max(signals, key=lambda s: _SEVERITY_RANK[s.severity])
        verdict = _SEVERITY_TO_VERDICT[top.severity]
        reason = top.code
    else:
        verdict = "allow"
        reason = "active_treaty_path"
        signals = [
            TrustSignal(
                code="active_treaty_path",
                severity="info",
                detail=f"active recognition path with {hop_count} hop(s)",
            )
        ]

    return TrustDecision(
        source_sovereign_id=source_sovereign_id,
        target_sovereign_id=target_sovereign_id,
        verdict=verdict,
        reason=reason,
        requested_roles=roles,
        trusted=True,
        trust_path=path,
        hop_count=hop_count,
        signals=signals,
        evaluated_at=evaluated_at,
    )
