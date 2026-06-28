"""Demo: Distributed Consensus Authorization -- K-of-N threshold.

Run from repository root:
    python docs/examples/assets/scripts/distributed-consensus-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision_with_proof
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-distributed-consensus.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-distributed-consensus.png"
TITLE = "Genesis Mesh -- Distributed Consensus Authorization"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.consensus import (
        assemble_consensus_proof,
        cast_validator_vote,
        issue_ephemeral_identity,
        verify_consensus_proof,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Distributed Consensus Authorization Demo")
    step("    K-of-N threshold: 3-of-5 validators must approve")
    step()

    agreement, _, _ = make_agreement(now=_NOW)
    decision, jp, kp_op = make_boundary_decision_with_proof(agreement, now=_NOW)

    kp_validators = [generate_keypair() for _ in range(5)]
    validator_ids = [f"validator-{c}" for c in "ABCDE"]
    kp_assembler = generate_keypair()
    kp_ei = generate_keypair()

    step("==> Step 1: JustificationProof from BoundaryDecision")
    step(f"    proof_id : {jp.proof_id}")
    step(f"    decision : {decision.decision_id}")
    step()

    step("==> Step 2: 5 validators cast votes (3 approve, 2 deny)")
    votes = []
    for i, (kp_v, v_id) in enumerate(zip(kp_validators, validator_ids)):
        approve = i < 3
        vote = cast_validator_vote(
            justification_proof=jp,
            validator_sovereign_id=v_id,
            vote=approve,
            signing_key=kp_v.private_key,
            reason="approved by policy" if approve else "risk threshold exceeded",
            now=_NOW,
        )
        votes.append(vote)
        step(f"    {v_id}: {'APPROVE' if approve else 'DENY   '}")
    step()

    step("==> Step 3: Assemble ConsensusProof (3-of-5 threshold met)")
    proof = assemble_consensus_proof(
        justification_proof=jp,
        votes=votes,
        required_threshold=3,
        validator_sovereign_ids=validator_ids,
        assembler_signing_key=kp_assembler.private_key,
        issued_by="org-a-assembler",
        valid_for_seconds=120,
        cascade_threshold=0.4,
        now=_NOW,
    )
    step(f"    proof_id      : {proof.proof_id}")
    step(f"    threshold     : {proof.required_threshold}")
    approve_count = sum(1 for v in proof.votes if v.vote)
    step(f"    approve_count : {approve_count}")
    cascade_dig = getattr(proof, 'cascade_assessment_digest', 'n/a')
    step(f"    cascade dig   : {str(cascade_dig)[:24]}...")
    step()

    step("==> Step 4: Issue EphemeralExecutionIdentity (valid 120s)")
    identity = issue_ephemeral_identity(
        consensus_proof=proof,
        bearer_sovereign_id="partner-x",
        allowed_capabilities=["transactions.read"],
        signing_key=kp_ei.private_key,
        issued_by="org-a-identity-issuer",
        valid_for_seconds=120,
        now=_NOW,
    )
    step(f"    identity_id  : {identity.identity_id}")
    step(f"    bearer       : {identity.bearer_sovereign_id}")
    step(f"    capabilities : {identity.allowed_capabilities}")
    step()

    step("==> Step 5: Verify consensus proof")
    validator_pub_keys = {v: kp.public_key_b64 for v, kp in zip(validator_ids, kp_validators)}
    vr = verify_consensus_proof(
        proof=proof,
        validator_public_keys=validator_pub_keys,
        assembler_public_keys=[kp_assembler.public_key_b64],
        cascade_threshold=0.4,
        at_time=_NOW,
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("VERIFIED: 3-of-5 threshold met; ephemeral identity issued; cascade safe")
    step(f"          identity_id = {identity.identity_id}")
    step(f"          3 approve votes, cascade assessment stored in proof digest")
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
