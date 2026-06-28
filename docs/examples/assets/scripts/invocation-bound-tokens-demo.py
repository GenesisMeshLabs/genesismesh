"""Demo: Invocation-Bound Capability Tokens (IBCT).

Run from repository root:
    python docs/examples/assets/scripts/invocation-bound-tokens-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import make_agreement
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-invocation-bound-tokens.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-invocation-bound-tokens.png"
TITLE = "Genesis Mesh -- Invocation-Bound Capability Tokens"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.trust.invocation_token import (
        issue_invocation_token,
        record_invocation_use,
        verify_invocation_token,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Invocation-Bound Capability Tokens Demo")
    step("    IBCT: bearer-portable, offline-verifiable, budget-bounded")
    step()

    agreement, kp_issuer, _kp_b = make_agreement(
        "org-a", "bank-a",
        capabilities=["transactions.read", "balances.read"],
        now=_NOW,
    )

    step("==> Step 1: Issue IBCT with 3-use budget")
    token = issue_invocation_token(
        agreement=agreement,
        bearer_sovereign_id="partner-x",
        capabilities=["transactions.read"],
        signing_key=kp_issuer.private_key,
        issued_by="org-a-issuer",
        valid_for_seconds=600,
        max_invocations=4,
        policy_constraints=["audit_log_required"],
        now=_NOW,
    )
    step(f"    token_id        : {token.token_id}")
    step(f"    bearer          : {token.bearer_sovereign_id}")
    step(f"    capabilities    : {token.capabilities}")
    step(f"    max_invocations : {token.max_invocations}")
    step(f"    valid_for       : 600 seconds")
    step()

    step("==> Step 2: First use (invocation 1 of 3)")
    use1 = record_invocation_use(
        token=token,
        action_tag="read_transactions",
        outcome="success",
        signing_key=kp_issuer.private_key,
        used_by="partner-x",
        now=_NOW,
    )
    step(f"    use_id       : {use1.use_id}")
    step(f"    action_tag   : {use1.action_tag}")
    step(f"    outcome      : {use1.outcome}")
    step(f"    invocation   : 1")
    step()

    step("==> Step 3: Second use (links to first use)")
    use2 = record_invocation_use(
        token=token,
        action_tag="read_transactions",
        outcome="success",
        signing_key=kp_issuer.private_key,
        used_by="partner-x",
        prior_use=use1,
        now=_NOW,
    )
    step(f"    use_id   : {use2.use_id}")
    step(f"    chained  : prev_use_digest set")
    step()

    step("==> Step 4: Third use (final use within budget)")
    use3 = record_invocation_use(
        token=token,
        action_tag="read_transactions",
        outcome="success",
        signing_key=kp_issuer.private_key,
        used_by="partner-x",
        prior_use=use2,
        now=_NOW,
    )
    step(f"    use_id   : {use3.use_id}")
    step()

    step("==> Step 5: Verify token with 3 use records -- valid within budget")
    vr = verify_invocation_token(
        token=token,
        issuer_public_keys=[kp_issuer.public_key_b64],
        requested_capability="transactions.read",
        bearer_sovereign_id="partner-x",
        use_records=[use1, use2, use3],
        at_time=_NOW,
    )
    step(f"    valid  : {vr.valid}")
    step(f"    reason : {vr.reason}")
    step()

    step("==> Step 6: Fourth use -- crosses the 4-use budget ceiling")
    use4 = record_invocation_use(
        token=token,
        action_tag="read_transactions",
        outcome="success",
        signing_key=kp_issuer.private_key,
        used_by="partner-x",
        prior_use=use3,
        now=_NOW,
    )
    vr_over = verify_invocation_token(
        token=token,
        issuer_public_keys=[kp_issuer.public_key_b64],
        requested_capability="transactions.read",
        bearer_sovereign_id="partner-x",
        use_records=[use1, use2, use3, use4],
        at_time=_NOW,
    )
    step(f"    valid  : {vr_over.valid}")
    step(f"    reason   : {vr_over.reason}")
    step()

    step("VERIFIED: 4-use budget enforced offline; budget exhausted at use 4")
    step(f"          token_id = {token.token_id}")
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
