"""CLI commands for Context-Injection Defense Gate.

trust context commit  -- commit to base context before execution
trust context verify  -- verify final context matches committed base + declared segments
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.context_integrity import (
    ContextAppendSegment,
    ContextIntegrityRecord,
    ContextTree,
)
from ..trust.context_integrity import create_context_integrity_record, verify_context_integrity


@click.group("integrity")
def integrity() -> None:
    """Context-injection defense — commit and verify execution context."""


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


@integrity.command("commit")
@click.option("--agent-sovereign", "agent_sov", required=True,
              help="Agent sovereign ID signing this record.")
@click.option("--decision-id", "decision_id", required=True,
              help="BoundaryDecision ID this commitment belongs to.")
@click.option("--system-prompt-file", "prompt_file", required=True,
              type=click.Path(exists=True),
              help="Path to the system prompt file (UTF-8).")
@click.option("--max-turns", "max_turns", type=int, default=20,
              help="Maximum number of user/assistant turns expected (default 20).")
@click.option("--max-tool-results", "max_tool_results", type=int, default=50,
              help="Maximum number of tool result turns expected (default 50).")
@click.option("--max-total-tokens", "max_total_tokens", type=int, default=8192,
              help="Hard token cap for the entire execution (default 8192).")
@click.option("--valid-for", "valid_for", type=int, default=600,
              help="Commitment validity in seconds (default 600).")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Agent Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed ContextIntegrityRecord JSON.")
def context_commit(
    agent_sov: str, decision_id: str, prompt_file: str,
    max_turns: int, max_tool_results: int, max_total_tokens: int,
    valid_for: int, key_path: str, output_path: str,
) -> None:
    """Commit to a base context before execution begins.

    Creates a signed ContextIntegrityRecord capturing the base context hash
    and the declared growth bounds. Any undeclared context growth detected at
    verify time is treated as a potential injection.
    """
    sk = load_private_key(key_path)
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    base_context = ContextTree(
        system_prompt_hash=prompt_hash,
        turn_count=0,
        message_hashes=[],
        tool_result_hashes=[],
        total_token_estimate=len(prompt.split()),
    )

    record = create_context_integrity_record(
        agent_sov, decision_id, base_context, [],
        sk, max_total_tokens=max_total_tokens, valid_for_seconds=valid_for,
    )
    Path(output_path).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"[OK] ContextIntegrityRecord {record.record_id}")
    click.echo(f"     Agent      : {agent_sov}")
    click.echo(f"     Decision   : {decision_id}")
    click.echo(f"     Base hash  : {record.committed_base_context_hash[:16]}...")
    click.echo(f"     Max tokens : {max_total_tokens}")
    click.echo(f"     Expires    : {record.expires_at.isoformat()}")
    click.echo(f"     Output     : {output_path}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@integrity.command("verify")
@click.option("--record", "record_path", required=True, type=click.Path(exists=True),
              help="ContextIntegrityRecord JSON file.")
@click.option("--final-context", "final_ctx_path", required=True, type=click.Path(exists=True),
              help="ContextTree JSON representing the final execution context.")
@click.option("--segment", "segment_jsons", multiple=True,
              help="JSON string for each observed ContextAppendSegment. Pass once per segment.")
@click.option("--public-key", "public_keys", required=True, multiple=True,
              help="Agent public key (base64). Pass once per key.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def context_verify(
    record_path: str, final_ctx_path: str,
    segment_jsons: tuple[str, ...],
    public_keys: tuple[str, ...], fmt: str,
) -> None:
    """Verify final context matches the committed base plus declared segments.

    Exits 0 if valid, 1 if any check fails.
    """
    record = ContextIntegrityRecord.model_validate_json(
        Path(record_path).read_text(encoding="utf-8")
    )
    final_context = ContextTree.model_validate_json(
        Path(final_ctx_path).read_text(encoding="utf-8")
    )
    observed: list[ContextAppendSegment] = [
        ContextAppendSegment.model_validate_json(s) for s in segment_jsons
    ]

    passed, reason, report = verify_context_integrity(
        record, final_context, observed, list(public_keys)
    )

    if fmt == "json":
        out: dict[str, object] = {
            "passed": passed,
            "reason": reason,
            "record_id": record.record_id,
            "agent_sovereign_id": record.agent_sovereign_id,
        }
        if report is not None:
            out["violation"] = {
                "type": report.violation_type,
                "committed": report.committed_value,
                "observed": report.observed_value,
            }
        click.echo(json.dumps(out, indent=2))
    else:
        status = "[OK]" if passed else "[FAIL]"
        click.echo(f"{status} {reason}")
        click.echo(f"  Record  : {record.record_id}")
        click.echo(f"  Agent   : {record.agent_sovereign_id}")
        if report is not None:
            click.echo(f"  Detail  : {report.committed_value} → {report.observed_value}")

    if not passed:
        sys.exit(1)
