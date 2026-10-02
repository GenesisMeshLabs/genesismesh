"""SQLite migrations when several workers start on one file (v0.63.1).

Gunicorn workers each open the database and migrate at startup. Before
v0.63.1 two workers could both see a migration as pending and both apply it;
the loser failed with "duplicate column name" and gunicorn shut down.
"""

from __future__ import annotations

import multiprocessing
import sqlite3

import pytest

from genesis_mesh.na_service.db import NADatabase, expected_schema_version, migration_files

WORKERS = 6


def _migrate(path: str, barrier) -> None:
    barrier.wait()
    NADatabase(path).migrate()


def _versions(path: str) -> list[int]:
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("SELECT version FROM schema_version ORDER BY version")]


@pytest.mark.parametrize("attempt", range(3))
def test_workers_migrating_one_file_together_all_start(tmp_path, attempt):
    path = str(tmp_path / "na.db")
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(WORKERS)
    workers = [ctx.Process(target=_migrate, args=(path, barrier)) for _ in range(WORKERS)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=120)
    assert [worker.exitcode for worker in workers] == [0] * WORKERS
    assert _versions(path) == [version for version, _ in migration_files("sqlite")]


def test_a_migration_applied_by_another_process_is_skipped(tmp_path):
    path = str(tmp_path / "na.db")
    NADatabase(path).migrate()
    late = NADatabase(path)
    version, migration = migration_files("sqlite")[0]
    # As if this process read schema_version before the other one committed.
    late._apply_sqlite_migration(version, migration.read_text(encoding="utf-8"))
    assert late.schema_version() == expected_schema_version()
    assert not late.conn.in_transaction


def test_a_failing_migration_is_rolled_back_and_raised(tmp_path):
    path = str(tmp_path / "na.db")
    db = NADatabase(path)
    db.migrate()
    broken = expected_schema_version() + 1
    with pytest.raises(sqlite3.OperationalError):
        db._apply_sqlite_migration(broken, "CREATE TABLE gm_probe (id INTEGER);\nSELECT * FROM missing_table;")
    assert broken not in _versions(path)
    assert db.conn.execute("SELECT name FROM sqlite_master WHERE name = 'gm_probe'").fetchone() is None
