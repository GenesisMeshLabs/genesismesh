"""CLI commands for Verifiable Logic Attestation.

trust attest create  -- create a signed ModelAttestation for a given execution context
trust attest verify  -- verify a ModelAttestation against an AttestationPolicy
trust attest policy  -- create a signed AttestationPolicy
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.attestation import AttestationPolicy, ModelAttestation, ToolManifest
from ..trust.logic_attestation import create_model_attestation, verify_model_attestation


@click.group("attest")
def attest() -> None:
    """Verifiable logic attestation — bind execution context to capabilities."""


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@attest.command("create")
@click.option("--agent-sovereign", "agent_sov", required=True,
              help="Agent sovereign ID signing this attestation.")
@click.option("--model-id", "model_id", required=True,
              help='Model identifier (e.g. "claude-sonnet-4-6").')
@click.option("--model-version", "model_version", required=True,
              help='Model version tag (e.g. "20251001").')
@click.option("--system-prompt-file", "prompt_file", required=True,
              type=click.Path(exists=True),
              help="Path to file containing the exact system prompt (UTF-8).")
@click.option("--tool-id", "tool_ids", multiple=True,
              help="Tool ID available to the agent. Pass once per tool.")
@click.option("--token-id", "token_id", default=None,
              help="Optional IBCT token_id to bind to this attestation.")
@click.option("--valid-for", "valid_for", type=int, default=300,
              help="Attestation validity in seconds (default 300).")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Agent Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed ModelAttestation JSON.")
def attest_create(
    agent_sov: str, model_id: str, model_version: str, prompt_file: str,
    tool_ids: tuple[str, ...], token_id: str | None,
    valid_for: int, key_path: str, output_path: str,
) -> None:
    """Create a signed ModelAttestation declaring current execution context."""
    sk = load_private_key(key_path)
    system_prompt = Path(prompt_file).read_text(encoding="utf-8")

    attestation = create_model_attestation(
        agent_sov, model_id, model_version, system_prompt, list(tool_ids), sk,
        token_id=token_id, valid_for_seconds=valid_for,
    )
    Path(output_path).write_text(attestation.model_dump_json(indent=2), encoding="utf-8")

    prompt_hash_short = attestation.system_prompt_hash[:16]
    click.echo(f"[OK] ModelAttestation {attestation.attestation_id}")
    click.echo(f"     Agent   : {agent_sov}")
    click.echo(f"     Model   : {model_id} ({model_version})")
    click.echo(f"     Prompt  : {prompt_hash_short}...")
    click.echo(f"     Tools   : {len(tool_ids)} declared")
    click.echo(f"     Expires : {attestation.expires_at.isoformat()}")
    click.echo(f"     Output  : {output_path}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@attest.command("verify")
@click.option("--attestation", "attest_path", required=True, type=click.Path(exists=True),
              help="ModelAttestation JSON file.")
@click.option("--policy", "policy_path", required=True, type=click.Path(exists=True),
              help="AttestationPolicy JSON file.")
@click.option("--public-key", "public_keys", required=True, multiple=True,
              help="Agent public key (base64 string). Pass once per key.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def attest_verify(
    attest_path: str, policy_path: str,
    public_keys: tuple[str, ...], fmt: str,
) -> None:
    """Verify a ModelAttestation against an AttestationPolicy.

    Exits 0 if valid, 1 if any check fails.
    """
    attestation = ModelAttestation.model_validate_json(
        Path(attest_path).read_text(encoding="utf-8")
    )
    policy = AttestationPolicy.model_validate_json(
        Path(policy_path).read_text(encoding="utf-8")
    )

    passed, reason = verify_model_attestation(attestation, policy, list(public_keys))

    if fmt == "json":
        click.echo(json.dumps({
            "passed": passed,
            "reason": reason,
            "attestation_id": attestation.attestation_id,
            "model_id": attestation.model_id,
        }, indent=2))
    else:
        status = "[OK]" if passed else "[FAIL]"
        click.echo(f"{status} {reason}")
        click.echo(f"  Attestation : {attestation.attestation_id}")
        click.echo(f"  Agent       : {attestation.agent_sovereign_id}")
        click.echo(f"  Model       : {attestation.model_id}")

    if not passed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


@attest.command("policy")
@click.option("--operator-sovereign", "operator_sov", required=True,
              help="Operator sovereign ID signing this policy.")
@click.option("--allow-model", "allow_models", multiple=True,
              help="Permitted model_id. Pass once per model. Empty = any model allowed.")
@click.option("--allow-prompt-hash", "allow_prompts", multiple=True,
              help="Permitted system_prompt_hash (hex). Pass once per hash.")
@click.option("--allow-tool-hash", "allow_tools", multiple=True,
              help="Permitted tool_manifest_hash (hex). Pass once per hash.")
@click.option("--require-bound-token", "require_token", is_flag=True, default=False,
              help="Require attestation.token_id to be set.")
@click.option("--valid-until", "valid_until_str", required=True,
              help="Policy validity end (ISO 8601, e.g. 2027-01-01T00:00:00Z).")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Operator Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed AttestationPolicy JSON.")
def attest_policy(
    operator_sov: str, allow_models: tuple[str, ...],
    allow_prompts: tuple[str, ...], allow_tools: tuple[str, ...],
    require_token: bool, valid_until_str: str, key_path: str, output_path: str,
) -> None:
    """Create a signed AttestationPolicy defining permitted execution contexts."""
    try:
        valid_until = datetime.fromisoformat(valid_until_str.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.ClickException(f"Invalid --valid-until: {exc}") from exc

    from ..crypto import sign_model as _sign_model  # noqa: PLC0415

    sk = load_private_key(key_path)
    policy = AttestationPolicy(
        operator_sovereign_id=operator_sov,
        allowed_model_ids=list(allow_models),
        allowed_system_prompt_hashes=list(allow_prompts),
        allowed_tool_manifest_hashes=list(allow_tools),
        require_bound_token=require_token,
        valid_until=valid_until,
    )
    sig = _sign_model(policy, sk, operator_sov)
    policy = policy.model_copy(update={"signature": sig})

    Path(output_path).write_text(policy.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] AttestationPolicy {policy.policy_id}")
    click.echo(f"     Operator    : {operator_sov}")
    click.echo(f"     Models      : {list(allow_models) or ['(any)']}")
    click.echo(f"     Valid until : {valid_until.isoformat()}")
    click.echo(f"     Output      : {output_path}")
