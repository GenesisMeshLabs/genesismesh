"""Trust logic for Process-Level Execution Mediation (v0.45).

validate_mediation_request() is the single authoritative check before
GenesisGuard spawns any subprocess.  It is intentionally simple and
deterministic — no LLM reasoning, no network calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import BoundaryDecision
from ..models.invocation_token import InvocationToken
from ..models.mediation import (
    ExecutionMediationRequest,
    MediatedExecutionReceipt,
    MediationRejection,
)

MediationRejectionReason = Literal[
    "invalid_request_signature",
    "decision_not_found",
    "decision_expired",
    "capability_not_authorized",
    "token_budget_exhausted",
    "token_expired",
    "command_not_in_allowlist",
    "subprocess_blocked",
]


def validate_mediation_request(
    request: ExecutionMediationRequest,
    boundary_decision: BoundaryDecision | None,
    agent_public_keys: list[str],
    *,
    token: InvocationToken | None = None,
    command_allowlist: list[str] | None = None,
    use_count: int = 0,
    at_time: datetime | None = None,
) -> tuple[bool, MediationRejectionReason | None]:
    """Validate all authorization artifacts before spawning subprocess.

    Checks (in order):
    1. Request signature valid (agent key)
    2. BoundaryDecision present, authorized=True, not expired
    3. requested_capability in IBCT capabilities (when token provided)
    4. Token not expired; budget not exhausted (when token provided)
    5. subprocess_command[0] in command_allowlist (when allowlist provided)
    """
    import base64  # noqa: PLC0415

    t = at_time or datetime.now(timezone.utc)

    # 1. Signature
    if request.signature is not None:
        verified = False
        for pub_b64 in agent_public_keys:
            pub = nacl.signing.VerifyKey(base64.b64decode(pub_b64))
            if verify_model_signature(request, request.signature, pub):
                verified = True
                break
        if not verified:
            return False, "invalid_request_signature"
    else:
        return False, "invalid_request_signature"

    # 2. Decision
    if boundary_decision is None:
        return False, "decision_not_found"
    if not boundary_decision.authorized:
        return False, "capability_not_authorized"
    if t > boundary_decision.decision_valid_until:
        return False, "decision_expired"

    # 3+4. Token checks
    if token is not None:
        if request.requested_capability not in token.capabilities:
            return False, "capability_not_authorized"
        if t > token.expires_at:
            return False, "token_expired"
        if token.max_invocations is not None and use_count >= token.max_invocations:
            return False, "token_budget_exhausted"

    # 5. Command allowlist
    if command_allowlist is not None:
        if not request.subprocess_command:
            return False, "command_not_in_allowlist"
        if request.subprocess_command[0] not in command_allowlist:
            return False, "command_not_in_allowlist"

    return True, None


def create_mediated_execution_receipt(
    request: ExecutionMediationRequest,
    subprocess_pid: int,
    guard_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    exit_code: int | None = None,
    now: datetime | None = None,
) -> MediatedExecutionReceipt:
    now = now or datetime.now(timezone.utc)
    receipt = MediatedExecutionReceipt(
        request_id=request.request_id,
        agent_sovereign_id=request.agent_sovereign_id,
        capability=request.requested_capability,
        decision_id=request.decision_id,
        subprocess_pid=subprocess_pid,
        subprocess_exit_code=exit_code,
        mediated_at=now,
        completed_at=now if exit_code is not None else None,
        guard_sovereign_id=guard_sovereign_id,
    )
    sig = sign_model(receipt, signing_key, guard_sovereign_id)
    return receipt.model_copy(update={"signature": sig})
