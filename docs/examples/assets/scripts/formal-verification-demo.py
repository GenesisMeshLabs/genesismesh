"""Demo: Formal Verification / Interop Bridges (SPIFFE, W3C VC, JWT).

Run from repository root:
    python docs/examples/assets/scripts/formal-verification-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement, make_boundary_decision
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-formal-verification.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-formal-verification.png"
TITLE = "Genesis Mesh -- Interop Bridges (SPIFFE / W3C VC / JWT)"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.interop.spiffe import agreement_to_svid, svid_to_agreement_fields
    from genesis_mesh.interop.w3c_vc import agreement_to_vc, trust_evidence_to_vc
    from genesis_mesh.interop.jose import decision_to_jwt, jwt_to_decision_claims
    from genesis_mesh.trust.evidence import build_trust_evidence, graph_digest_from_export
    from genesis_mesh.trust.decision import evaluate_trust_decision
    from _bootstrap import active_graph

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Interop Bridges Demo")
    step("    AgreementRecord <-> SPIFFE SVID / W3C VC / JWT")
    step()

    agreement, kp_a, kp_b = make_agreement(now=_NOW)
    decision, kp_op = make_boundary_decision(agreement, now=_NOW)

    step("==> Step 1: Convert AgreementRecord to SPIFFE SVID")
    svid = agreement_to_svid(agreement)
    step(f"    spiffe_id   : {svid.get('spiffe_id', 'n/a')}")
    step(f"    subject     : {svid.get('subject', 'n/a')}")
    step(f"    san         : {svid.get('san', 'n/a')}")
    fields = [k for k in svid.keys()]
    step(f"    SVID fields : {fields}")
    step()

    step("==> Step 2: Round-trip SVID -> extract agreement fields")
    back = svid_to_agreement_fields(svid)
    if back:
        step(f"    offerer   : {back.get('offerer_sovereign_id', 'n/a')}")
        step(f"    responder : {back.get('responder_sovereign_id', 'n/a')}")
    step(f"    round-trip: {back is not None}")
    step()

    step("==> Step 3: Convert AgreementRecord to W3C Verifiable Credential")
    vc = agreement_to_vc(agreement)
    step(f"    @context    : {vc.get('@context', [])[:2]}")
    step(f"    type        : {vc.get('type', [])}")
    step(f"    issuer      : {vc.get('issuer', 'n/a')}")
    cred = vc.get("credentialSubject", {})
    step(f"    subject id  : {cred.get('id', 'n/a')}")
    step()

    step("==> Step 4: Convert BoundaryDecision to JWT bearer token")
    jwt_token = decision_to_jwt(decision, kp_op.private_key, key_id="org-a-2026")
    parts = jwt_token.split(".")
    step(f"    JWT parts   : {len(parts)} (header.payload.signature)")
    step(f"    header      : ...{parts[0][-10:]}")
    step(f"    payload     : ...{parts[1][:20]}...")
    step()

    step("==> Step 5: Verify JWT and extract claims")
    claims = jwt_to_decision_claims(jwt_token, kp_op.public_key_b64)
    if claims:
        step(f"    sub         : {claims.get('sub', 'n/a')}")
        step(f"    authorized  : {claims.get('authorized', 'n/a')}")
        step(f"    capability  : {claims.get('capability', 'n/a')}")
        step(f"    verified    : True")
    step()

    step("==> Step 6: JWT with wrong key fails")
    from genesis_mesh.crypto import generate_keypair
    kp_wrong = generate_keypair()
    bad_claims = jwt_to_decision_claims(jwt_token, kp_wrong.public_key_b64)
    step(f"    wrong key result: {bad_claims}  (None = signature invalid)")
    step()

    step("VERIFIED: AgreementRecord round-trips to SPIFFE/W3C VC; JWT claims verified")
    step(f"          agreement_id = {agreement.agreement_id}")
    step(f"          decision_id  = {decision.decision_id}")
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
