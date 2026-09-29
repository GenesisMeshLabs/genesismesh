"""Declarative boundary policy CLI commands — trust boundary-policy (v0.58).

Offline helpers for operators authoring and auditing boundary policies:
validate intent or signed policies against the built-in gate registry, verify
a policy signature, explain a policy-bound decision, and list gate types.
Publishing and activation go through the Network Authority admin API.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from ..models.boundary_policy import BoundaryPolicy
from ..models.context import BoundaryDecision
from ..trust.context import GateRegistry, validate_boundary_policy, verify_boundary_policy

_FORMAT = click.option(
    "--format", "fmt", type=click.Choice(["human", "json"]), default="human",
    help="Output format.",
)


def _load_json(path: str, label: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load {label} {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise click.ClickException(f"{label} {path!r} must be a JSON object")
    return data


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


def _policy_from_file(data: dict[str, Any]) -> BoundaryPolicy:
    """Parse a signed policy, or preview an unsigned intent document."""
    if {"version", "signature", "issued_at", "issued_by", "issuer_sovereign_id"} & data.keys():
        return BoundaryPolicy.model_validate(data)
    return BoundaryPolicy.model_validate({
        **data,
        "version": 1,
        "issued_at": datetime.now(timezone.utc),
        "issued_by": "local-preview",
        "issuer_sovereign_id": "local-preview",
    })


@click.group("boundary-policy")
def boundary_policy() -> None:
    """Validate, verify and explain declarative boundary policies."""


@boundary_policy.command("validate")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Policy intent JSON or signed BoundaryPolicy JSON.")
@_FORMAT
def validate_cmd(file_path: str, fmt: str) -> None:
    """Validate a policy against the built-in trusted gate registry.

    Example:

    \b
        genesis-mesh trust boundary-policy validate --file policy.json
    """
    data = _load_json(file_path, "policy")
    try:
        policy = _policy_from_file(data)
    except (ValidationError, KeyError, TypeError) as exc:
        raise click.ClickException(f"Policy is malformed: {exc}") from exc
    result = validate_boundary_policy(policy, GateRegistry.default())
    if fmt == "json":
        click.echo(json.dumps({**result.to_dict(), "policy_id": policy.policy_id}, indent=2))
    else:
        click.echo(f"Policy  : {policy.policy_id}")
        click.echo(f"Gates   : {len(policy.gates)}")
        click.echo(f"Valid   : {'yes' if result.valid else 'no'}")
        for issue in result.issues:
            where = f" [{issue.gate_id}]" if issue.gate_id else ""
            click.echo(f"  - {issue.code}{where}: {issue.message}")
    sys.exit(0 if result.valid else 1)


@boundary_policy.command("verify")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Signed BoundaryPolicy JSON.")
@click.option("--public-key", "public_key_input", required=True,
              help="Issuer (NA) public key: base64 string or path to a public key file.")
@_FORMAT
def verify_cmd(file_path: str, public_key_input: str, fmt: str) -> None:
    """Verify a signed boundary policy.

    Example:

    \b
        genesis-mesh trust boundary-policy verify \\
            --file policy.signed.json --public-key keys/na.pub
    """
    try:
        policy = BoundaryPolicy.model_validate(_load_json(file_path, "policy"))
    except ValidationError as exc:
        raise click.ClickException(f"Policy is malformed: {exc}") from exc
    result = verify_boundary_policy(policy, [_pub_key_from_input(public_key_input)])
    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"Policy  : {result.policy_id} v{result.version}")
        click.echo(f"Digest  : {result.policy_digest}")
        click.echo(f"Result  : {'VALID' if result.valid else 'INVALID'} ({result.reason})")
    sys.exit(0 if result.valid else 1)


@boundary_policy.command("explain")
@click.option("--decision", "decision_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Policy-bound BoundaryDecision JSON (from /admin/boundary/evaluate).")
@_FORMAT
def explain_cmd(decision_path: str, fmt: str) -> None:
    """Explain which policies, configured gates and attestation produced a decision.

    Example:

    \b
        genesis-mesh trust boundary-policy explain --decision decision.json
    """
    data = _load_json(decision_path, "decision")
    if "decision" in data and isinstance(data["decision"], dict):
        data = data["decision"]
    try:
        decision = BoundaryDecision.model_validate(data)
    except ValidationError as exc:
        raise click.ClickException(f"Decision is malformed: {exc}") from exc
    binding = decision.policy_binding
    if binding is None:
        raise click.ClickException("Decision has no policy_binding (not produced by a policy-aware evaluation)")
    attestation = decision.attestation_binding
    if fmt == "json":
        out: dict[str, Any] = {
            "decision_id": decision.decision_id,
            "authorized": decision.authorized,
            "denial_reason": decision.denial_reason,
            "policy_binding": binding.model_dump(mode="json"),
        }
        if attestation is not None:
            out["attestation_binding"] = attestation.model_dump(mode="json")
        click.echo(json.dumps(out, indent=2))
        return
    click.echo(f"Decision   : {decision.decision_id}")
    click.echo(f"Authorized : {decision.authorized}")
    if decision.denial_reason:
        click.echo(f"Reason     : {decision.denial_reason}")
    if attestation is not None:
        click.echo(f"Attestation: {attestation.attestation_id}")
        click.echo(f"  subject  : {attestation.subject_id or '-'}")
        click.echo(f"  issuer   : {attestation.issuer_sovereign_id or '-'}")
        digest = attestation.attestation_digest
        click.echo(f"  digest   : {digest[:16] + '…' if digest else '-'}")
        click.echo(f"  revocation seq checked: {attestation.revocation_seq_checked}")
    click.echo(f"Resolution : {binding.resolution_status}"
               + (f" ({binding.resolution_failure})" if binding.resolution_failure else ""))
    click.echo(f"Policy set : {binding.policy_set_digest}")
    if not binding.policies:
        click.echo("Policies   : none applied")
    for p in binding.policies:
        click.echo(f"Policy     : {p.policy_id} v{p.version}  digest={p.policy_digest[:16]}…")
    for e in binding.gate_evaluations:
        mark = "PASS" if e.passed else "FAIL"
        click.echo(f"  {mark:<4} {e.policy_id}/{e.gate_id}  {e.gate_type}  mode={e.mode}  outcome={e.outcome}")


@boundary_policy.command("gate-types")
@_FORMAT
def gate_types_cmd(fmt: str) -> None:
    """List the trusted gate types policies may reference.

    Example:

    \b
        genesis-mesh trust boundary-policy gate-types
    """
    described = GateRegistry.default().describe()
    if fmt == "json":
        click.echo(json.dumps(described, indent=2))
        return
    for item in described:
        fields = ", ".join(
            f"{name}{'' if spec['required'] else '?'}" for name, spec in item["config"].items()
        )
        click.echo(f"{item['gate_type']:<24} {fields}")
