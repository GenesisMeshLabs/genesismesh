"""Persistence for the Network Authority service: SQLite (default) or PostgreSQL."""

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db_agents import AgentStoreMixin
from .db_audit import AuditStoreMixin
from .db_boundary_policy import BoundaryPolicyStoreMixin
from .db_data_usage import DataUsageStoreMixin
from .db_enrollment import EnrollmentStoreMixin
from .db_evidence import EvidenceStoreMixin
from .db_policy import PolicyStoreMixin
from .db_runtime import RuntimeStoreMixin
from .db_trust import TrustStoreMixin
from .storage import DatabaseConfigError, is_postgres_url
from .storage.base import sqlite_path_from_url
from .storage import postgres as pg


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
logger = logging.getLogger(__name__)

#: Suffix of a migration file that replaces the shared file on PostgreSQL.
POSTGRES_OVERRIDE_SUFFIX = ".postgres.sql"


def migration_files(backend: str) -> list[tuple[int, Path]]:
    """Return ``(version, path)`` per migration, using dialect overrides for ``backend``."""
    shared = sorted(
        p for p in MIGRATIONS_DIR.glob("*.sql") if not p.name.endswith(POSTGRES_OVERRIDE_SUFFIX)
    )
    out: list[tuple[int, Path]] = []
    for path in shared:
        version = int(path.stem.split("_", 1)[0])
        override = path.with_name(path.stem + POSTGRES_OVERRIDE_SUFFIX)
        out.append((version, override if backend == "postgres" and override.exists() else path))
    return out


class NewerSchemaError(RuntimeError):
    """The database was migrated by a newer release than this one."""


def expected_schema_version() -> int:
    """The highest migration version this release ships."""
    return max(version for version, _ in migration_files("sqlite"))


