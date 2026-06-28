"""Demo: Human Oversight -- DualSignedCommitments for high-stakes actions.

Run from repository root:
    python docs/examples/assets/scripts/human-oversight-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-human-oversight.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-human-oversight.png"
TITLE = "Genesis Mesh -- Human Oversight"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.oversight import HumanOversightPolicy
    from genesis_mesh.trust.oversight import (
        approve_commitment,
        evaluate_oversight_policy,
        propose_commitment,
        verify_dual_signed_commitment,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Human Oversight Demo")
    step("    High-stakes actions require a DualSignedCommitment (agent + human)")
    step()

    kp_agent = generate_keypair()
    kp_human = generate_keypair()

    policy = HumanOversightPolicy(
        policy_id="bank-a-oversight-v1",
        agreement_id="agr-demo-001",
        human_sovereign_id="bank-a-human",
        allowed_capabilities=["transactions.read", "payments.write"],
        counterparty_allowlist=["partner-x"],
        value_threshold=10000,
        allowed_hours=None,
        frequency_limit=(3600, 5),
        created_at=_NOW,
        signature=None,
    )

    step("==> Step 1: Low-risk read action -- automatic approval")
    low_risk = {"capability": "transactions.read", "value": 0}
    eval_auto = evaluate_oversight_policy(
        policy=policy,
        proposed_action=low_risk,
        requesting_sovereign_id="partner-x",
        recent_action_count=2,
        anomaly=False,
        now=_NOW,
    )
    step(f"    action   : {low_risk['capability']}")
    step(f"    result   : {eval_auto.result}")
    step()

    step("==> Step 2: High-value payment -- escalated to human_approve")
    high_risk = {"capability": "payments.write", "value": 50000}
    eval_escalate = evaluate_oversight_policy(
        policy=policy,
        proposed_action=high_risk,
        requesting_sovereign_id="partner-x",
        recent_action_count=2,
        anomaly=False,
        now=_NOW,
    )
    step(f"    action   : {high_risk['capability']} (value $50,000 > threshold $10,000)")
    step(f"    result   : {eval_escalate.result}")
    step(f"    reasons  : {eval_escalate.escalation_reasons}")
    step()

    step("==> Step 3: Agent proposes commitment -- awaits human approval")
    request, _ = propose_commitment(
        policy=policy,
        proposed_action=high_risk,
        requesting_sovereign_id="partner-x",
        agent_signing_key=kp_agent.private_key,
        issued_by="partner-x-agent",
        approval_window_seconds=300,
        now=_NOW,
    )
    step(f"    request_id : {request.request_id}")
    step(f"    escalation : {request.escalation_level}")
    step(f"    expires_at : {request.expires_at.isoformat()}")
    step()

    step("==> Step 4: Human operator approves -- DualSignedCommitment issued")
    response, commitment = approve_commitment(
        request=request,
        policy=policy,
        human_signing_key=kp_human.private_key,
        issued_by="bank-a-human-operator",
        note="Approved after verifying counterparty identity",
        now=_NOW,
    )
    step(f"    commitment_id : {commitment.commitment_id}")
    step(f"    responded_at  : {response.responded_at.isoformat()}")
    step(f"    note          : {response.response_note}")
    step()

    step("==> Step 5: Verify dual-signed commitment offline")
    vr = verify_dual_signed_commitment(
        commitment=commitment,
        agent_public_keys=[kp_agent.public_key_b64],
        human_public_keys=[kp_human.public_key_b64],
        request=request,
        at_time=_NOW,
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("VERIFIED: high-stakes action gated; dual-signature verified offline")
    step(f"          commitment_id = {commitment.commitment_id}")
    step(f"          both agent + human signatures required")
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
