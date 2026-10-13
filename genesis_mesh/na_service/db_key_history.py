"""Persistence of the NA key history and of archive records (v1.5.0, migration 017).

Both tables are append-only (database triggers refuse updates and deletes).
A row written together with its store entry is inserted inside the caller's
evidence write transaction (``append_evidence_entries_with``), so the row and
the entry land together or not at all.
"""

from __future__ import annotations

import threading
from typing import Any

_KEY_COLUMNS = (
    "key_sequence", "key_id", "public_key", "effective_at", "valid_to", "valid_to_enforced",
    "succession_digest", "succession_json", "recorded_at",
)
_ARCHIVE_COLUMNS = (
    "archive_id", "pack_id", "from_sequence", "through_sequence", "through_entry_digest",
    "end_anchor_sequence", "manifest_sha256", "location", "archived_at", "recorded_by", "record_json",
)


class KeyHistoryStoreMixin:
    """Persistence methods for the NA key history and archive records."""

    conn: Any
    _lock: threading.RLock

    # -- NA key history ----------------------------------------------------------

    def na_key_history_rows(self) -> list[dict[str, Any]]:
        """Every key of the history, in order."""
        rows = self.conn.execute("SELECT * FROM na_key_history ORDER BY key_sequence").fetchall()
        return [{c: r[c] for c in _KEY_COLUMNS} for r in rows]

    def na_key_history_length(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM na_key_history").fetchone()
        return int(row["n"]) if row else 0

    def insert_na_key_row(self, row: dict[str, Any]) -> None:
        """Insert one key inside the caller's transaction (raises the backend's integrity error on a taken
        position or a reused public key)."""
        cols = ", ".join(_KEY_COLUMNS)
        marks = ", ".join("?" for _ in _KEY_COLUMNS)
        self.conn.execute(f"INSERT INTO na_key_history({cols}) VALUES ({marks})",
                          tuple(row.get(c) for c in _KEY_COLUMNS))

    def add_na_key_row(self, row: dict[str, Any]) -> None:
        """Insert one key in a transaction of its own."""
        with self._lock, self.conn:
            self.insert_na_key_row(row)

    # -- archive records ---------------------------------------------------------

    def insert_archive_row(self, row: dict[str, Any]) -> None:
        """Insert one archive record inside the caller's transaction."""
        cols = ", ".join(_ARCHIVE_COLUMNS)
        marks = ", ".join("?" for _ in _ARCHIVE_COLUMNS)
        self.conn.execute(f"INSERT INTO archive_records({cols}) VALUES ({marks})",
                          tuple(row.get(c) for c in _ARCHIVE_COLUMNS))

    def add_archive_row(self, row: dict[str, Any]) -> None:
        with self._lock, self.conn:
            self.insert_archive_row(row)

    def list_archive_rows(self) -> list[dict[str, Any]]:
        """Every archive record, by the range it covers."""
        rows = self.conn.execute(
            "SELECT * FROM archive_records ORDER BY from_sequence, through_sequence, archive_id"
        ).fetchall()
        return [{c: r[c] for c in _ARCHIVE_COLUMNS} for r in rows]