class NADatabase(
    EnrollmentStoreMixin,
    PolicyStoreMixin,
    BoundaryPolicyStoreMixin,
    AuditStoreMixin,
    TrustStoreMixin,
    AgentStoreMixin,
    DataUsageStoreMixin,
    EvidenceStoreMixin,
    RuntimeStoreMixin,
):
    """Repository facade for Network Authority state.

    ``database_url`` selects the backend: unset keeps the SQLite file at
    ``db_path`` exactly as before; ``sqlite:///path`` names a SQLite file
    explicitly; ``postgresql://`` connects to a shared PostgreSQL database so
    several NA instances can serve together.
    """

    conn: Any

    def __init__(self, db_path: str = ":memory:", database_url: Optional[str] = None):
        """Open the database and configure connection-level settings."""
        self._lock = threading.RLock()
        if is_postgres_url(database_url):
            assert database_url is not None
            self.backend = "postgres"
            self.conn = pg.PostgresConnection(database_url)
            self.db_path = self.conn.redacted_url
            self.integrity_errors: tuple[type[BaseException], ...] = pg.integrity_error_types()
            self.database_errors: tuple[type[BaseException], ...] = pg.database_error_types()
            collation = self.conn.collation()
            if collation not in pg.BINARY_COLLATIONS:
                raise DatabaseConfigError(
                    f"PostgreSQL database collation is {collation!r}; the NA needs code-point "
                    "ordering. Create the database with LC_COLLATE 'C' (see "
                    "docs/operations/high-availability.md)."
                )
            return

        if database_url:
            if not database_url.startswith("sqlite:"):
                raise DatabaseConfigError("DATABASE_URL must be postgresql://... or sqlite:///path")
            db_path = sqlite_path_from_url(database_url)
        self.backend = "sqlite"
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.integrity_errors = (sqlite3.IntegrityError,)
        self.database_errors = (sqlite3.Error,)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            logger.warning("Could not enable SQLite WAL mode: %s", exc)

    # -- migrations -------------------------------------------------------------

    def migrate(self) -> None:
        """Apply numbered SQL migrations transactionally, once across all instances.

        Refuses a database migrated by a newer release: running older code on a
        newer schema is not supported. Roll back by restoring the backup taken
        before the upgrade (docs/operations/upgrade.md).
        """
        if self.backend == "postgres":
            self._migrate_postgres()
            return
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        self._refuse_newer_schema()
        applied = {
            row["version"]
            for row in self.conn.execute("SELECT version FROM schema_version")
        }

        for version, path in migration_files("sqlite"):
            if version in applied:
                continue
            self._apply_sqlite_migration(version, path.read_text(encoding="utf-8"))

    def _apply_sqlite_migration(self, version: int, sql: str) -> None:
        """Apply one migration unless another process already has (v0.63.1).

        Gunicorn workers sharing one SQLite file migrate at the same time. Each
        migration runs in one write transaction that first claims its
        ``schema_version`` row; a process that loses the race fails on that
        claim before touching the schema, rolls back and moves on.
        """
        applied_at = datetime.now(timezone.utc).isoformat()
        script = (
            "BEGIN IMMEDIATE;\n"
            f"INSERT INTO schema_version(version, applied_at) VALUES ({int(version)}, '{applied_at}');\n"
            f"{sql}\nCOMMIT;"
        )
        try:
            self.conn.executescript(script)
        except sqlite3.Error:
            if self.conn.in_transaction:
                self.conn.rollback()
            row = self.conn.execute("SELECT 1 FROM schema_version WHERE version = ?", (version,)).fetchone()
            if row is None:
                raise
            logger.info("SQLite migration %03d was applied by another process", version)

    def _migrate_postgres(self) -> None:
        """Run pending migrations under a database-wide advisory lock.

        Instances starting together queue on the lock; the first applies the
        migrations and the others find them already recorded.
        """
        self.conn.execute("SELECT pg_advisory_lock(?)", (pg.MIGRATION_LOCK_KEY,))
        try:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            self._refuse_newer_schema()
            applied = {row["version"] for row in self.conn.execute("SELECT version FROM schema_version")}
            for version, path in migration_files("postgres"):
                if version in applied:
                    continue
                with self.conn:
                    self.conn.executescript(path.read_text(encoding="utf-8"))
                    self.conn.execute(
                        "INSERT INTO schema_version(version, applied_at) VALUES (?, ?) "
                        "ON CONFLICT (version) DO NOTHING",
                        (version, datetime.now(timezone.utc).isoformat()),
                    )
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(?)", (pg.MIGRATION_LOCK_KEY,))

    def _refuse_newer_schema(self) -> None:
        version = self.schema_version()
        if version > expected_schema_version():
            raise NewerSchemaError(
                f"database schema version {version} is newer than this release supports "
                f"({expected_schema_version()}); upgrade Genesis Mesh, or restore the "
                "backup taken before the upgrade"
            )

    def schema_version(self) -> int:
        """Return the highest applied migration version (0 when none)."""
        row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"] or 0) if row else 0

    # -- backend-neutral helpers ----------------------------------------------------

    @contextmanager
    def exclusive_transaction(self) -> Iterator[None]:
        """A write transaction that excludes every other writer of the same kind.

        SQLite: ``BEGIN IMMEDIATE`` (one writer per file). PostgreSQL: a
        transaction holding an advisory lock, so instances serialize too.
        """
        with self._lock:
            if self.backend == "postgres":
                with self.conn.exclusive(pg.EVIDENCE_LOCK_KEY):
                    yield
                return
            if self.conn.in_transaction:
                self.conn.commit()
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()

    def check_writable(self) -> None:
        """Raise unless the database accepts writes (readiness probe)."""
        if self.backend == "postgres":
            if not self.conn.is_writable_primary():
                raise DatabaseConfigError("database is a read-only replica")
            with self.conn:
                self.conn.execute("SELECT 1").fetchone()
            return
        # A SELECT succeeds on a file this process cannot write (another
        # owner's volume, a read-only mount), so take the write lock and write
        # inside a transaction that is always rolled back (v1.0.2).
        with self._lock:
            if self.conn.in_transaction:
                self.conn.commit()
            self.conn.execute("PRAGMA busy_timeout = 1000")
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute("CREATE TABLE IF NOT EXISTS readiness_write_probe (x INTEGER)")
                    self.conn.execute("INSERT INTO readiness_write_probe (x) VALUES (1)")
                finally:
                    self.conn.rollback()
            except sqlite3.OperationalError as exc:
                # Another writer holds the lock: the database accepts writes.
                if "locked" not in str(exc).lower():
                    raise
            finally:
                self.conn.execute("PRAGMA busy_timeout = 30000")

    def table_names(self) -> list[str]:
        """Return application table names (excluding SQLite internals)."""
        if self.backend == "postgres":
            return self.conn.table_names()
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def close(self) -> None:
        """Close the underlying connection(s)."""
        self.conn.close()
