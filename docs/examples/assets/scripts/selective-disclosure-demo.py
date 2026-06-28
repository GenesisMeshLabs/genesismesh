"""Demo: Selective Disclosure -- prove one capability without revealing others.

Run from repository root:
    python docs/examples/assets/scripts/selective-disclosure-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-selective-disclosure.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-selective-disclosure.png"
TITLE = "Genesis Mesh -- Selective Disclosure"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)

_ALL_CAPS = [
    "transactions.read",
    "balances.read",
    "payments.write",
    "account.create",
    "account.close",
    "statements.read",
    "fx.read",
    "audit.read",
]


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.selective_disclosure import (
        commit_capabilities,
        issue_nullifier,
        prove_capability_membership,
        verify_capability_proof,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Selective Disclosure Demo")
    step("    Prove one capability from a set of 8 -- reveal nothing else")
    step()

    agreement, kp_issuer, _ = make_agreement(
        "org-a", "bank-a",
        capabilities=_ALL_CAPS,
        now=_NOW,
    )

    step("==> Step 1: Commit all 8 capabilities to a Merkle root")
    commitment = commit_capabilities(
        capabilities=_ALL_CAPS,
        agreement=agreement,
        signing_key=kp_issuer.private_key,
        issued_by="org-a-issuer",
        now=_NOW,
    )
    step(f"    commitment_id : {commitment.commitment_id}")
    step(f"    capability_count : {commitment.capability_count}")
    step(f"    merkle_root   : {commitment.merkle_root[:24]}...")
    step(f"    capabilities  : [hidden -- 8 total]")
    step()

    step("==> Step 2: Prove membership of 'transactions.read' (O(log 8) = 3 hashes)")
    proof = prove_capability_membership(
        capability="transactions.read",
        capabilities=_ALL_CAPS,
        commitment=commitment,
        prover_sovereign_id="org-a",
        now=_NOW,
    )
    step(f"    proof_id      : {proof.proof_id}")
    step(f"    capability    : {proof.revealed_capability}")
    step(f"    path_length   : {len(proof.merkle_path)} nodes (log2(8)=3)")
    step(f"    reveals       : only 'transactions.read' + sibling hashes")
    step()

    step("==> Step 3: Verify proof -- valid, no nullifier in use")
    vr = verify_capability_proof(
        proof=proof,
        commitment=commitment,
        issuer_public_keys=[kp_issuer.public_key_b64],
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("==> Step 4: Issue nullifier -- prevents proof replay")
    kp_null = generate_keypair()
    nullifier = issue_nullifier(
        proof=proof,
        signing_key=kp_null.private_key,
        issued_by="org-a-gatekeeper",
        valid_for_seconds=60,
        now=_NOW,
    )
    step(f"    nullifier_id  : {nullifier.nullifier_id}")
    step(f"    proof_id      : {nullifier.proof_id}")
    step()

    step("==> Step 5: Verify same proof again -- replay blocked by nullifier registry")
    vr_replay = verify_capability_proof(
        proof=proof,
        commitment=commitment,
        issuer_public_keys=[kp_issuer.public_key_b64],
        nullifier=nullifier,
        used_nullifiers={nullifier.nullifier_id},
    )
    step(f"    valid  : {vr_replay.valid}")
    step(f"    reason : {vr_replay.reason}")
    step()

    step("VERIFIED: capability proved without revealing 7 others; replay blocked")
    step(f"          8 capabilities committed, 1 selectively disclosed")
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
