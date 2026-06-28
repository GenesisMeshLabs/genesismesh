"""Demo: Process-Level Mediation -- GenesisGuard subprocess authorization.

Run from repository root:
    python docs/examples/assets/scripts/process-level-mediation-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-process-level-mediation.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-process-level-mediation.png"
TITLE = "Genesis Mesh -- Process-Level Mediation"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair, sign_model
    from genesis_mesh.models.mediation import ExecutionMediationRequest
    from genesis_mesh.trust.mediation import (
        create_mediated_execution_receipt,
        validate_mediation_request,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Process-Level Mediation Demo")
    step("    GenesisGuard mediates subprocess execution against BoundaryDecision")
    step()

    agreement, _kp_a, _kp_b = make_agreement(
        "org-a", "bank-a",
        capabilities=["transactions.read"],
        now=_NOW,
    )
    decision, kp_op = make_boundary_decision(agreement, capability="transactions.read", now=_NOW)
    kp_agent = generate_keypair()
    guard_id = "org-a-guard"

    step("==> Step 1: BoundaryDecision from BoundaryEngine evaluation")
    step(f"    decision_id    : {decision.decision_id}")
    step(f"    authorized     : {decision.authorized}")
    step(f"    valid_until    : {decision.decision_valid_until.isoformat()}")
    step()

    step("==> Step 2: Agent creates signed ExecutionMediationRequest")
    request = ExecutionMediationRequest(
        agent_sovereign_id="org-a",
        requested_capability="transactions.read",
        decision_id=decision.decision_id,
        subprocess_command=["fetch_transactions", "--account", "acc-001"],
        allowed_env_vars=["GM_API_KEY"],
        requested_at=_NOW,
    )
    sig = sign_model(request, kp_agent.private_key, "org-a")
    request = request.model_copy(update={"signature": sig})
    step(f"    request_id     : {request.request_id[:16]}...")
    step(f"    capability     : {request.requested_capability}")
    step(f"    command        : {request.subprocess_command}")
    step()

    step("==> Step 3: Validate mediation request -- authorized")
    ok, rejection = validate_mediation_request(
        request=request,
        boundary_decision=decision,
        agent_public_keys=[kp_agent.public_key_b64],
        at_time=_NOW,
    )
    step(f"    valid          : {ok}")
    step(f"    rejection      : {rejection}")
    step()

    step("==> Step 4: Create MediatedExecutionReceipt (subprocess PID 12345)")
    receipt = create_mediated_execution_receipt(
        request=request,
        subprocess_pid=12345,
        guard_sovereign_id=guard_id,
        signing_key=kp_op.private_key,
        exit_code=0,
        now=_NOW,
    )
    step(f"    receipt_id     : {receipt.receipt_id[:16]}...")
    step(f"    subprocess_pid : {receipt.subprocess_pid}")
    step(f"    exit_code      : {receipt.subprocess_exit_code}")
    step(f"    guard          : {receipt.guard_sovereign_id}")
    step()

    step("==> Step 5: Denied case -- command not in allowlist")
    ok_denied, rejection_denied = validate_mediation_request(
        request=request,
        boundary_decision=decision,
        agent_public_keys=[kp_agent.public_key_b64],
        command_allowlist=["safe_export"],
        at_time=_NOW,
    )
    step(f"    command        : {request.subprocess_command[0]!r}")
    step(f"    allowlist      : ['safe_export']")
    step(f"    valid          : {ok_denied}")
    step(f"    rejection      : {rejection_denied}")
    step()

    step("VERIFIED: process execution mediated and receipted; unauthorized commands blocked")
    step(f"          receipt_id = {receipt.receipt_id[:16]}...")
    step(f"          BLOCKED reason = {rejection_denied}")
    return transcript


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=GIF)
    p.add_argument("--png-output", type=Path, default=PNG)
    p.add_argument("--no-gif", action="store_true")
    args = p.parse_args()

    lines = run_demo()
    if not args.no_gif:
        render_png(lines, TITLE, args.png_output)
        render_gif(lines, TITLE, args.output)
        print(f"\nPNG -> {args.png_output}")
        print(f"GIF -> {args.output}")


if __name__ == "__main__":
    main()
