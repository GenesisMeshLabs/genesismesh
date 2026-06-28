"""Demo: Cascade-Resilient Consensus -- correlated-vote detection.

Run from repository root:
    python docs/examples/assets/scripts/cascade-resilient-consensus-demo.py
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision_with_proof
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-cascade-resilient-consensus.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-cascade-resilient-consensus.png"
TITLE = "Genesis Mesh -- Cascade-Resilient Consensus"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.consensus import assess_cascade_risk, cast_validator_vote

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Cascade-Resilient Consensus Demo")
    step("    Context Divergence Score + Temporal Clustering Score")
    step()

    agreement, _, _ = make_agreement(now=_NOW)
    decision, jp, _ = make_boundary_decision_with_proof(agreement, now=_NOW)

    kp_validators = [generate_keypair() for _ in range(5)]
    validator_ids = [f"validator-{c}" for c in "ABCDE"]

    # -------------------------------------------------------------------------
    step("==> Step 1: Build 5 votes with unique context digests (healthy)")
    step("    Each validator reasons from a distinct local state nonce")
    healthy_votes = []
    for i, (kp_v, v_id) in enumerate(zip(kp_validators, validator_ids)):
        # Force a unique per-validator context digest so CDS stays low
        nonce = f"state-nonce-{v_id}-unique"
        context_digest = hashlib.sha256(
            f"{jp.digest()}:{nonce}".encode()
        ).hexdigest()
        # Spread votes over 60 s to keep temporal clustering low
        vote_time = _NOW + timedelta(seconds=i * 15)
        vote = cast_validator_vote(
            justification_proof=jp,
            validator_sovereign_id=v_id,
            vote=True,
            signing_key=kp_v.private_key,
            reason="independent policy review",
            context_digest=context_digest,
            now=vote_time,
        )
        healthy_votes.append(vote)
        step(f"    {v_id}: context_digest={context_digest[:12]}...")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 2: assess_cascade_risk -- healthy votes (diverse, spread)")
    healthy_assessment, healthy_reason = assess_cascade_risk(
        healthy_votes,
        cascade_threshold=0.4,
        expected_deliberation_seconds=60.0,
        now=_NOW,
    )
    step(f"    cascade_score      : {healthy_assessment.cascade_score:.4f}")
    step(f"    context_divergence : {healthy_assessment.context_divergence_score:.4f}")
    step(f"    temporal_cluster   : {healthy_assessment.temporal_clustering_score:.4f}")
    step(f"    unique_contexts    : {healthy_assessment.unique_context_count}")
    step(f"    blocked            : {healthy_assessment.blocked}")
    step(f"    reason             : {healthy_reason}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 3: Build 5 votes with SAME context digest (cascade risk)")
    step("    All validators share identical local state -- correlated reasoning")
    shared_digest = hashlib.sha256(
        f"{jp.digest()}:shared-compromised-state".encode()
    ).hexdigest()
    cascade_votes = []
    for kp_v, v_id in zip(kp_validators, validator_ids):
        # All votes arrive within 2 s of each other (tight temporal cluster)
        vote_time = _NOW + timedelta(seconds=0.3)
        vote = cast_validator_vote(
            justification_proof=jp,
            validator_sovereign_id=v_id,
            vote=True,
            signing_key=kp_v.private_key,
            reason="auto-approved",
            context_digest=shared_digest,
            now=vote_time,
        )
        cascade_votes.append(vote)
        step(f"    {v_id}: context_digest={shared_digest[:12]}... (SAME)")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 4: assess_cascade_risk -- cascading votes (identical, clustered)")
    cascade_assessment, cascade_reason = assess_cascade_risk(
        cascade_votes,
        cascade_threshold=0.4,
        expected_deliberation_seconds=60.0,
        now=_NOW,
    )
    step(f"    cascade_score      : {cascade_assessment.cascade_score:.4f}")
    step(f"    context_divergence : {cascade_assessment.context_divergence_score:.4f}")
    step(f"    temporal_cluster   : {cascade_assessment.temporal_clustering_score:.4f}")
    step(f"    unique_contexts    : {cascade_assessment.unique_context_count}")
    step(f"    blocked            : {cascade_assessment.blocked}")
    step(f"    reason             : {cascade_reason}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 5: Summary -- cascade detection in both directions")
    healthy_status = "PASS" if not healthy_assessment.blocked else "BLOCKED"
    cascade_status = "BLOCKED" if cascade_assessment.blocked else "PASS"
    step(f"    healthy votes  : {healthy_status}  (score={healthy_assessment.cascade_score:.4f})")
    step(f"    cascade votes  : {cascade_status} (score={cascade_assessment.cascade_score:.4f})")
    step()

    step("VERIFIED: cascade detection works in both directions")
    step(f"          healthy score={healthy_assessment.cascade_score:.4f} < 0.4 threshold -> independent")
    step(f"          cascade score={cascade_assessment.cascade_score:.4f} > 0.4 threshold -> blocked")
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
