"""Trust logic for Process-Level Execution Mediation (v0.45).

validate_mediation_request() is the single authoritative check before
GenesisGuard spawns any subprocess.  It is intentionally simple and
deterministic — no LLM reasoning, no network calls.
"""

from __future__ import annotations

import shlex
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
    "invalid_decision_signature",
    "decision_expired",
    "capability_not_authorized",
    "token_budget_exhausted",
    "token_expired",
    "command_not_in_allowlist",
    "subprocess_blocked",
]

# A trailing '...' token marks an allowlist entry as a prefix rule.
_PREFIX_SENTINEL = "..."

# Flags that hand the interpreter arbitrary code.  A prefix rule whose fixed
# part ends in one of these permits anything; the guard warns about it.
EVAL_FLAGS = frozenset({"-c", "-e", "--eval", "--command"})


def parse_allowlist_entry(entry: str) -> tuple[list[str], bool]:
    """Parse one command-allowlist entry into (fixed_tokens, is_prefix_rule).

    Entries are *full command lines*, not program names.  A trailing '...'
    marks a prefix rule: the fixed tokens must match the head of the command
    and the tail is unconstrained.

    Raises ValueError for an entry that cannot be enforced as written.
    """
    try:
        tokens = shlex.split(entry)
    except ValueError as exc:
        raise ValueError(
            f"command allowlist entry {entry!r} is not a valid command line: {exc}"
        ) from exc
    if not tokens:
        raise ValueError(f"command allowlist entry {entry!r} is empty")

    if tokens[-1] != _PREFIX_SENTINEL:
        return tokens, False

    fixed = tokens[:-1]
    if len(fixed) < 2:
        raise ValueError(
            f"command allowlist entry {entry!r} is a prefix rule with fewer than two "
            "fixed tokens, which permits every invocation of that program — the exact "
            "first-word-only matching this check exists to prevent.  Name the "
            "sub-command or script explicitly, e.g. 'python /opt/report.py ...'."
        )
    return fixed, True


def validate_command_allowlist(command_allowlist: list[str] | None) -> None:
    """Raise ValueError unless the allowlist is present, non-empty and enforceable.

    Called at guard construction so a misconfigured allowlist stops the guard
    at start-up rather than being discovered one request at a time.
    """
    if not command_allowlist:
        raise ValueError(
            "GenesisGuard refuses to start without a command allowlist.  Pass a "
            "non-empty list of full command lines, e.g. "
            "['python /opt/report.py --daily', 'python /opt/report.py ...']."
        )
    for entry in command_allowlist:
        parse_allowlist_entry(entry)


def _command_allowed(command: list[str], allowlist: list[str]) -> bool:
    """True if the *whole* command matches an allowlist entry.

    Matching is on the full argv, never on the program name alone: allowing
    'bash' must not allow `bash -c '<anything>'`.
    """
    for entry in allowlist:
        fixed, is_prefix = parse_allowlist_entry(entry)
        if is_prefix:
            if len(command) >= len(fixed) and command[: len(fixed)] == fixed:
                return True
        elif command == fixed:
            return True
    return False


def validate_mediation_request(
    request: ExecutionMediationRequest,
    boundary_decision: BoundaryDecision | None,
    agent_public_keys: list[str],
    *,
    operator_public_keys: list[str] | None = None,
    token: InvocationToken | None = None,
    command_allowlist: list[str] | None = None,
    use_count: int = 0,
    at_time: datetime | None = None,
) -> tuple[bool, MediationRejectionReason | None]:
    """Validate all authorization artifacts before spawning subprocess.

    Checks (in order):
    1. Request signature valid (agent key)
    2. BoundaryDecision present and signed by a known operator key
    3. BoundaryDecision authorized=True, not expired
    4. requested_capability in IBCT capabilities (when token provided)
    5. Token not expired; budget not exhausted (when token provided)
    6. Full subprocess_command matches command_allowlist

    Fails closed: a missing operator key set or a missing/empty allowlist
    denies the request.  Omitting either is a configuration error, never a
    licence to skip the check.
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

    # 2. Decision present and signed by an operator key the guard was given.
    #    Without this the guard acts on a decision anyone could have written.
    if boundary_decision is None:
        return False, "decision_not_found"
    #    Reuses verify_boundary_decision(), the same verifier the CLI and the NA
    #    boundary route use, so the guard and the control plane agree on what a
    #    valid decision is.  No operator keys => any() over an empty list => reject.
    from .context.decisions import verify_boundary_decision  # noqa: PLC0415

    decision_check = verify_boundary_decision(
        boundary_decision, list(operator_public_keys or []), now=t
    )
    if not decision_check.accepted:
        if decision_check.reason == "decision_expired":
            return False, "decision_expired"
        return False, "invalid_decision_signature"

    # 3. Decision content
    if not boundary_decision.authorized:
        return False, "capability_not_authorized"
    if t > boundary_decision.decision_valid_until:
        return False, "decision_expired"

    # 4+5. Token checks
    if token is not None:
        if request.requested_capability not in token.capabilities:
            return False, "capability_not_authorized"
        if t > token.expires_at:
            return False, "token_expired"
        if token.max_invocations is not None and use_count >= token.max_invocations:
            return False, "token_budget_exhausted"

    # 6. Command allowlist — fail closed: no allowlist means nothing is permitted,
    #    and the whole command is matched, not just the program name.
    if not command_allowlist or not request.subprocess_command:
        return False, "command_not_in_allowlist"
    try:
        allowed = _command_allowed(request.subprocess_command, command_allowlist)
    except ValueError:
        # Unenforceable entry: deny rather than raise.  validate_command_allowlist()
        # surfaces the real error loudly at guard start-up.
        return False, "command_not_in_allowlist"
    if not allowed:
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
