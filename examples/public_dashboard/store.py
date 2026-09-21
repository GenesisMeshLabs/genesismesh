"""Atomic SQLite snapshot storage; web readers open the database read-only."""

from pathlib import Path
import sqlite3

from .records import Snapshot, validate_snapshot


def read_snapshot(path: Path, root_key: str) -> Snapshot:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT payload FROM public_snapshot WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("snapshot_missing")
    snapshot = Snapshot.model_validate_json(row[0])
    validate_snapshot(snapshot, root_key)
    return snapshot


def write_snapshot(path: Path, snapshot: Snapshot) -> None:
    validate_snapshot(snapshot, snapshot.genesis.root_public_key)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS public_snapshot (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO public_snapshot VALUES (1, ?)", (snapshot.model_dump_json(),))
