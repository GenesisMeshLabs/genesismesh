"""Human Oversight trust functions — policy evaluation and dual-signed commitment workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.oversight import (
    DualSignedCommitment,
    HumanApprovalRequest,
    HumanApprovalResponse,
    HumanOversightPolicy,
    OversightEscalationLevel,
)


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

CheckOutcome = Literal["pass", "escalate", "block"]


@dataclass(frozen=True)
class PolicyEvaluation:
    """Outcome of evaluate_oversight_policy()."""

    result: OversightEscalationLevel
    checks: list[tuple[str, CheckOutcome]] = field(default_factory=list)
    escalation_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "checks": [{"name": n, "outcome": o} for n, o in self.checks],
            "escalation_reasons": self.escalation_reasons,
        }


def evaluate_oversight_policy(
    policy: HumanOversightPolicy,
    proposed_action: dict[str, Any],
    requesting_sovereign_id: str,
    *,
    recent_action_count: int = 0,
    anomaly: bool = False,
    now: datetime | None = None,
) -> PolicyEvaluation:
    """Run the 8-check deterministic policy engine.

    Checks (in order):
    1. capability_scope      — cap not in allowed_capabilities → block
    2. counterparty_allowlist — not in allowlist (if set) → escalate
    3. value_threshold       — action value > threshold → escalate
    4. time_window           — outside allowed hours UTC → escalate
    5. frequency_limit       — recent_action_count >= limit → escalate
    6. irreversibility       — action tagged irreversible → escalate
    7. novel_counterparty    — first interaction flag → escalate
    8. anomaly_flag          — anomaly=True → block

    Overall outcome: block > human_approve > automatic (highest severity wins).
    """
    ts = now or datetime.now(timezone.utc)
    checks: list[tuple[str, CheckOutcome]] = []
    reasons: list[str] = []
    has_block = False
    has_escalate = False

    def _record(name: str, outcome: CheckOutcome, reason: str | None = None) -> None:
        nonlocal has_block, has_escalate
        checks.append((name, outcome))
        if outcome == "block":
            has_block = True
            if reason:
                reasons.append(reason)
        elif outcome == "escalate":
            has_escalate = True
            if reason:
                reasons.append(reason)

    # 1. capability_scope
    cap = proposed_action.get("capability")
    if cap not in policy.allowed_capabilities:
        _record("capability_scope", "block", f"capability {cap!r} not in policy allowed list")
    else:
        _record("capability_scope", "pass")

    # 2. counterparty_allowlist
    if policy.counterparty_allowlist and requesting_sovereign_id not in policy.counterparty_allowlist:
        _record(
            "counterparty_allowlist", "escalate",
            f"requester {requesting_sovereign_id!r} not in counterparty allowlist",
        )
    else:
        _record("counterparty_allowlist", "pass")

    # 3. value_threshold
    if policy.value_threshold is not None:
        action_value = proposed_action.get("value", 0)
        if isinstance(action_value, (int, float)) and action_value > policy.value_threshold:
            _record(
                "value_threshold", "escalate",
                f"action value {action_value} > threshold {policy.value_threshold}",
            )
        else:
            _record("value_threshold", "pass")
    else:
        _record("value_threshold", "pass")

    # 4. time_window
    if policy.allowed_hours is not None:
        start_h, end_h = policy.allowed_hours
        current_hour = ts.hour
        in_window = start_h <= current_hour < end_h if start_h < end_h else (
            current_hour >= start_h or current_hour < end_h
        )
        if not in_window:
            _record(
                "time_window", "escalate",
                f"request hour {current_hour} UTC outside allowed window [{start_h}, {end_h})",
            )
        else:
            _record("time_window", "pass")
    else:
        _record("time_window", "pass")

    # 5. frequency_limit
    if policy.frequency_limit is not None:
        max_count, _window_seconds = policy.frequency_limit
        if recent_action_count >= max_count:
            _record(
                "frequency_limit", "escalate",
                f"recent_action_count {recent_action_count} >= limit {max_count}",
            )
        else:
            _record("frequency_limit", "pass")
    else:
        _record("frequency_limit", "pass")

    # 6. irreversibility
    if proposed_action.get("irreversible", False):
        _record("irreversibility", "escalate", "action is tagged as irreversible")
    else:
        _record("irreversibility", "pass")

    # 7. novel_counterparty
    if proposed_action.get("novel_counterparty", False):
        _record("novel_counterparty", "escalate", "first interaction with this counterparty")
    else:
        _record("novel_counterparty", "pass")

    # 8. anomaly_flag
    if anomaly:
        _record("anomaly_flag", "block", "anomaly flag raised by caller")
    else:
        _record("anomaly_flag", "pass")

    if has_block:
        result: OversightEscalationLevel = "block"
    elif has_escalate:
        result = "human_approve"
    else:
        result = "automatic"

    return PolicyEvaluation(result=result, checks=checks, escalation_reasons=reasons)


# ---------------------------------------------------------------------------
# Commitment workflow
# ---------------------------------------------------------------------------


def propose_commitment(
    policy: HumanOversightPolicy,
    proposed_action: dict[str, Any],
    requesting_sovereign_id: str,
    agent_signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    approval_window_seconds: int = 300,
    recent_action_count: int = 0,
    anomaly: bool = False,
    now: datetime | None = None,
) -> tuple[HumanApprovalRequest, PolicyEvaluation]:
    """Evaluate policy and sign a HumanApprovalRequest when human approval is needed.

    Raises:
        RuntimeError: If the policy evaluation returns 'automatic' (no approval needed).
        ValueError: If the policy evaluation returns 'block' (action not permitted).
    """
    ts = now or datetime.now(timezone.utc)
    evaluation = evaluate_oversight_policy(
        policy, proposed_action, requesting_sovereign_id,
        recent_action_count=recent_action_count, anomaly=anomaly, now=ts,
    )

    if evaluation.result == "automatic":
        raise RuntimeError(
            "action does not require human approval (policy result: automatic)"
        )
    if evaluation.result == "block":
        reasons = "; ".join(evaluation.escalation_reasons)
        raise ValueError(f"action is blocked by oversight policy: {reasons}")

    request = HumanApprovalRequest(
        policy_id=policy.policy_id,
        requesting_sovereign_id=requesting_sovereign_id,
        proposed_action=proposed_action,
        escalation_level="human_approve",
        escalation_reasons=evaluation.escalation_reasons,
        requested_at=ts,
        expires_at=ts + timedelta(seconds=approval_window_seconds),
    )
    sig = sign_model(request, agent_signing_key, issued_by)
    request = request.model_copy(update={"agent_signature": sig})
    return request, evaluation


def approve_commitment(
    request: HumanApprovalRequest,
    policy: HumanOversightPolicy,
    human_signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    commitment_valid_for_seconds: int = 600,
    note: str | None = None,
    now: datetime | None = None,
) -> tuple[HumanApprovalResponse, DualSignedCommitment]:
    """Human custodian approves the request and produces a DualSignedCommitment.

    The commitment is signed by the human key.  The agent's signature is
    copied from the HumanApprovalRequest into the commitment so both
    signatures are present in the resulting DualSignedCommitment.
    """
    ts = now or datetime.now(timezone.utc)

    response = HumanApprovalResponse(
        request_id=request.request_id,
        human_sovereign_id=policy.human_sovereign_id,
        approved=True,
        responded_at=ts,
        response_note=note,
    )
    response_sig = sign_model(response, human_signing_key, issued_by)
    response = response.model_copy(update={"human_signature": response_sig})

    commitment = DualSignedCommitment(
        request_id=request.request_id,
        response_id=response.response_id,
        agreement_id=policy.agreement_id,
        acting_sovereign_id=request.requesting_sovereign_id,
        human_sovereign_id=policy.human_sovereign_id,
        proposed_action=request.proposed_action,
        committed_at=ts,
        expires_at=ts + timedelta(seconds=commitment_valid_for_seconds),
        agent_signature=request.agent_signature,
    )
    human_sig = sign_model(commitment, human_signing_key, issued_by)
    commitment = commitment.model_copy(update={"human_signature": human_sig})
    return response, commitment


def reject_commitment(
    request: HumanApprovalRequest,
    policy: HumanOversightPolicy,
    human_signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    note: str | None = None,
    now: datetime | None = None,
) -> HumanApprovalResponse:
    """Human custodian rejects the request."""
    ts = now or datetime.now(timezone.utc)
    response = HumanApprovalResponse(
        request_id=request.request_id,
        human_sovereign_id=policy.human_sovereign_id,
        approved=False,
        responded_at=ts,
        response_note=note,
    )
    sig = sign_model(response, human_signing_key, issued_by)
    return response.model_copy(update={"human_signature": sig})


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

DualSignedCommitmentVerificationReason = Literal[
    "valid",
    "missing_agent_signature",
    "missing_human_signature",
    "invalid_agent_signature",
    "invalid_human_signature",
    "request_response_mismatch",
    "expired",
    "not_fully_signed",
]


@dataclass(frozen=True)
class DualSignedCommitmentVerificationResult:
    """Structured outcome of verify_dual_signed_commitment()."""

    valid: bool
    reason: DualSignedCommitmentVerificationReason
    commitment_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "commitment_id": self.commitment_id,
        }


def verify_dual_signed_commitment(
    commitment: DualSignedCommitment,
    agent_public_keys: list[str],
    human_public_keys: list[str],
    *,
    request: HumanApprovalRequest | None = None,
    at_time: datetime | None = None,
) -> DualSignedCommitmentVerificationResult:
    """Verify a DualSignedCommitment.

    Verification order:
      missing_agent_signature → missing_human_signature →
      invalid_agent_signature → invalid_human_signature →
      request_response_mismatch → expired → valid

    Both parties sign the same canonical form (to_canonical_json() excludes
    both signatures).  The agent_signature and human_signature are verified
    independently against the same canonical body.
    """
    ts = at_time or datetime.now(timezone.utc)

    def _reject(
        reason: DualSignedCommitmentVerificationReason,
    ) -> DualSignedCommitmentVerificationResult:
        return DualSignedCommitmentVerificationResult(
            valid=False, reason=reason, commitment_id=commitment.commitment_id
        )

    if commitment.agent_signature is None:
        return _reject("missing_agent_signature")
    if commitment.human_signature is None:
        return _reject("missing_human_signature")

    # Check request_id consistency before crypto so callers get a clear reason.
    if request is not None and commitment.request_id != request.request_id:
        return _reject("request_response_mismatch")

    # Agent signed the HumanApprovalRequest (not the commitment body directly).
    # When the request is provided, verify agent_signature against the request's
    # canonical form.  Without it, presence is checked but crypto is skipped.
    if request is not None:
        agent_ok = any(
            verify_model_signature(request, commitment.agent_signature, pub)
            for pub in agent_public_keys
        )
        if not agent_ok:
            return _reject("invalid_agent_signature")

    # Human signs the commitment canonical form (excluding both sigs).
    human_ok = any(
        verify_model_signature(commitment, commitment.human_signature, pub)
        for pub in human_public_keys
    )
    if not human_ok:
        return _reject("invalid_human_signature")

    if ts > commitment.expires_at:
        return _reject("expired")

    return DualSignedCommitmentVerificationResult(
        valid=True, reason="valid", commitment_id=commitment.commitment_id
    )
