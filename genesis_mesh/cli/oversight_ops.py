"""Human Oversight CLI commands — trust oversight evaluate/propose/approve/reject/verify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.oversight import (
    DualSignedCommitment,
    HumanApprovalRequest,
    HumanOversightPolicy,
)
from ..trust.oversight import (
    approve_commitment,
    evaluate_oversight_policy,
    propose_commitment,
    reject_commitment,
    verify_dual_signed_commitment,
)


def _load_json(path: str, label: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load {label} {path!r}: {exc}") from exc


def _pub_key_from_input(public_key_input: str) -> str:
    key_path = Path(public_key_input)
    if key_path.exists():
        lines = [
            ln.strip()
            for ln in key_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return public_key_input


@click.group("oversight")
def oversight() -> None:
    """Human Oversight — evaluate policies, propose, approve, and verify high-stakes actions."""


@oversight.command("evaluate")
@click.option(
    "--policy", "policy_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the HumanOversightPolicy JSON.",
)
@click.option(
    "--action", "action_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the proposed action JSON (must include 'capability' key).",
)
@click.option("--requester", required=True, help="Requesting sovereign ID.")
@click.option("--recent-count", "recent_count", default=0, type=int,
              help="Recent action count (for frequency_limit check).")
@click.option("--anomaly", is_flag=True, default=False,
              help="Set the anomaly flag (forces block).")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def oversight_evaluate(
    policy_path: str, action_path: str, requester: str,
    recent_count: int, anomaly: bool, output_format: str,
) -> None:
    """Evaluate a HumanOversightPolicy against a proposed action.

    Prints the escalation result and per-check outcomes.  Exits 0=automatic,
    1=human_approve, 2=block.

    Example:

    \b
        genesis-mesh trust oversight evaluate \\
            --policy policy.json --action action.json --requester bank-b
    """
    try:
        policy = HumanOversightPolicy.model_validate(_load_json(policy_path, "policy"))
    except Exception as exc:
        raise click.ClickException(f"Cannot parse policy: {exc}") from exc
    action = _load_json(action_path, "action")

    evaluation = evaluate_oversight_policy(
        policy, action, requester, recent_action_count=recent_count, anomaly=anomaly,
    )

    if output_format == "json":
        click.echo(json.dumps(evaluation.to_dict(), indent=2))
    else:
        colours = {"automatic": "green", "human_approve": "yellow", "block": "red"}
        result = evaluation.result
        click.echo(click.style(f"Result: {result.upper()}", fg=colours.get(result, "white"), bold=True))
        click.echo("")
        click.echo("Checks:")
        for name, outcome in evaluation.checks:
            colour = {"pass": "green", "escalate": "yellow", "block": "red"}.get(outcome, "white")
            click.echo(f"  {click.style(outcome.upper(), fg=colour):12s}  {name}")
        if evaluation.escalation_reasons:
            click.echo("")
            click.echo("Escalation reasons:")
            for r in evaluation.escalation_reasons:
                click.echo(f"  - {r}")

    sys.exit({"automatic": 0, "human_approve": 1, "block": 2}.get(evaluation.result, 2))


@oversight.command("propose")
@click.option(
    "--policy", "policy_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the HumanOversightPolicy JSON.",
)
@click.option(
    "--action", "action_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the proposed action JSON.",
)
@click.option("--requester", required=True, help="Requesting sovereign ID.")
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Agent Ed25519 private key.",
)
@click.option("--key-id", default="agent", help="Key identifier in the request signature.")
@click.option("--approval-window", "approval_window", default=300, type=int,
              help="Seconds the human has to approve (default: 300).")
@click.option("--recent-count", "recent_count", default=0, type=int)
@click.option("--anomaly", is_flag=True, default=False)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed HumanApprovalRequest JSON.",
)
def oversight_propose(
    policy_path: str, action_path: str, requester: str,
    signing_key: str, key_id: str, approval_window: int,
    recent_count: int, anomaly: bool, output: str,
) -> None:
    """Sign and emit a HumanApprovalRequest for a high-stakes action.

    Example:

    \b
        genesis-mesh trust oversight propose \\
            --policy policy.json --action action.json \\
            --requester bank-b --signing-key agent.key \\
            --output request.json
    """
    try:
        policy = HumanOversightPolicy.model_validate(_load_json(policy_path, "policy"))
    except Exception as exc:
        raise click.ClickException(f"Cannot parse policy: {exc}") from exc
    action = _load_json(action_path, "action")

    try:
        private_key = load_private_key(signing_key)
    except Exception as exc:
        raise click.ClickException(f"Cannot load signing key: {exc}") from exc

    try:
        request, evaluation = propose_commitment(
            policy, action, requester, private_key,
            issued_by=key_id, approval_window_seconds=approval_window,
            recent_action_count=recent_count, anomaly=anomaly,
        )
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Request  : {request.request_id}")
    click.echo(f"Escalates: {', '.join(evaluation.escalation_reasons)}")
    click.echo(f"Expires  : {request.expires_at.isoformat()}")
    click.echo(f"Output   : {out_path}")


@oversight.command("approve")
@click.option(
    "--request", "request_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed HumanApprovalRequest JSON.",
)
@click.option(
    "--policy", "policy_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the HumanOversightPolicy JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Human custodian Ed25519 private key.",
)
@click.option("--key-id", default="human", help="Key identifier in the commitment signature.")
@click.option("--note", default=None, help="Optional approval note.")
@click.option("--commitment-valid-for", "commitment_valid_for", default=600, type=int,
              help="Commitment validity seconds (default: 600).")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the DualSignedCommitment JSON.",
)
def oversight_approve(
    request_path: str, policy_path: str,
    signing_key: str, key_id: str, note: str | None,
    commitment_valid_for: int, output: str,
) -> None:
    """Human custodian approves a HumanApprovalRequest.

    Emits a DualSignedCommitment with both the agent signature (from the request)
    and the human custodian's countersignature.

    Example:

    \b
        genesis-mesh trust oversight approve \\
            --request request.json --policy policy.json \\
            --signing-key human.key --output commitment.json
    """
    try:
        request = HumanApprovalRequest.model_validate_json(
            Path(request_path).read_text(encoding="utf-8")
        )
        policy = HumanOversightPolicy.model_validate(_load_json(policy_path, "policy"))
    except Exception as exc:
        raise click.ClickException(f"Cannot parse inputs: {exc}") from exc

    try:
        private_key = load_private_key(signing_key)
    except Exception as exc:
        raise click.ClickException(f"Cannot load signing key: {exc}") from exc

    response, commitment = approve_commitment(
        request, policy, private_key,
        issued_by=key_id, commitment_valid_for_seconds=commitment_valid_for, note=note,
    )

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(commitment.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Commitment : {commitment.commitment_id}")
    click.echo(f"Fully signed: {commitment.is_fully_signed()}")
    click.echo(f"Expires     : {commitment.expires_at.isoformat()}")
    click.echo(f"Output      : {out_path}")


@oversight.command("reject")
@click.option(
    "--request", "request_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed HumanApprovalRequest JSON.",
)
@click.option(
    "--policy", "policy_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the HumanOversightPolicy JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Human custodian Ed25519 private key.",
)
@click.option("--key-id", default="human")
@click.option("--note", default=None, help="Optional rejection note.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the HumanApprovalResponse JSON.",
)
def oversight_reject(
    request_path: str, policy_path: str,
    signing_key: str, key_id: str, note: str | None, output: str,
) -> None:
    """Human custodian rejects a HumanApprovalRequest.

    Example:

    \b
        genesis-mesh trust oversight reject \\
            --request request.json --policy policy.json \\
            --signing-key human.key --note "denied: unusual counterparty" \\
            --output response.json
    """
    try:
        request = HumanApprovalRequest.model_validate_json(
            Path(request_path).read_text(encoding="utf-8")
        )
        policy = HumanOversightPolicy.model_validate(_load_json(policy_path, "policy"))
    except Exception as exc:
        raise click.ClickException(f"Cannot parse inputs: {exc}") from exc

    try:
        private_key = load_private_key(signing_key)
    except Exception as exc:
        raise click.ClickException(f"Cannot load signing key: {exc}") from exc

    response = reject_commitment(request, policy, private_key, issued_by=key_id, note=note)

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(response.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Response : {response.response_id}")
    click.echo(f"Approved : {response.approved}")
    click.echo(f"Output   : {out_path}")


@oversight.command("verify")
@click.option(
    "--commitment", "commitment_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the DualSignedCommitment JSON.",
)
@click.option(
    "--agent-key", "agent_key_input", required=True,
    help="Agent public key: base64 string or path to file.",
)
@click.option(
    "--human-key", "human_key_input", required=True,
    help="Human custodian public key: base64 string or path to file.",
)
@click.option(
    "--request", "request_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Optional HumanApprovalRequest JSON to cross-check request_id.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def oversight_verify(
    commitment_path: str, agent_key_input: str, human_key_input: str,
    request_path: str | None, output_format: str,
) -> None:
    """Verify both signatures on a DualSignedCommitment.

    Example:

    \b
        genesis-mesh trust oversight verify \\
            --commitment commitment.json \\
            --agent-key agent.pub \\
            --human-key human.pub
    """
    try:
        commitment = DualSignedCommitment.model_validate_json(
            Path(commitment_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load commitment: {exc}") from exc

    agent_pub = _pub_key_from_input(agent_key_input)
    human_pub = _pub_key_from_input(human_key_input)

    request = None
    if request_path:
        try:
            request = HumanApprovalRequest.model_validate_json(
                Path(request_path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise click.ClickException(f"Cannot parse request: {exc}") from exc

    result = verify_dual_signed_commitment(commitment, [agent_pub], [human_pub], request=request)

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.valid else "FAIL"
        colour = "green" if result.valid else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Commitment : {result.commitment_id}")
        if result.valid:
            click.echo(f"Fully signed: {commitment.is_fully_signed()}")
            click.echo(f"Expires     : {commitment.expires_at.isoformat()}")

    if not result.valid:
        sys.exit(1)
