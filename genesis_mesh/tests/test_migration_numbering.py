"""Migration numbers are unique and contiguous (1.7.1).

Before 1.7.1 two branches that each added ``020_*.sql`` merged cleanly, and
on SQLite the second migration was then skipped for good: the version claim
failed as if another worker had applied it ("applied by another process").
``migration_files()`` now refuses a duplicate, a gap and a PostgreSQL
override without its shared migration, so such a merge fails every test run.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from genesis_mesh.na_service import db as db_module
from genesis_mesh.na_service.db import NADatabase


@pytest.fixture
def migrations(tmp_path, monkeypatch) -> Path:
    """A copy of the shipped migrations that the test may add files to."""
    copy = tmp_path / "migrations"
    shutil.copytree(db_module.MIGRATIONS_DIR, copy)
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", copy)
    return copy


def _next(migrations: Path) -> int:
    return max(version for version, _ in db_module.migration_files("sqlite")) + 1


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shipped_migrations_are_numbered_one_to_n_without_gaps(backend):
    versions = [version for version, _ in db_module.migration_files(backend)]
    assert versions == list(range(1, len(versions) + 1))


def test_two_branches_adding_the_same_migration_number_fail_at_load(migrations):
    n = _next(migrations)
    (migrations / f"{n:03d}_feature_a.sql").write_text("CREATE TABLE feature_a (id INTEGER PRIMARY KEY);\n")
    (migrations / f"{n:03d}_feature_b.sql").write_text("CREATE TABLE feature_b (id INTEGER PRIMARY KEY);\n")
    with pytest.raises(db_module.MigrationNumberingError, match=f"{n:03d}_feature_a.sql.*{n:03d}_feature_b.sql"):
        db_module.migration_files("sqlite")
    with pytest.raises(db_module.MigrationNumberingError):
        db_module.expected_schema_version()


def test_a_migration_number_collision_never_skips_a_migration_silently(tmp_path, migrations):
    """The critic's reproduction: both branches' tables exist, or the NA refuses to start."""
    n = _next(migrations)
    (migrations / f"{n:03d}_feature_a.sql").write_text("CREATE TABLE feature_a (id INTEGER PRIMARY KEY);\n")
    (migrations / f"{n:03d}_feature_b.sql").write_text("CREATE TABLE feature_b (id INTEGER PRIMARY KEY);\n")
    db = NADatabase(str(tmp_path / "na.db"))
    try:
        db.migrate()
    except RuntimeError as exc:
        assert f"{n:03d}" in str(exc)
        return
    tables = {row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    assert {"feature_a", "feature_b"} <= tables, "a migration sharing its number with another was skipped"


def test_a_gap_in_migration_numbers_fails_at_load(migrations):
    n = _next(migrations)
    (migrations / f"{n + 1:03d}_skips_one.sql").write_text("CREATE TABLE skips_one (id INTEGER PRIMARY KEY);\n")
    with pytest.raises(db_module.MigrationNumberingError, match=f"{n:03d}"):
        db_module.migration_files("sqlite")


def test_a_postgres_override_without_its_shared_migration_fails_at_load(migrations):
    n = _next(migrations)
    (migrations / f"{n:03d}_feature.sql").write_text("CREATE TABLE feature (id INTEGER PRIMARY KEY);\n")
    (migrations / f"{n:03d}_feature_renamed.postgres.sql").write_text("CREATE TABLE feature (id BIGINT);\n")
    with pytest.raises(db_module.MigrationNumberingError, match="feature_renamed.postgres.sql"):
        db_module.migration_files("postgres")


def test_a_migration_without_a_number_fails_at_load(migrations):
    (migrations / "feature.sql").write_text("CREATE TABLE feature (id INTEGER PRIMARY KEY);\n")
    with pytest.raises(db_module.MigrationNumberingError, match="feature.sql"):
        db_module.migration_files("sqlite")


@pytest.mark.sqlite_only
def test_sqlite_migrate_rereads_applied_versions_before_each_migration(tmp_path, monkeypatch):
    """A migration another worker recorded after this one started is not applied again."""
    path = str(tmp_path / "na.db")
    db = NADatabase(path)
    first, second = db_module.migration_files("sqlite")[:2]

    def files(backend):
        yield first
        # Another worker records the second migration while this one applies the first.
        with sqlite3.connect(path) as other:
            other.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (second[0], datetime.now(timezone.utc).isoformat()),
            )
        yield second

    expected = db_module.expected_schema_version()
    monkeypatch.setattr(db_module, "expected_schema_version", lambda: expected)
    applied: list[int] = []
    real_apply = db._apply_sqlite_migration
    monkeypatch.setattr(db_module, "migration_files", files)
    monkeypatch.setattr(db, "_apply_sqlite_migration", lambda version, sql: (applied.append(version), real_apply(version, sql)))
    db.migrate()
    assert applied == [first[0]]
