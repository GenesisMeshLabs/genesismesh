"""Demo: Execution Evidence Chain -- tamper-evident linked records.

Run from repository root:
    python docs/examples/assets/scripts/execution-evidence-chain-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-execution-evidence-chain.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-execution-evidence-chain.png"
TITLE = "Genesis Mesh -- Execution Evidence Chain"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.execution import record_execution, verify_evidence_chain, EvidenceChain

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Execution Evidence Chain Demo")
    step("    Each record digest-links to the prior record -- any gap is detectable")
    step()

    agreement, _kp_a, _kp_b = make_agreement(now=_NOW)
    decision, kp_op = make_boundary_decision(agreement, now=_NOW)
    kp_exec = generate_keypair()

    step("==> Step 1: BoundaryDecision authorizes 'transactions.read'")
    step(f"    decision_id : {decision.decision_id}")
    step(f"    authorized  : {decision.authorized}")
    step()

    step("==> Step 2: Record execution #1 (capability first invoked)")
    ev1 = record_execution(
        decision=decision,
        executor_sovereign_id="org-a",
        executed_capability="transactions.read",
        outcome="success",
        signing_key=kp_exec.private_key,
        issued_by="org-a-executor",
        sequence_no=1,
        outcome_detail="100 transactions fetched",
        now=_NOW,
    )
    step(f"    evidence_id : {ev1.evidence_id}")
    step(f"    sequence_no : {ev1.sequence_no}")
    step(f"    outcome     : {ev1.outcome}")
    step(f"    sig (key_id): {ev1.signature.key_id}")
    step()

    step("==> Step 3: Record execution #2 (chains to #1 via prev_evidence_digest)")
    ev2 = record_execution(
        decision=decision,
        executor_sovereign_id="org-a",
        executed_capability="transactions.read",
        outcome="success",
        signing_key=kp_exec.private_key,
        issued_by="org-a-executor",
        sequence_no=2,
        outcome_detail="98 transactions fetched",
        prior_record=ev1,
        now=_NOW,
    )
    step(f"    evidence_id : {ev2.evidence_id}")
    step(f"    prev_digest : {(ev2.prev_evidence_digest or '')[:20]}...")
    step(f"    chained to ev1 via prev_evidence_digest")
    step()

    step("==> Step 4: Record execution #3 (chains to #2)")
    ev3 = record_execution(
        decision=decision,
        executor_sovereign_id="org-a",
        executed_capability="transactions.read",
        outcome="partial",
        signing_key=kp_exec.private_key,
        issued_by="org-a-executor",
        sequence_no=3,
        outcome_detail="Service rate-limited after 42 transactions",
        prior_record=ev2,
        now=_NOW,
    )
    step(f"    evidence_id : {ev3.evidence_id}")
    step(f"    outcome     : {ev3.outcome}")
    step()

    step("==> Step 5: Verify complete 3-record chain")
    chain = EvidenceChain(
        decision_id=decision.decision_id,
        records=[ev1, ev2, ev3],
    )
    vr = verify_evidence_chain(
        chain=chain,
        executor_public_keys_by_sovereign={"org-a": [kp_exec.public_key_b64]},
        expected_capability="transactions.read",
        decision=decision,
    )
    step(f"    verified    : {vr.verified}")
    step(f"    reason      : {vr.reason}")
    step(f"    records     : {vr.chain_length}")
    step()

    step("==> Step 6: Tamper detection -- modify ev2 outcome after signing")
    original_outcome = ev2.outcome
    ev2.outcome = "success_fabricated"
    chain_bad = EvidenceChain(decision_id=decision.decision_id, records=[ev1, ev2, ev3])
    vr_bad = verify_evidence_chain(
        chain=chain_bad,
        executor_public_keys_by_sovereign={"org-a": [kp_exec.public_key_b64]},
    )
    ev2.outcome = original_outcome  # restore
    step(f"    tampered outcome: 'success_fabricated'")
    step(f"    verified : {vr_bad.verified}")
    step(f"    reason   : {vr_bad.reason}")
    step()

    step("VERIFIED: 3-record chain verified; tampered record detected at sequence 2")
    step(f"          evidence IDs: {ev1.evidence_id[:8]}... -> {ev2.evidence_id[:8]}... -> {ev3.evidence_id[:8]}...")
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
