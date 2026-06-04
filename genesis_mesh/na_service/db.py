"""SQLite persistence for the Network Authority service."""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .db_agents import AgentStoreMixin
from .db_audit import AuditStoreMixin
from .db_enrollment import EnrollmentStoreMixin
from .db_policy import PolicyStoreMixin
from .db_trust import TrustStoreMixin


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
logger = logging.getLogger(__name__)


class NADatabase(
    EnrollmentStoreMixin,
    PolicyStoreMixin,
    AuditStoreMixin,
    TrustStoreMixin,
    AgentStoreMixin,
):
    """SQLite repository facade for Network Authority state."""

    def __init__(self, db_path: str):
        """Open the SQLite database and configure connection-level pragmas."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            logger.warning("Could not enable SQLite WAL mode: %s", exc)

    def migrate(self) -> None:
        """Apply numbered SQL migrations transactionally."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]
            for row in self.conn.execute("SELECT version FROM schema_version")
        }

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.stem.split("_", 1)[0])
            if version in applied:
                continue

            sql = path.read_text(encoding="utf-8")
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
