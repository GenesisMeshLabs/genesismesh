"""Run the NA test suite against PostgreSQL (v0.60).

Set ``GENESIS_MESH_TEST_DATABASE_URL`` to a PostgreSQL database created with
``LC_COLLATE 'C'``. Every ``NADatabase`` a test opens then lives in a schema
of its own: the same ``db_path`` within one test maps to the same schema (so
restart tests share state), ``:memory:`` always gets a fresh one, and every
schema is dropped when the test ends. Tests marked ``sqlite_only`` are
skipped; tests marked ``postgres`` run only in this mode.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from urllib.parse import quote

import pytest

from genesis_mesh.na_service import db as na_db

TEST_DATABASE_URL = os.environ.get("GENESIS_MESH_TEST_DATABASE_URL", "")


def _with_search_path(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote(f'-csearch_path={schema}')}"


@pytest.fixture(autouse=True)
def postgres_test_database(request, monkeypatch):
    """Route NADatabase to per-test PostgreSQL schemas when configured."""
    if not TEST_DATABASE_URL:
        if request.node.get_closest_marker("postgres"):
            pytest.skip("needs GENESIS_MESH_TEST_DATABASE_URL")
        yield
        return
    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("SQLite-specific test")

    import psycopg

    admin = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schemas: dict[str, str] = {}
    opened: list[na_db.NADatabase] = []
    original_init = na_db.NADatabase.__init__
    node_id = request.node.nodeid

    def schema_for(db_path: str) -> str:
        if db_path == ":memory:" or db_path not in schemas:
            digest = hashlib.sha256(f"{node_id}|{db_path}|{uuid.uuid4()}".encode()).hexdigest()[:20]
            name = f"t_{digest}"
            admin.execute(f'CREATE SCHEMA "{name}"')
            if db_path == ":memory:":
                schemas.setdefault(":memory:#" + name, name)
                return name
            schemas[db_path] = name
        return schemas[db_path]

    def init(self, db_path=":memory:", database_url=None):
        if database_url is None:
            database_url = _with_search_path(TEST_DATABASE_URL, schema_for(str(db_path)))
        original_init(self, db_path, database_url=database_url)
        opened.append(self)

    monkeypatch.setattr(na_db.NADatabase, "__init__", init)
    try:
        yield
    finally:
        for database in opened:
            try:
                database.close()
            except Exception:
                pass
        for name in set(schemas.values()):
            admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        admin.close()


def fresh_postgres_url(request) -> str:
    """A URL for a new, empty schema in the test database, dropped after the test."""
    import psycopg

    name = f"t_{uuid.uuid4().hex[:20]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{name}"')

    def drop() -> None:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')

    request.addfinalizer(drop)
    return _with_search_path(TEST_DATABASE_URL, name)
