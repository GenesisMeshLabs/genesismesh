"""Demo: Formal Risk Signal Verification -- signatures, gate enforcement, decay.

Run from repository root:
    python docs/examples/assets/scripts/formal-risk-signal-verification-demo.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-formal-risk-signal-verification.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-formal-risk-signal-verification.png"
TITLE = "Genesis Mesh -- Formal Risk Signal Verification"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def _evidence(outcome: str, t: datetime):
    from genesis_mesh.models.execution import ExecutionEvidence
    return ExecutionEvidence(
        evidence_id=str(uuid.uuid4()),
        sequence_no=1,
        decision_id=str(uuid.uuid4()),
        context_id=str(uuid.uuid4()),
        agreement_id=str(uuid.uuid4()),
        executor_sovereign_id="partner-x",
        executed_capability="transactions.read",
        outcome=outcome,
        executed_at=t,
    )


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.crypto import verify_model_signature
    from genesis_mesh.trust.risk_signal import (
        check_risk_signal_gate,
        create_risk_signal,
        decay_risk_signal,
        update_risk_signal,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Formal Risk Signal Verification Demo")
    step("    Signature integrity, gate enforcement, and time decay")
    step()

    kp = generate_keypair()

    step("==> Step 1: Create signed risk signal and verify its signature")
    signal = create_risk_signal(
        from_sovereign_id="org-a",
        to_sovereign_id="partner-x",
        signing_key=kp.private_key,
        initial_signal=0.7,
        alpha=0.2,
        decay_lambda=0.05,
        now=_NOW,
    )
    step(f"    signal_id  : {signal.signal_id}")
    step(f"    signal     : {signal.signal:.4f}")
    step(f"    signed     : {signal.signature is not None}")
    sig_valid = verify_model_signature(signal, signal.signature, kp.public_key_b64)
    step(f"    sig valid  : {sig_valid}")
    step()

    step("==> Step 2: Gate check at minimum_signal=0.5 -- passes (0.7 >= 0.5)")
    passed, reason = check_risk_signal_gate(
        signal=signal,
        minimum_signal=0.5,
        issuer_public_keys=[kp.public_key_b64],
        at_time=_NOW,
    )
    step(f"    gate passed: {passed}")
    step(f"    reason     : {reason}")
    step()

    step("==> Step 3: Wrong key fails gate -- invalid signature")
    kp_wrong = generate_keypair()
    bad_passed, bad_reason = check_risk_signal_gate(
        signal=signal,
        minimum_signal=0.5,
        issuer_public_keys=[kp_wrong.public_key_b64],
        at_time=_NOW,
    )
    step(f"    gate passed: {bad_passed}")
    step(f"    reason     : {bad_reason}")
    step()

    step("==> Step 4: Apply time decay -- signal decays without new evidence")
    future = _NOW + timedelta(days=30)
    decayed_signal = decay_risk_signal(signal, kp.private_key, now=future)
    step(f"    original   : {signal.signal:.4f}")
    step(f"    after 30d  : {decayed_signal.signal:.4f}")
    step(f"    signed     : {decayed_signal.signature is not None}")
    decay_valid = verify_model_signature(
        decayed_signal, decayed_signal.signature, kp.public_key_b64
    )
    step(f"    sig valid  : {decay_valid}")
    step()

    step("==> Step 5: Gate check after decay at minimum_signal=0.5")
    decayed_passed, decayed_reason = check_risk_signal_gate(
        signal=decayed_signal,
        minimum_signal=0.5,
        issuer_public_keys=[kp.public_key_b64],
        at_time=future,
    )
    step(f"    gate passed: {decayed_passed}")
    step(f"    reason     : {decayed_reason}")
    step()

    step("==> Step 6: Record an update and verify the update signature chain")
    t = _NOW + timedelta(minutes=5)
    updated_signal, update, _ = update_risk_signal(
        signal, _evidence("success", t), kp.private_key, now=t,
    )
    update_valid = verify_model_signature(update, update.signature, kp.public_key_b64)
    signal_valid = verify_model_signature(
        updated_signal, updated_signal.signature, kp.public_key_b64
    )
    step(f"    update_id  : {update.update_id}")
    step(f"    prior      : {update.prior_signal:.4f}")
    step(f"    posterior  : {update.posterior_signal:.4f}")
    step(f"    update sig : {update_valid}")
    step(f"    signal sig : {signal_valid}")
    step()

    step("VERIFIED: risk signal integrity verified; gate check enforced; decay tracked")
    step(f"          signal_id={signal.signal_id[:8]}...  decay 30d: {signal.signal:.4f} -> {decayed_signal.signal:.4f}")
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
