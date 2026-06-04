"""Audit and backup persistence helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
import uuid


class AuditStoreMixin:
    """Persistence methods for audit events and live SQLite backups."""

    conn: sqlite3.Connection

    def backup(self, dest_path: str) -> None:
        """Copy the live SQLite database to a destination path."""
        dest = sqlite3.connect(dest_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
    def add_audit_event(self, event_type: str, details: dict) -> str:
        """Persist a lightweight Network Authority audit event."""
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "details": details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO audit_events(event_id, event_json, created_at)
                VALUES (?, ?, ?)
                """,
                (event_id, json.dumps(payload, sort_keys=True), payload["created_at"]),
            )
        return event_id
    def list_audit_events(self) -> list[dict]:
        """Return persisted Network Authority audit events in insertion order."""
        rows = self.conn.execute(
            "SELECT event_json FROM audit_events ORDER BY created_at ASC"
        ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]
