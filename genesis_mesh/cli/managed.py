"""Managed sovereign operational CLI commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import click

from genesis_mesh.na_service.db import NADatabase


REDACTED = "<redacted>"
SENSITIVE_KEY_PARTS = (
    "admin_signature",
    "body",
    "invite_token",
    "na_private_key",
    "nonce",
    "operator_private_key",
    "private_key",
    "request_body",
    "signature",
    "token",
)


@click.group(name="managed")
def managed() -> None:
    """Managed sovereign backup, restore, and audit operations."""


@managed.command("backup")
@click.option(
    "--db-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Network Authority SQLite database path.",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Destination backup path.",
)
def backup(db_path: Path, output: Path) -> None:
    """Create a consistent SQLite backup using SQLite's online backup API."""
    output.parent.mkdir(parents=True, exist_ok=True)
    db = NADatabase(str(db_path))
    try:
        db.backup(str(output))
    finally:
        db.conn.close()
    click.echo(json.dumps({"db_path": str(db_path), "backup_path": str(output)}, indent=2))


@managed.command("restore")
@click.option(
    "--db-path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Network Authority SQLite database path to replace.",
)
@click.option(
    "--backup",
    "backup_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Backup database to restore from.",
)
@click.option(
    "--pre-restore-backup",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional destination for a copy of the current DB before restore.",
)
@click.option("--yes", is_flag=True, help="Confirm the offline restore operation.")
def restore(
    db_path: Path,
    backup_path: Path,
    pre_restore_backup: Path | None,
    yes: bool,
) -> None:
    """Restore a Network Authority database from a backup file.

    Stop the Network Authority before running this command. The helper refuses
    to run without --yes because replacing a live DB file is destructive.
    """
    if not yes:
        raise click.ClickException(
            "Refusing to restore without --yes. Stop the Network Authority first."
        )
    _validate_sqlite_backup(backup_path)
    if db_path.exists() and pre_restore_backup is not None:
        pre_restore_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, pre_restore_backup)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, db_path)
    click.echo(
        json.dumps(
            {
                "db_path": str(db_path),
                "restored_from": str(backup_path),
                "pre_restore_backup": str(pre_restore_backup) if pre_restore_backup else None,
            },
            indent=2,
        )
    )


@managed.command("audit-export")
@click.option(
    "--db-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Network Authority SQLite database path.",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Destination audit export path.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["jsonl", "json"]),
    default="jsonl",
    show_default=True,
    help="Audit export format.",
)
@click.option("--event-type", default=None, help="Optional event type filter.")
def audit_export(
    db_path: Path,
    output: Path,
    output_format: str,
    event_type: str | None,
) -> None:
    """Export redacted Network Authority audit events."""
    db = NADatabase(str(db_path))
    try:
        events = [_redact_event(event) for event in db.list_audit_events()]
    finally:
        db.conn.close()
    if event_type:
        events = [event for event in events if event.get("event_type") == event_type]

    output.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "jsonl":
        output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
    else:
        output.write_text(json.dumps(events, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    click.echo(
        json.dumps(
            {
                "db_path": str(db_path),
                "output": str(output),
                "format": output_format,
                "event_count": len(events),
            },
            indent=2,
        )
    )


def _validate_sqlite_backup(path: Path) -> None:
    """Reject obvious non-NA SQLite files before restore."""
    db = NADatabase(str(path))
    try:
        has_schema = db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        has_audit = db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
        ).fetchone()
    finally:
        db.conn.close()
    if not has_schema or not has_audit:
        raise click.ClickException(f"Backup does not look like a Genesis Mesh NA database: {path}")


def _redact_event(value: Any) -> Any:
    """Redact sensitive fields from exported audit payloads."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact_event(item)
        return redacted
    if isinstance(value, list):
        return [_redact_event(item) for item in value]
    return value
