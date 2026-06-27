"""Execution Evidence hash chain CLI commands (trust execution subgroup)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.context import BoundaryDecision
from ..models.execution import EvidenceChain, ExecutionEvidence
from ..trust.execution import (
    EvidenceChainVerificationResult,
    record_execution,
    verify_evidence_chain,
)


# ---------------------------------------------------------------------------
# execution group
# ---------------------------------------------------------------------------


@click.group()
def execution() -> None:
    """Execution Evidence — record and verify tamper-evident execution chains."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_decision(path: str) -> BoundaryDecision:
    try:
        return BoundaryDecision.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load decision {path!r}: {exc}") from exc


def _load_evidence(path: str) -> ExecutionEvidence:
    try:
        return ExecutionEvidence.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load evidence {path!r}: {exc}") from exc


def _write_json(obj: Any, output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(obj, "model_dump_json"):
        out.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return out


def _parse_public_key(value: str) -> str:
    path = Path(value)
    if path.exists():
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return value


# ---------------------------------------------------------------------------
# trust execution record
# ---------------------------------------------------------------------------


@execution.command("record")
@click.option(
    "--decision", "decision_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="BoundaryDecision JSON that authorized this execution.",
)
@click.option(
    "--capability", required=True,
    help="Capability identifier that was executed.",
)
@click.option(
    "--executor", required=True,
    help="Executor sovereign ID.",
)
@click.option(
    "--outcome",
    type=click.Choice(["success", "failure", "partial"]),
    default="success",
    help="Execution outcome.",
)
@click.option(
    "--outcome-detail", "outcome_detail", default=None,
    help="Optional human-readable outcome detail.",
)
@click.option(
    "--params", "params_json", default="{}",
    help="JSON object of execution parameters.",
)
@click.option(
    "--sequence", "sequence_no", required=True, type=int,
    help="Sequence number (1-based, must increment by 1 within a decision).",
)
@click.option(
    "--prior", "prior_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the prior ExecutionEvidence JSON (for chain linking).",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Executor's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed ExecutionEvidence JSON.",
)
def execution_record(
    decision_path: str,
    capability: str,
    executor: str,
    outcome: str,
    outcome_detail: str | None,
    params_json: str,
    sequence_no: int,
    prior_path: str | None,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Create and sign an ExecutionEvidence record.

    With --prior, links this record to the prior via prev_evidence_digest,
    forming a tamper-evident chain.

    Example (first record):

    \b
        genesis-mesh trust execution record \\
            --decision decision.json \\
            --capability transactions.read \\
            --executor bank-a \\
            --outcome success \\
            --sequence 1 \\
            --signing-key bank.key --key-id bank-2026 \\
            --output evidence-1.json

    Example (chained record):

    \b
        genesis-mesh trust execution record \\
            --decision decision.json \\
            --capability transactions.read \\
            --executor bank-a \\
            --outcome success \\
            --sequence 2 \\
            --prior evidence-1.json \\
            --signing-key bank.key --key-id bank-2026 \\
            --output evidence-2.json
    """
    decision = _load_decision(decision_path)
    prior: ExecutionEvidence | None = _load_evidence(prior_path) if prior_path else None

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid --params JSON: {exc}") from exc

    private_key = load_private_key(signing_key)

    ev = record_execution(
        decision,
        executor_sovereign_id=executor,
        executed_capability=capability,
        outcome=outcome,
        signing_key=private_key,
        issued_by=key_id,
        sequence_no=sequence_no,
        execution_parameters=params,
        outcome_detail=outcome_detail,
        prior_record=prior,
    )

    out = _write_json(ev, output)
    click.echo(f"Evidence  : {ev.evidence_id}")
    click.echo(f"Sequence  : {ev.sequence_no}")
    click.echo(f"Decision  : {ev.decision_id}")
    click.echo(f"Capability: {ev.executed_capability}")
    click.echo(f"Outcome   : {ev.outcome}")
    if ev.prev_evidence_digest:
        click.echo(f"Prev digest: {ev.prev_evidence_digest[:16]}...")
    else:
        click.echo(f"Prev digest: (none — first in chain)")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust execution verify
# ---------------------------------------------------------------------------


@execution.command("verify")
@click.option(
    "--decision-id", "decision_id", required=True,
    help="Expected BoundaryDecision ID for all records in the chain.",
)
@click.option(
    "--evidence", "evidence_paths", multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="ExecutionEvidence JSON files in chain order (seq 1, 2, 3, ...). Repeatable.",
)
@click.option(
    "--key", "executor_keys", multiple=True,
    help="sovereign_id:public_key_b64 pair for executor verification. Repeatable.",
)
@click.option(
    "--expected-capability", "expected_capability", default=None,
    help="If set, all records must execute this capability.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def execution_verify(
    decision_id: str,
    evidence_paths: tuple[str, ...],
    executor_keys: tuple[str, ...],
    expected_capability: str | None,
    output_format: str,
) -> None:
    """Verify a chain of ExecutionEvidence records.

    Checks: sequence numbers, prev_evidence_digest linkage, and signatures.
    Exit code 0 if verified, 1 on any failure.

    Example:

    \b
        genesis-mesh trust execution verify \\
            --decision-id <uuid> \\
            --evidence evidence-1.json \\
            --evidence evidence-2.json \\
            --key bank-a:<bank-pub-b64>
    """
    records = [_load_evidence(p) for p in evidence_paths]
    chain = EvidenceChain(decision_id=decision_id, records=records)

    per_executor: dict[str, list[str]] = {}
    for entry in executor_keys:
        if ":" not in entry:
            raise click.ClickException(
                f"--key must be 'sovereign_id:public_key_b64', got {entry!r}"
            )
        sid, pub = entry.split(":", 1)
        per_executor.setdefault(sid.strip(), []).append(_parse_public_key(pub.strip()))

    result = verify_evidence_chain(
        chain,
        executor_public_keys_by_sovereign=per_executor,
        expected_capability=expected_capability,
    )

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.verified else "FAIL"
        colour = "green" if result.verified else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Chain     : {result.chain_length} record(s)")
        if result.failed_at_sequence is not None:
            click.echo(f"Failed at : sequence {result.failed_at_sequence}")

    if not result.verified:
        sys.exit(1)
