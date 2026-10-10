"""Audit and backup persistence helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence


class AuditStoreMixin:
    """Persistence methods for audit events and live SQLite backups."""

    conn: Any

    def backup(self, dest_path: str) -> None:
        """Copy the live SQLite database to a destination path.

        PostgreSQL deployments rely on the managed service's backups and
        point-in-time restore (docs/operations/high-availability.md).
        """
        if getattr(self, "backend", "sqlite") != "sqlite":
            raise NotImplementedError("backup() is SQLite-only; use the PostgreSQL service's backups")
        dest = sqlite3.connect(dest_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
    def add_audit_event(self, event_type: str, details: dict, *, event_id: str | None = None) -> str:
        """Persist a lightweight Network Authority audit event.

        ``event_id`` (v1.3.1) lets a caller name the event before it is
        written, so a record made in an earlier transaction can refer to it.
        """
        event_id = event_id or str(uuid.uuid4())
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
    def list_audit_events(
        self,
        *,
        event_types: Sequence[str] = (),
        exclude_event_types: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[dict]:
        """Return persisted Network Authority audit events in insertion order.

        ``event_types`` keeps only those types and ``exclude_event_types``
        leaves those out, both in SQL; ``limit`` keeps the newest ``limit``
        events. The public dashboard uses them so that its cost does not grow
        with the whole table (v1.1.0). v1.3.1: an event is kept only when its
        own ``event_type`` is one of ``event_types``; the SQL match is a
        prefilter (a ``details`` value can look like an event type).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if event_types:
            matches = [_event_type_match(t) for t in event_types]
            clauses.append("(" + " OR ".join(sql for sql, _ in matches) + ")")
            params.extend(value for _, values in matches for value in values)
        for event_type in exclude_event_types:
            sql, values = _event_type_match(event_type)
            clauses.append(f"NOT {sql}")
            params.extend(values)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        if limit is None:
            rows = self.conn.execute(
                f"SELECT event_json FROM audit_events{where} ORDER BY created_at ASC", params
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT event_json FROM audit_events{where} ORDER BY created_at DESC LIMIT ?",
                [*params, int(limit)],
            ).fetchall()[::-1]
        events = [json.loads(row["event_json"]) for row in rows]
        if event_types:
            wanted = set(event_types)
            events = [e for e in events if isinstance(e, dict) and e.get("event_type") in wanted]
        return events


def _event_type_match(event_type: str) -> tuple[str, list[str]]:
    """SQL matching one event type in ``event_json`` (written with sort_keys).

    Both separator spellings are accepted, so a row copied by another tool
    still matches; the closing quote ends the type. ``%`` and ``_`` in the
    type are matched literally (v1.3.1; ``_`` matched any character before).
    """
    literal = event_type.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return (
        "(event_json LIKE ? ESCAPE '!' OR event_json LIKE ? ESCAPE '!')",
        [f'%"event_type": "{literal}"%', f'%"event_type":"{literal}"%'],
    )
