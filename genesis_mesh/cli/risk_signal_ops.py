"""CLI commands for Peer Risk Signals.

trust risk create   -- create a new PeerRiskSignal for a counterparty
trust risk update   -- update signal from an ExecutionEvidence outcome
trust risk decay    -- apply time decay without evidence (scheduled)
trust risk show     -- display current signal state
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.execution import ExecutionEvidence
from ..models.risk_signal import PeerRiskSignal, RiskSignalUpdate
from ..trust.risk_signal import (
    assess_seed_isolation,
    create_risk_signal,
    decay_risk_signal,
    update_risk_signal,
)


@click.group("risk")
def risk() -> None:
    """Peer risk signals — local EWMA over execution history (not a reputation system)."""


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@risk.command("create")
@click.option("--from-sovereign", "from_sov", required=True,
              help="Sovereign ID of the signal owner.")
@click.option("--to-sovereign", "to_sov", required=True,
              help="Sovereign ID of the counterparty being observed.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Base64-encoded Ed25519 signing key file.")
@click.option("--initial-signal", "initial", type=float, default=0.5,
              help="Starting signal value in [0.0, 1.0] (default 0.5).")
@click.option("--alpha", type=float, default=0.2, help="EWMA smoothing factor (default 0.2).")
@click.option("--decay-lambda", "lam", type=float, default=0.05,
              help="Exponential decay rate per day (default 0.05).")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed PeerRiskSignal JSON.")
def risk_create(
    from_sov: str, to_sov: str, key_path: str,
    initial: float, alpha: float, lam: float, output_path: str,
) -> None:
    """Create a new signed PeerRiskSignal for a counterparty."""
    sk = load_private_key(key_path)
    sig = create_risk_signal(
        from_sov, to_sov, sk,
        initial_signal=initial, alpha=alpha, decay_lambda=lam,
    )
    Path(output_path).write_text(sig.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] PeerRiskSignal {sig.signal_id} written to {output_path}")
    click.echo(f"     {from_sov} → {to_sov}  signal={sig.signal:.4f}")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@risk.command("update")
@click.option("--signal", "signal_path", required=True, type=click.Path(exists=True),
              help="Current PeerRiskSignal JSON.")
@click.option("--evidence", "evidence_path", required=True, type=click.Path(exists=True),
              help="ExecutionEvidence JSON providing the outcome.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Signal owner's signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the updated PeerRiskSignal JSON.")
@click.option("--output-update", "update_path", default=None, type=click.Path(),
              help="Optional path to write the RiskSignalUpdate JSON.")
@click.option("--output-anomaly", "anomaly_path", default=None, type=click.Path(),
              help="Optional path to write a RiskAnomaly JSON if one is detected.")
def risk_update(
    signal_path: str, evidence_path: str, key_path: str,
    output_path: str, update_path: str | None, anomaly_path: str | None,
) -> None:
    """Update a PeerRiskSignal from an ExecutionEvidence outcome."""
    signal = PeerRiskSignal.model_validate_json(Path(signal_path).read_text(encoding="utf-8"))
    evidence = ExecutionEvidence.model_validate_json(
        Path(evidence_path).read_text(encoding="utf-8")
    )
    sk = load_private_key(key_path)

    updated, update_record, anomaly = update_risk_signal(signal, evidence, sk)

    Path(output_path).write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] Signal updated: {signal.signal:.4f} → {updated.signal:.4f}")
    click.echo(f"     Outcome: {evidence.outcome}  delta={update_record.delta:+.4f}")

    if update_path:
        Path(update_path).write_text(update_record.model_dump_json(indent=2), encoding="utf-8")

    if anomaly is not None:
        click.echo(f"[ANOMALY] Detected: {anomaly.sigma_multiples:.1f}σ above threshold")
        if anomaly_path:
            Path(anomaly_path).write_text(anomaly.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# decay
# ---------------------------------------------------------------------------


@risk.command("decay")
@click.option("--signal", "signal_path", required=True, type=click.Path(exists=True),
              help="Current PeerRiskSignal JSON.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Signal owner's signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the decayed PeerRiskSignal JSON.")
def risk_decay(signal_path: str, key_path: str, output_path: str) -> None:
    """Apply time decay to a PeerRiskSignal without a new evidence update."""
    signal = PeerRiskSignal.model_validate_json(Path(signal_path).read_text(encoding="utf-8"))
    sk = load_private_key(key_path)

    decayed = decay_risk_signal(signal, sk)
    Path(output_path).write_text(decayed.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] Signal decayed: {signal.signal:.4f} → {decayed.signal:.4f}")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# assess-seed
# ---------------------------------------------------------------------------


@risk.command("assess-seed")
@click.option("--signal", "signal_path", required=True, type=click.Path(exists=True),
              help="PeerRiskSignal JSON file.")
@click.option("--history", "history_paths", required=True, multiple=True,
              type=click.Path(exists=True),
              help="RiskSignalUpdate JSON files (pass once per update).")
@click.option("--seed-threshold", "threshold", type=float, default=0.5,
              help="Seed probability threshold for isolation (default 0.5).")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def risk_assess_seed(
    signal_path: str, history_paths: tuple[str, ...], threshold: float, fmt: str,
) -> None:
    """Assess whether a counterparty's update history matches adversarial seed patterns.

    Exits 0 if not isolated, 1 if isolated.
    """
    signal = PeerRiskSignal.model_validate_json(Path(signal_path).read_text(encoding="utf-8"))
    history = [
        RiskSignalUpdate.model_validate_json(Path(p).read_text(encoding="utf-8"))
        for p in history_paths
    ]

    report = assess_seed_isolation(signal, history, seed_threshold=threshold)

    if fmt == "json":
        click.echo(report.model_dump_json(indent=2))
    else:
        status = "[ISOLATED]" if report.isolated else "[OK]"
        click.echo(f"{status} Seed isolation assessment")
        click.echo(f"  Counterparty     : {report.to_sovereign_id}")
        click.echo(f"  History length   : {report.history_length}")
        click.echo(f"  Seed probability : {report.seed_probability:.3f}")
        click.echo(f"  Threshold        : {report.threshold_used}")
        click.echo(f"  CFS              : {report.credit_farming_score:.3f}")
        click.echo(f"  VDS              : {report.volatility_discontinuity_score:.3f}")
        click.echo(f"  SFS              : {report.streak_fragility_score:.3f}")
        click.echo(f"  Max streak       : {report.max_success_streak}")

    if report.isolated:
        raise click.exceptions.Exit(code=1)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@risk.command("show")
@click.option("--signal", "signal_path", required=True, type=click.Path(exists=True),
              help="PeerRiskSignal JSON to display.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def risk_show(signal_path: str, fmt: str) -> None:
    """Display current PeerRiskSignal state."""
    signal = PeerRiskSignal.model_validate_json(Path(signal_path).read_text(encoding="utf-8"))

    if fmt == "json":
        click.echo(json.dumps({
            "signal_id": signal.signal_id,
            "from_sovereign_id": signal.from_sovereign_id,
            "to_sovereign_id": signal.to_sovereign_id,
            "signal": signal.signal,
            "update_count": signal.update_count,
            "last_updated_at": signal.last_updated_at.isoformat(),
            "alpha": signal.alpha,
            "decay_lambda": signal.decay_lambda,
        }, indent=2))
    else:
        click.echo(f"PeerRiskSignal {signal.signal_id}")
        click.echo(f"  From     : {signal.from_sovereign_id}")
        click.echo(f"  To       : {signal.to_sovereign_id}")
        click.echo(f"  Signal   : {signal.signal:.4f}")
        click.echo(f"  Updates  : {signal.update_count}")
        click.echo(f"  Last upd : {signal.last_updated_at.isoformat()}")
        click.echo(f"  Alpha    : {signal.alpha}  λ={signal.decay_lambda}")
        click.echo(f"  Signed   : {'yes' if signal.signature else 'no'}")
