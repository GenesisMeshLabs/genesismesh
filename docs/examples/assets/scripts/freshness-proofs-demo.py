"""Demo: Freshness Proofs -- bounding revocation-check latency.

Run from repository root:
    python docs/examples/assets/scripts/freshness-proofs-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-freshness-proofs.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-freshness-proofs.png"
TITLE = "Genesis Mesh -- Freshness Proofs"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.trust.context import BoundaryEngine
    from genesis_mesh.trust.freshness import issue_freshness_proof, verify_freshness_proof

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Freshness Proofs Demo")
    step("    A freshness proof asserts the revocation feed was checked at sequence N")
    step()

    agreement, _, _ = make_agreement(now=_NOW)
    kp_feed = generate_keypair()
    kp_op = generate_keypair()

    step("==> Step 1: Issue a freshness proof at feed sequence 100")
    proof = issue_freshness_proof(
        feed_sovereign_id="bank-a",
        feed_sequence=100,
        feed_digest="deadbeef" * 8,
        signing_key=kp_feed.private_key,
        issued_by="bank-a-feed",
        issuer_sovereign_id="bank-a",
        valid_for_seconds=300,
        now=_NOW,
    )
    step(f"    proof_id       : {proof.proof_id}")
    step(f"    feed_sovereign : {proof.feed_sovereign_id}")
    step(f"    feed_sequence  : {proof.feed_sequence}")
    step(f"    valid_until    : {proof.proof_valid_until.isoformat()}")
    step()

    step("==> Step 2: Verify proof -- current sequence (100) meets floor (80)")
    vr = verify_freshness_proof(
        proof=proof,
        issuer_public_keys=[kp_feed.public_key_b64],
        required_sequence=80,
        at_time=_NOW,
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("==> Step 3: Verify proof -- current sequence (100) < required floor (120)")
    vr_stale = verify_freshness_proof(
        proof=proof,
        issuer_public_keys=[kp_feed.public_key_b64],
        required_sequence=120,
        at_time=_NOW,
    )
    step(f"    valid  : {vr_stale.valid}")
    step(f"    reason   : {vr_stale.reason}  (sequence too old)")
    step()

    step("==> Step 4: Verify proof -- valid_until elapsed (proof expired)")
    vr_expired = verify_freshness_proof(
        proof=proof,
        issuer_public_keys=[kp_feed.public_key_b64],
        required_sequence=80,
        at_time=_NOW + timedelta(minutes=10),
    )
    step(f"    valid  : {vr_expired.valid}")
    step(f"    reason   : {vr_expired.reason}  (proof window expired)")
    step()

    step("==> Step 5: Embed freshness proof in BoundaryEngine evaluation")
    engine = BoundaryEngine(
        "org-a",
        decision_valid_seconds=300,
        require_freshness_proof=True,
    )
    ctx = ContextRecord(
        context_id="ctx-fresh-001",
        agreement_id=agreement.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id="org-a",
        provider_sovereign_id="bank-a",
        requested_capability="transactions.read",
        request_parameters={},
        requested_at=_NOW,
        context_freshness_seq=100,
    )
    fresh_proof = issue_freshness_proof(
        feed_sovereign_id="bank-a",
        feed_sequence=100,
        feed_digest="deadbeef" * 8,
        signing_key=kp_feed.private_key,
        issued_by="bank-a-feed",
        issuer_sovereign_id="bank-a",
        valid_for_seconds=300,
        now=_NOW,
    )
    decision = engine.evaluate(
        context=ctx,
        agreement=agreement,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        freshness_proof=fresh_proof,
        freshness_proof_issuer_keys=[kp_feed.public_key_b64],
        now=_NOW,
    )
    step(f"    decision authorized : {decision.authorized}")
    for g in decision.gate_results:
        step(f"    gate [{g.gate_name:22s}]: passed={g.passed}")
    step()

    step("VERIFIED: freshness proof valid at seq 100; stale at seq 120; expired after 300s")
    step(f"          proof_id = {proof.proof_id}")
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
