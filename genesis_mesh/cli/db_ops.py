"""``genesis-mesh na migrate-db`` and ``na verify-db`` (v0.60)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from ..models import GenesisBlock
from ..na_service.db import NADatabase
from ..na_service.storage import DatabaseConfigError, is_postgres_url
from ..na_service.storage.base import sqlite_path_from_url
from ..workflows.db_migration import MigrationError, migrate_sqlite_to_postgres, verify_database


def _na_public_key(genesis_path: Optional[Path]) -> Optional[str]:
    if genesis_path is None:
        return None
    genesis = GenesisBlock(**json.loads(genesis_path.read_text(encoding="utf-8")))
    return genesis.network_authority.public_key


def _sqlite_path(value: str) -> str:
    return sqlite_path_from_url(value) if value.startswith("sqlite:") else value


@click.command("migrate-db")
@click.option("--from", "source", required=True, help="Source SQLite database (path or sqlite:///path).")
@click.option("--to", "target", required=True, envvar="DATABASE_URL", help="Target postgresql:// URL (default: $DATABASE_URL).")
@click.option(
    "--genesis", "genesis_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None, help="Signed genesis block; enables signature checks of the evidence store.",
)
@click.option("--report", "report_path", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the migration report (JSON) here.")
def migrate_db(source: str, target: str, genesis_path: Optional[Path], report_path: Optional[Path]) -> None:
    """Copy an NA SQLite database into an empty PostgreSQL database and verify it.

    Stop the NA first. The SQLite file is opened read-only and left untouched.
    """
    if not is_postgres_url(target):
        raise click.ClickException("--to must be a postgresql:// URL")
    try:
        report = migrate_sqlite_to_postgres(_sqlite_path(source), target, na_public_key=_na_public_key(genesis_path))
    except (MigrationError, DatabaseConfigError) as exc:
        raise click.ClickException(str(exc)) from exc
    text = json.dumps(report, indent=2)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
    rows = sum(t["rows"] for t in report["tables"].values())
    click.echo(f"Migrated {rows} rows in {len(report['tables'])} tables to {report['target']}; verification passed.")
    if not report_path:
        click.echo(text)


@click.command("verify-db")
@click.option("--database-url", envvar="DATABASE_URL", default=None, help="postgresql:// URL (default: $DATABASE_URL).")
@click.option("--db-path", default=None, help="SQLite database path (when no URL is given).")
@click.option(
    "--genesis", "genesis_path", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None, help="Signed genesis block; enables signature checks of the evidence store.",
)
def verify_db(database_url: Optional[str], db_path: Optional[str], genesis_path: Optional[Path]) -> None:
    """Verify an NA database: policy digests, CRL continuity, evidence chains.

    Use after a restore or a migration. Exits non-zero when any check fails.
    """
    if not database_url and not db_path:
        raise click.ClickException("give --database-url (or DATABASE_URL) or --db-path")
    if db_path and not database_url and not Path(db_path).is_file():
        raise click.ClickException(f"database not found: {db_path}")
    try:
        db = NADatabase(db_path or ":memory:", database_url=database_url)
    except DatabaseConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        report = verify_database(db, _na_public_key(genesis_path))
    finally:
        db.close()
    click.echo(json.dumps({"database": db.db_path, **report.to_dict()}, indent=2))
    if not report.ok:
        raise SystemExit(1)
