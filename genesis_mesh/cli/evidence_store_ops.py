"""Evidence store CLI commands (v0.59): verify an exported evidence log offline."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
from .support import public_key_value


@click.group("evidence")
def evidence() -> None:
    """Evidence store — verify exported decision and execution history offline."""


@evidence.command("verify-export")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="gm.evidence.event JSON Lines from GET /admin/evidence/export.")
@click.option("--na-public-key", "na_keys", required=True, multiple=True,
              help="NA public key: base64 or path to a public key file. Repeatable.")
@click.option("--executor-keys", "executor_keys_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="JSON from GET /admin/evidence/executor-keys.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify_export(file_path: str, na_keys: tuple[str, ...], executor_keys_path: str, fmt: str) -> None:
    """Verify an evidence export: envelopes, store chain, signatures and chains.

    Example:

    \b
        genesis-mesh evidence verify-export \\
            --file export.jsonl --na-public-key <base64> \\
            --executor-keys executor-keys.json
    """
    try:
        events = parse_export_lines(Path(file_path).read_text(encoding="utf-8").splitlines())
    except ValueError as exc:
        raise click.ClickException(f"Export is malformed: {exc}") from exc
    raw_keys = json.loads(Path(executor_keys_path).read_text(encoding="utf-8"))
    rows = raw_keys.get("executor_keys", raw_keys) if isinstance(raw_keys, dict) else raw_keys
    keys = {
        r["key_id"]: ExecutorKey(
            key_id=r["key_id"], public_key=r["public_key"],
            executor_sovereign_id=r["executor_sovereign_id"], retired=bool(r.get("retired_at")),
        )
        for r in rows
    }
    result = verify_evidence_events(events, na_public_keys=[public_key_value(k) for k in na_keys], executor_keys=keys, contiguous=True)
    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"Entries    : {result.checked_entries}")
        click.echo(f"Decisions  : {result.decisions}")
        click.echo(f"Executions : {result.executions}")
        click.echo(f"Result     : {'VERIFIED' if result.verified else 'FAILED'}")
        for f in result.failures:
            click.echo(f"  - #{f['store_sequence']}: {f['reason']} {f['detail']}".rstrip())
    if not result.verified:
        raise SystemExit(1)
