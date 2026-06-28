"""Demo: Ephemeral Identity Purge -- verifiable deletion via Merkle registry.

Run from repository root:
    python docs/examples/assets/scripts/ephemeral-identity-purge-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-ephemeral-identity-purge.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-ephemeral-identity-purge.png"
TITLE = "Genesis Mesh -- Ephemeral Identity Purge"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.consensus import EphemeralExecutionIdentity
    from genesis_mesh.trust.purge import (
        build_nullification_registry,
        create_nullification_receipt,
        prove_nullification_inclusion,
        verify_nullification_inclusion,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Ephemeral Identity Purge Demo")
    step("    Verifiable deletion of 3 expired agent sessions via Merkle registry")
    step()

    kp_purger = generate_keypair()
    kp_issuer = generate_keypair()
    purger_id = "org-a-purge-operator"

    # Identities expired 10 minutes before _NOW
    expired_at = _NOW - timedelta(minutes=10)
    issued_at = expired_at - timedelta(seconds=120)

    step("==> Step 1: Create 3 expired EphemeralExecutionIdentities")
    identities = []
    for i in range(3):
        identity = EphemeralExecutionIdentity(
            consensus_id=f"consensus-{i + 1:03d}",
            decision_id=f"decision-{i + 1:03d}",
            bearer_sovereign_id=f"agent-session-{i + 1}",
            issued_at=issued_at,
            expires_at=expired_at,
            allowed_capabilities=["transactions.read"],
        )
        identities.append(identity)
        step(f"    identity {i + 1} : {identity.identity_id[:16]}... bearer={identity.bearer_sovereign_id}")
    step()

    step("==> Step 2: Create NullificationReceipts (one per identity)")
    receipts = []
    for identity in identities:
        receipt = create_nullification_receipt(
            identity=identity,
            purging_sovereign_id=purger_id,
            signing_key=kp_purger.private_key,
            now=_NOW,
        )
        receipts.append(receipt)
        step(f"    receipt : {receipt.receipt_id[:16]}... identity={receipt.identity_id[:16]}...")
    step()

    step("==> Step 3: Build NullificationRegistryRoot (Merkle tree over 3 receipts)")
    registry_root, merkle_levels = build_nullification_registry(
        receipts=receipts,
        operator_sovereign_id=purger_id,
        signing_key=kp_purger.private_key,
        now=_NOW,
    )
    step(f"    root_id       : {registry_root.root_id[:16]}...")
    step(f"    merkle_root   : {registry_root.merkle_root[:24]}...")
    step(f"    receipt_count : {registry_root.receipt_count}")
    step(f"    tree_levels   : {len(merkle_levels)}")
    step()

    step("==> Step 4: Prove receipt 1 is included in registry (Merkle inclusion proof)")
    proof = prove_nullification_inclusion(
        receipt_id=receipts[0].receipt_id,
        receipts=receipts,
        levels=merkle_levels,
        registry_root=registry_root,
    )
    step(f"    proof receipt : {proof.receipt_id[:16]}...")
    step(f"    leaf_hash     : {proof.leaf_hash[:24]}...")
    step(f"    path_length   : {len(proof.merkle_path)} nodes")
    step()

    step("==> Step 5: Verify inclusion proof -- confirms purge is auditable")
    ok, reason = verify_nullification_inclusion(
        proof=proof,
        registry_root=registry_root,
        expected_receipt=receipts[0],
        issuer_public_keys=[kp_purger.public_key_b64],
    )
    step(f"    valid  : {ok}")
    step(f"    reason : {reason}")
    step()

    step("VERIFIED: 3 identities purged; inclusion auditable via Merkle proof")
    step(f"          registry root = {registry_root.root_id[:16]}...")
    step(f"          proof valid   = {ok} ({reason})")
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
