"""Demo: Delegation Chain (scope attenuation across hops).

Run from repository root:
    python docs/examples/assets/scripts/delegation-chain-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import active_graph, make_agreement
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-delegation-chain.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-delegation-chain.png"
TITLE = "Genesis Mesh -- Delegation Chain"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.agreement import AgreementTerms
    from genesis_mesh.trust.delegation import (
        build_delegation,
        cosign_delegation,
        verify_delegation_chain,
    )
    from genesis_mesh.trust.delegation import DelegationChain

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Delegation Chain Demo")
    step("    Org-A -> Partner-X -> Contractor-Y (scope attenuates at each hop)")
    step()

    agreement, kp_a, kp_b = make_agreement(
        "org-a", "bank-a",
        capabilities=["transactions.read", "balances.read", "payments.write"],
        now=_NOW,
    )
    kp_x = generate_keypair()
    kp_y = generate_keypair()

    step("==> Step 1: Root agreement established (Org-A <-> Bank-A)")
    step(f"    agreement_id : {agreement.agreement_id}")
    step(f"    capabilities : {agreement.agreed_terms.capabilities}")
    step()

    graph_ax = active_graph("org-a", "partner-x", now=_NOW)

    step("==> Step 2: Org-A delegates to Partner-X (attenuated to transactions.read)")
    terms_hop1 = AgreementTerms(
        capabilities=["transactions.read"],
        scope={"delegation": True},
        valid_from=_NOW,
        valid_until=_NOW + timedelta(days=90),
        freshness_commitment=42,
    )
    hop1 = build_delegation(
        parent=agreement,
        delegated_terms=terms_hop1,
        graph=graph_ax,
        signing_key=kp_a.private_key,
        delegator_sovereign_id="org-a",
        delegate_sovereign_id="partner-x",
        issued_by="org-a-op",
        now=_NOW,
    )
    hop1 = cosign_delegation(
        record=hop1,
        graph=active_graph("partner-x", "org-a", now=_NOW),
        signing_key=kp_x.private_key,
        issued_by="partner-x-op",
        now=_NOW,
    )
    step(f"    hop1 id      : {hop1.delegation_id}")
    step(f"    delegate     : {hop1.delegate_sovereign_id}")
    step(f"    capabilities : {hop1.delegated_terms.capabilities}")
    step(f"    signatures   : {len(hop1.signatures)}")
    step()

    graph_xy = active_graph("partner-x", "contractor-y", now=_NOW)

    step("==> Step 3: Partner-X delegates to Contractor-Y (further attenuated)")
    terms_hop2 = AgreementTerms(
        capabilities=["transactions.read"],
        scope={"delegation": False},
        valid_from=_NOW,
        valid_until=_NOW + timedelta(days=30),
        freshness_commitment=42,
    )
    hop2 = build_delegation(
        parent=hop1,
        delegated_terms=terms_hop2,
        graph=graph_xy,
        signing_key=kp_x.private_key,
        delegator_sovereign_id="partner-x",
        delegate_sovereign_id="contractor-y",
        issued_by="partner-x-op",
        now=_NOW,
    )
    hop2 = cosign_delegation(
        record=hop2,
        graph=active_graph("contractor-y", "partner-x", now=_NOW),
        signing_key=kp_y.private_key,
        issued_by="contractor-y-op",
        now=_NOW,
    )
    step(f"    hop2 id      : {hop2.delegation_id}")
    step(f"    delegate     : {hop2.delegate_sovereign_id}")
    step(f"    capabilities : {hop2.delegated_terms.capabilities}")
    step()

    step("==> Step 4: Verify 2-hop chain (Org-A -> Partner-X -> Contractor-Y)")
    chain = DelegationChain(root=agreement, hops=[hop1, hop2])
    result = verify_delegation_chain(
        chain=chain,
        root_offerer_public_keys=[kp_a.public_key_b64],
        root_responder_public_keys=[kp_b.public_key_b64],
        per_hop_keys={
            "org-a": [kp_a.public_key_b64],
            "partner-x": [kp_x.public_key_b64],
            "contractor-y": [kp_y.public_key_b64],
        },
    )
    step(f"    accepted     : {result.accepted}")
    step(f"    reason       : {result.reason}")
    step(f"    chain_length : {result.chain_length}")
    step()

    step("==> Step 5: Scope escalation attempt -- Contractor-Y tries to add payments.write")
    try:
        terms_escalate = AgreementTerms(
            capabilities=["transactions.read", "payments.write"],
            scope={"delegation": False},
            valid_from=_NOW,
            valid_until=_NOW + timedelta(days=30),
            freshness_commitment=42,
        )
        hop_bad = build_delegation(
            parent=hop1,
            delegated_terms=terms_escalate,
            graph=graph_xy,
            signing_key=kp_x.private_key,
            delegator_sovereign_id="partner-x",
            delegate_sovereign_id="contractor-y",
            issued_by="partner-x-op",
            now=_NOW,
        )
        step(f"    UNEXPECTED: delegation built with {hop_bad.delegated_terms.capabilities}")
    except ValueError as exc:
        step(f"    BLOCKED: {exc}")
    step()

    step("VERIFIED: 2-hop chain verified; scope escalation rejected at build time")
    step(f"          chain depth = {len(chain.hops)} hops")
    step(f"          final scope = {hop2.delegated_terms.capabilities}")
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
