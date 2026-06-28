"""Demo: Justification Proofs -- signed gate trace per BoundaryDecision.

Run from repository root:
    python docs/examples/assets/scripts/justification-proofs-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision_with_proof
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-justification-proofs.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-justification-proofs.png"
TITLE = "Genesis Mesh -- Justification Proofs"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.trust.justification import verify_justification_proof

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Justification Proofs Demo")
    step("    Why was this decision authorized? Answer: a signed gate trace.")
    step()

    agreement, _, _ = make_agreement(now=_NOW)
    decision, proof, kp_op = make_boundary_decision_with_proof(agreement, now=_NOW)

    step("==> Step 1: BoundaryDecision with JustificationProof (evaluate_with_proof)")
    step(f"    decision_id : {decision.decision_id}")
    step(f"    authorized  : {decision.authorized}")
    for g in decision.gate_results:
        step(f"    gate [{g.gate_name:22s}]: passed={g.passed}")
    step()

    step("==> Step 2: JustificationProof contains signed gate trace")
    step(f"    proof_id    : {proof.proof_id}")
    step(f"    trace.traced_at : {proof.trace.traced_at.isoformat()}")
    step(f"    gate entries: {len(proof.trace.entries)}")
    step(f"    issuer      : {proof.issuer_sovereign_id}")
    step()

    step("==> Step 3: Verify proof offline -- no sovereign connection needed")
    vr = verify_justification_proof(
        proof=proof,
        issuer_public_keys=[kp_op.public_key_b64],
        decision=decision,
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("==> Step 4: Tamper-check -- modified proof issuer_sovereign_id after signing")
    original_issuer = proof.issuer_sovereign_id
    proof.issuer_sovereign_id = "attacker-sovereign"
    vr_bad = verify_justification_proof(
        proof=proof,
        issuer_public_keys=[kp_op.public_key_b64],
        decision=decision,
    )
    proof.issuer_sovereign_id = original_issuer
    step(f"    tampered issuer_sovereign_id -> attacker-sovereign")
    step(f"    valid  : {vr_bad.valid}  reason: {vr_bad.reason}")
    step()

    step("VERIFIED: gate trace signed and verified offline; tampering detected")
    step(f"          proof_id    = {proof.proof_id}")
    step(f"          decision_id = {decision.decision_id}")
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
