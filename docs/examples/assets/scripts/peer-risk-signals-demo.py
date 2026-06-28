"""Demo: Peer Risk Signals -- EWMA trust score with anomaly detection.

Run from repository root:
    python docs/examples/assets/scripts/peer-risk-signals-demo.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-peer-risk-signals.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-peer-risk-signals.png"
TITLE = "Genesis Mesh -- Peer Risk Signals"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def _evidence(outcome: str, t: datetime):
    from genesis_mesh.trust.risk_signal import ExecutionEvidence
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
    from genesis_mesh.trust.risk_signal import (
        check_risk_signal_gate,
        create_risk_signal,
        update_risk_signal,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Peer Risk Signals Demo")
    step("    Local EWMA trust score -- no shared ledger, no gossip")
    step()

    kp_signal = generate_keypair()
    signal = create_risk_signal(
        from_sovereign_id="org-a",
        to_sovereign_id="partner-x",
        signing_key=kp_signal.private_key,
        initial_signal=0.5,
        alpha=0.2,
        decay_lambda=0.05,
        now=_NOW,
    )
    step("==> Step 1: Initialize risk signal at 0.5 (neutral)")
    step(f"    signal_id  : {signal.signal_id}")
    step(f"    from       : {signal.from_sovereign_id}")
    step(f"    to         : {signal.to_sovereign_id}")
    step(f"    signal     : {signal.signal:.4f}")
    step(f"    alpha      : {signal.alpha} (EWMA weight)")
    step()

    step("==> Step 2: Record 8 successful outcomes -- signal rises")
    history = []
    t = _NOW
    for i in range(8):
        t += timedelta(minutes=5)
        signal, update, _ = update_risk_signal(
            signal, _evidence("success", t), kp_signal.private_key, history=history, now=t
        )
        history.append(update)
    step(f"    after 8 successes: signal = {signal.signal:.4f}")
    step()

    step("==> Step 3: Check gate at minimum_signal=0.3 -- passes")
    ok, reason = check_risk_signal_gate(
        signal=signal,
        minimum_signal=0.3,
        issuer_public_keys=[kp_signal.public_key_b64],
        at_time=t,
    )
    step(f"    gate passed : {ok}")
    step(f"    reason      : {reason}")
    step()

    step("==> Step 4: Record 6 failure outcomes -- signal drops, anomaly fires")
    anomaly_fired = None
    for i in range(6):
        t += timedelta(minutes=5)
        signal, update, anomaly = update_risk_signal(
            signal, _evidence("failure", t), kp_signal.private_key, history=history, now=t
        )
        history.append(update)
        if anomaly and anomaly_fired is None:
            anomaly_fired = (i + 1, signal.signal)
    step(f"    after 6 failures: signal = {signal.signal:.4f}")
    if anomaly_fired:
        step(f"    ANOMALY fired at failure #{anomaly_fired[0]}: signal={anomaly_fired[1]:.4f}")
    step()

    step("==> Step 5: Check gate at minimum_signal=0.5 -- now BLOCKED")
    blocked, reason_b = check_risk_signal_gate(
        signal=signal,
        minimum_signal=0.5,
        issuer_public_keys=[kp_signal.public_key_b64],
        at_time=t,
    )
    step(f"    gate passed : {blocked}")
    step(f"    reason      : {reason_b}")
    step()

    step("VERIFIED: signal rose on successes; anomaly detected; gate blocked below floor")
    step(f"          final signal = {signal.signal:.4f}  (floor was 0.5)")
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
