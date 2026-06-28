"""Demo: Adversarial Seed Isolation -- credit-farming pattern detection.

Run from repository root:
    python docs/examples/assets/scripts/adversarial-seed-isolation-demo.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-adversarial-seed-isolation.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-adversarial-seed-isolation.png"
TITLE = "Genesis Mesh -- Adversarial Seed Isolation"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def _evidence(outcome: str, seq: int, decision_id: str, agreement_id: str, t: datetime):
    from genesis_mesh.models.execution import ExecutionEvidence
    return ExecutionEvidence(
        evidence_id=str(uuid.uuid4()),
        sequence_no=seq,
        decision_id=decision_id,
        context_id=str(uuid.uuid4()),
        agreement_id=agreement_id,
        executor_sovereign_id="partner-x",
        executed_capability="transactions.read",
        outcome=outcome,
        executed_at=t,
    )


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.risk_signal import (
        assess_seed_isolation,
        create_risk_signal,
        update_risk_signal,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Adversarial Seed Isolation Demo")
    step("    Detect credit-farming -> volatility-discontinuity attack pattern")
    step()

    kp = generate_keypair()
    decision_id = str(uuid.uuid4())
    agreement_id = str(uuid.uuid4())

    # -------------------------------------------------------------------------
    step("==> Step 1: Initialize risk signal for adversarial counterparty")
    adv_signal = create_risk_signal(
        from_sovereign_id="org-a",
        to_sovereign_id="partner-x",
        signing_key=kp.private_key,
        initial_signal=0.5,
        alpha=0.2,
        now=_NOW,
    )
    step(f"    signal_id : {adv_signal.signal_id}")
    step(f"    from      : {adv_signal.from_sovereign_id}")
    step(f"    to        : {adv_signal.to_sovereign_id}")
    step(f"    signal    : {adv_signal.signal:.4f}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 2: Phase 1 -- 15 consecutive successes (credit farming)")
    step("    Adversary behaves perfectly to build up trust score")
    adv_history = []
    t = _NOW
    seq = 1
    for i in range(15):
        t += timedelta(hours=2)
        adv_signal, update, _ = update_risk_signal(
            adv_signal,
            _evidence("success", seq, decision_id, agreement_id, t),
            kp.private_key,
            history=adv_history,
            now=t,
        )
        adv_history.append(update)
        seq += 1
    step(f"    after 15 successes: signal = {adv_signal.signal:.4f}")
    step(f"    updates recorded  : {len(adv_history)}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 3: Phase 2 -- 12 consecutive failures (exploitation)")
    step("    Adversary switches to harmful behavior after trust is established")
    for i in range(12):
        t += timedelta(hours=2)
        adv_signal, update, _ = update_risk_signal(
            adv_signal,
            _evidence("failure", seq, decision_id, agreement_id, t),
            kp.private_key,
            history=adv_history,
            now=t,
        )
        adv_history.append(update)
        seq += 1
    step(f"    after 12 failures : signal = {adv_signal.signal:.4f}")
    step(f"    total history     : {len(adv_history)}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 4: assess_seed_isolation -- adversarial pattern")
    adv_report = assess_seed_isolation(
        adv_signal,
        adv_history,
        seed_threshold=0.2,
        now=t,
    )
    step(f"    seed_probability        : {adv_report.seed_probability:.4f}")
    step(f"    credit_farming_score    : {adv_report.credit_farming_score:.4f}")
    step(f"    volatility_discontinuity: {adv_report.volatility_discontinuity_score:.4f}")
    step(f"    streak_fragility_score  : {adv_report.streak_fragility_score:.4f}")
    step(f"    max_success_streak      : {adv_report.max_success_streak}")
    step(f"    isolated                : {adv_report.isolated}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 5: Build benign history -- gradual mixed results")
    kp2 = generate_keypair()
    benign_signal = create_risk_signal(
        from_sovereign_id="org-a",
        to_sovereign_id="partner-y",
        signing_key=kp2.private_key,
        initial_signal=0.5,
        alpha=0.2,
        now=_NOW,
    )
    benign_history = []
    t2 = _NOW
    seq2 = 1
    # Alternating realistic mixed outcomes -- no long streak, no phase switch
    outcomes = (["success", "success", "failure", "success", "partial"] * 6)[:27]
    for outcome in outcomes:
        t2 += timedelta(hours=3)
        benign_signal, update2, _ = update_risk_signal(
            benign_signal,
            _evidence(outcome, seq2, str(uuid.uuid4()), str(uuid.uuid4()), t2),
            kp2.private_key,
            history=benign_history,
            now=t2,
        )
        benign_history.append(update2)
        seq2 += 1

    benign_report = assess_seed_isolation(
        benign_signal,
        benign_history,
        seed_threshold=0.2,
        now=t2,
    )
    step(f"    seed_probability : {benign_report.seed_probability:.4f}")
    step(f"    isolated         : {benign_report.isolated}")
    step(f"    history_length   : {benign_report.history_length}")
    step()

    step("VERIFIED: adversarial seed pattern detected; benign history passes")
    step(f"          adversary isolated={adv_report.isolated}  (seed_prob={adv_report.seed_probability:.4f})")
    step(f"          benign    isolated={benign_report.isolated}  (seed_prob={benign_report.seed_probability:.4f})")
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
