"""Demo: Relationship Agreement (Offer -> Counter -> Accept).

Run from repository root:
    python docs/examples/assets/scripts/relationship-agreement-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import active_graph
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-relationship-agreement.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-relationship-agreement.png"
TITLE = "Genesis Mesh -- Relationship Agreement"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
_VALID = _NOW + timedelta(days=365)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.agreement import AgreementTerms
    from genesis_mesh.trust.agreement import (
        accept_counter,
        build_counter,
        build_offer,
        verify_agreement,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Relationship Agreement Demo")
    step("    Protocol: Offer -> Counter -> Accept -> Verify")
    step()

    kp_a = generate_keypair()
    kp_b = generate_keypair()
    step("==> Step 1: Generate Ed25519 keypairs for Org-A and Bank-A")
    step(f"    org-a  pub: {kp_a.public_key_b64[:32]}...")
    step(f"    bank-a pub: {kp_b.public_key_b64[:32]}...")
    step()

    graph_a = active_graph("org-a", "bank-a", now=_NOW)
    graph_b = active_graph("bank-a", "org-a", now=_NOW)

    step("==> Step 2: Org-A builds and signs a Capability Offer")
    terms_offered = AgreementTerms(
        capabilities=["transactions.read", "balances.read"],
        scope={"delegation": False},
        valid_from=_NOW,
        valid_until=_VALID,
        freshness_commitment=42,
    )
    offer = build_offer(
        offerer_sovereign_id="org-a",
        responder_sovereign_id="bank-a",
        requested_terms=terms_offered,
        graph=graph_a,
        signing_key=kp_a.private_key,
        issued_by="org-a-operator",
        expires_at=_VALID,
        now=_NOW,
    )
    step(f"    offer_id    : {offer.offer_id}")
    step(f"    capabilities: {offer.requested_terms.capabilities}")
    step(f"    freshness   : seq >= {offer.requested_terms.freshness_commitment}")
    step()

    step("==> Step 3: Bank-A narrows terms (drops balances.read) and counter-signs")
    terms_counter = AgreementTerms(
        capabilities=["transactions.read"],
        scope={"delegation": False},
        valid_from=_NOW,
        valid_until=_VALID,
        freshness_commitment=50,
    )
    counter = build_counter(
        offer=offer,
        offered_terms=terms_counter,
        graph=graph_b,
        signing_key=kp_b.private_key,
        issued_by="bank-a-operator",
        now=_NOW,
    )
    step(f"    offer_id   : {counter.offer_id} (traces original offer)")
    step(f"    narrowed to: {counter.agreed_terms.capabilities}")
    step(f"    freshness  : seq >= {counter.agreed_terms.freshness_commitment}")
    step()

    step("==> Step 4: Org-A accepts the counter -- dual-signed AgreementRecord")
    agreement = accept_counter(
        counter=counter,
        original_offer=offer,
        signing_key=kp_a.private_key,
        issued_by="org-a-operator",
        now=_NOW,
    )
    step(f"    agreement_id : {agreement.agreement_id}")
    step(f"    offerer      : {agreement.offerer_sovereign_id}")
    step(f"    responder    : {agreement.responder_sovereign_id}")
    step(f"    capabilities : {agreement.agreed_terms.capabilities}")
    step(f"    signatures   : {len(agreement.signatures)} (offerer + responder)")
    step()

    step("==> Step 5: Independent verification -- either party, any machine, no network")
    result = verify_agreement(
        record=agreement,
        offerer_public_keys=[kp_a.public_key_b64],
        responder_public_keys=[kp_b.public_key_b64],
        expected_graph_digest=None,
    )
    step(f"    accepted : {result.accepted}")
    step(f"    reason   : {result.reason}")
    step()

    step("==> Step 6: Tamper check -- wrong public key supplied")
    kp_wrong = generate_keypair()
    bad = verify_agreement(
        record=agreement,
        offerer_public_keys=[kp_wrong.public_key_b64],
        responder_public_keys=[kp_b.public_key_b64],
    )
    step(f"    accepted : {bad.accepted}  reason: {bad.reason}")
    step()

    step("VERIFIED: dual-signed AgreementRecord -- neither party can forge the other's signature")
    step(f"          agreement_id = {agreement.agreement_id}")
    step(f"          capabilities = {agreement.agreed_terms.capabilities}")
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
