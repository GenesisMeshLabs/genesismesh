"""Demo: Trust Evidence -- signed proof of trust decisions, offline verifiable.

Run from repository root:
    python docs/examples/assets/scripts/trust-evidence-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import active_graph
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-trust-evidence.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-trust-evidence.png"
TITLE = "Genesis Mesh -- Trust Evidence"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.decision import evaluate_trust_decision
    from genesis_mesh.trust.evidence import (
        build_trust_evidence,
        graph_digest_from_export,
        verify_trust_evidence,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Trust Evidence Demo")
    step("    Signed trust decisions bound to graph state; offline verifiable")
    step()

    graph = active_graph("org-a", "bank-a", now=_NOW)
    kp = generate_keypair()

    step("==> Step 1: Evaluate trust decision for org-a -> bank-a")
    decision = evaluate_trust_decision(
        graph,
        "org-a",
        "bank-a",
        requested_roles=["transactions.read"],
        now=_NOW,
    )
    step(f"    source     : {decision.source_sovereign_id}")
    step(f"    target     : {decision.target_sovereign_id}")
    step(f"    verdict    : {decision.verdict}")
    step(f"    trusted    : {decision.trusted}")
    step(f"    hop_count  : {decision.hop_count}")
    step(f"    signals    : {len(decision.signals)}")
    step()

    step("==> Step 2: Compute canonical graph digest")
    graph_digest = graph_digest_from_export(graph)
    step(f"    graph_dig  : {graph_digest[:32]}...")
    step(f"    length     : {len(graph_digest)} hex chars (SHA-256)")
    step()

    step("==> Step 3: Build signed trust evidence record")
    evidence = build_trust_evidence(
        decision,
        issuer_sovereign_id="org-a",
        graph_digest=graph_digest,
        issued_by="org-a-operator",
        signing_key=kp.private_key,
        now=_NOW,
    )
    step(f"    evidence_id: {evidence.evidence_id}")
    step(f"    issuer     : {evidence.issuer_sovereign_id}")
    step(f"    verdict    : {evidence.verdict}")
    step(f"    signatures : {len(evidence.signatures)}")
    step(f"    graph_dig  : {evidence.graph_digest[:16]}...")
    step()

    step("==> Step 4: Verify evidence with correct graph digest -- accepted")
    result = verify_trust_evidence(
        evidence,
        [kp.public_key_b64],
        expected_graph_digest=graph_digest,
    )
    step(f"    accepted   : {result.accepted}")
    step(f"    reason     : {result.reason}")
    step(f"    verdict    : {result.verdict}")
    step()

    step("==> Step 5: Tamper check -- wrong graph digest -> graph_digest_mismatch")
    wrong_digest = "a" * 64
    tamper_result = verify_trust_evidence(
        evidence,
        [kp.public_key_b64],
        expected_graph_digest=wrong_digest,
    )
    step(f"    accepted   : {tamper_result.accepted}")
    step(f"    reason     : {tamper_result.reason}")
    step()

    step("==> Step 6: Verify with wrong signing key -- invalid_signature")
    kp_wrong = generate_keypair()
    bad_sig_result = verify_trust_evidence(
        evidence,
        [kp_wrong.public_key_b64],
    )
    step(f"    accepted   : {bad_sig_result.accepted}")
    step(f"    reason     : {bad_sig_result.reason}")
    step()

    step("VERIFIED: trust decisions bundled with graph context; offline verifiable")
    step(f"          evidence_id={evidence.evidence_id[:8]}...  verdict={evidence.verdict}")
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
