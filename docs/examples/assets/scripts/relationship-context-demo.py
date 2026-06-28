"""Demo: Relationship Context -- BoundaryEngine gate evaluation.

Run from repository root:
    python docs/examples/assets/scripts/relationship-context-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-relationship-context.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-relationship-context.png"
TITLE = "Genesis Mesh -- Relationship Context"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.trust.context import BoundaryEngine

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Relationship Context Demo")
    step("    BoundaryEngine evaluates capabilities, validity, and freshness gates")
    step()

    agreement, kp_a, kp_b = make_agreement(
        "org-a", "bank-a",
        capabilities=["transactions.read", "balances.read"],
        now=_NOW,
    )
    kp_op = generate_keypair()
    engine = BoundaryEngine("org-a", decision_valid_seconds=300)

    step("==> Step 1: Root agreement established")
    step(f"    agreement_id : {agreement.agreement_id}")
    step(f"    capabilities : {agreement.agreed_terms.capabilities}")
    step(f"    valid_until  : {agreement.agreed_terms.valid_until.date()}")
    step()

    step("==> Step 2: Authorized request -- transactions.read within scope")
    ctx_ok = ContextRecord(
        context_id="ctx-001",
        agreement_id=agreement.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id="org-a",
        provider_sovereign_id="bank-a",
        requested_capability="transactions.read",
        request_parameters={"limit": 100},
        requested_at=_NOW,
        context_freshness_seq=50,
    )
    decision_ok = engine.evaluate(
        context=ctx_ok,
        agreement=agreement,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        now=_NOW,
    )
    step(f"    authorized  : {decision_ok.authorized}")
    for g in decision_ok.gate_results:
        step(f"    gate [{g.gate_name:22s}]: passed={g.passed}  {g.detail or ''}")
    step()

    step("==> Step 3: DENIED request -- out-of-scope capability (payments.write)")
    ctx_deny = ContextRecord(
        context_id="ctx-002",
        agreement_id=agreement.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id="org-a",
        provider_sovereign_id="bank-a",
        requested_capability="payments.write",
        request_parameters={},
        requested_at=_NOW,
        context_freshness_seq=50,
    )
    decision_deny = engine.evaluate(
        context=ctx_deny,
        agreement=agreement,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        now=_NOW,
    )
    step(f"    authorized  : {decision_deny.authorized}")
    for g in decision_deny.gate_results:
        status = "PASS" if g.passed else "FAIL"
        step(f"    gate [{g.gate_name:22s}]: {status}  {g.detail or ''}")
    step()

    step("==> Step 4: DENIED request -- expired agreement (past valid_until)")
    from genesis_mesh.models.agreement import AgreementTerms
    import uuid, json

    kp_x = generate_keypair()
    engine2 = BoundaryEngine("org-a")
    agreement_expired, _, _ = make_agreement(
        "org-a", "bank-a",
        capabilities=["transactions.read"],
        now=_NOW - timedelta(days=400),
    )
    ctx_exp = ContextRecord(
        context_id="ctx-003",
        agreement_id=agreement_expired.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id="org-a",
        provider_sovereign_id="bank-a",
        requested_capability="transactions.read",
        request_parameters={},
        requested_at=_NOW,
        context_freshness_seq=50,
    )
    decision_exp = engine2.evaluate(
        context=ctx_exp,
        agreement=agreement_expired,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        now=_NOW,
    )
    step(f"    authorized   : {decision_exp.authorized}")
    for g in decision_exp.gate_results:
        if not g.passed:
            step(f"    BLOCKED gate : {g.gate_name} -- {g.detail}")
    step()

    step("VERIFIED: BoundaryEngine gates capability, validity, and freshness")
    step(f"          authorized decision id  = {decision_ok.decision_id}")
    step(f"          denied   (out-of-scope) = {decision_deny.authorized}")
    step(f"          denied   (expired)      = {decision_exp.authorized}")
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
