"""PostgreSQL backend (v0.60): a connection with the sqlite3 calling conventions.

The store mixins were written against ``sqlite3``: ``?`` placeholders,
``with conn:`` for a transaction, and rows readable by column name or index.
``PostgresConnection`` keeps those conventions so the mixins stay
backend-neutral:

* each thread gets its own psycopg connection in autocommit mode, so a read
  never leaves a transaction open between requests;
* ``with conn:`` opens a transaction (a savepoint when nested), commits on
  success and rolls back on error;
* ``?`` placeholders are rewritten to ``%s`` outside string literals.

psycopg is an optional dependency (``pip install genesis-mesh[postgres]``).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from .base import DatabaseConfigError, redact_database_url

try:  # pragma: no cover - exercised only where psycopg is installed
    import psycopg
    from psycopg import errors as pg_errors
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    pg_errors = None  # type: ignore[assignment]

#: Collations whose ordering is plain code-point order, as SQLite's BINARY.
BINARY_COLLATIONS = frozenset({"C", "POSIX", "C.UTF-8", "C.utf8", "ucs_basic"})

#: Advisory lock keys (any stable 64-bit integers unique to this application).
MIGRATION_LOCK_KEY = 0x47_4D_4E_41_4D_49_47  # "GMNAMIG"
EVIDENCE_LOCK_KEY = 0x47_4D_4E_41_45_56_44  # "GMNAEVD"


def require_psycopg() -> None:
    if psycopg is None:
        raise DatabaseConfigError(
            "PostgreSQL support needs the optional driver: pip install 'genesis-mesh[postgres]'"
        )


def translate_placeholders(sql: str) -> str:
    """Rewrite ``?`` to ``%s`` (and escape ``%``) outside single-quoted literals."""
    out: list[str] = []
    in_literal = False
    for ch in sql:
        if ch == "'":
            in_literal = not in_literal
            out.append(ch)
        elif in_literal:
            out.append("%%" if ch == "%" else ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class Row(Sequence[Any]):
    """A result row addressable by index or column name, like ``sqlite3.Row``."""

    __slots__ = ("_names", "_values")

    def __init__(self, names: tuple[str, ...], values: tuple[Any, ...]) -> None:
        self._names = names
        self._values = values

    def keys(self) -> list[str]:
        return list(self._names)

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, str):
            try:
                return self._values[self._names.index(key)]
            except ValueError:
                raise IndexError(f"no such column: {key}") from None
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values))!r})"


class Cursor:
    """The subset of the sqlite3 cursor API the stores use."""

    def __init__(self, rows: list[Row], rowcount: int) -> None:
        self._rows = rows
        self._pos = 0
        self.rowcount = rowcount

    def fetchone(self) -> Row | None:
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self) -> list[Row]:
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class PostgresConnection:
    """Thread-safe PostgreSQL connection facade with sqlite3 conventions."""

    backend = "postgres"

    def __init__(self, url: str, *, connect_timeout: int = 10) -> None:
        require_psycopg()
        self.url = url
        self.redacted_url = redact_database_url(url)
        self._connect_timeout = connect_timeout
        self._local = threading.local()
        self._all: list[Any] = []
        self._all_lock = threading.Lock()
        self._sql_cache: dict[str, str] = {}

    # -- connection management ---------------------------------------------

    def _raw(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed or conn.broken:
            conn = psycopg.connect(self.url, autocommit=True, connect_timeout=self._connect_timeout)
            self._local.conn = conn
            self._local.tx = []
            with self._all_lock:
                self._all.append(conn)
        return conn

    @property
    def in_transaction(self) -> bool:
        return bool(getattr(self._local, "tx", None))

    def close(self) -> None:
        """Close every connection this facade opened (all threads)."""
        with self._all_lock:
            conns, self._all = self._all, []
        for conn in conns:
            try:
                conn.close()
            except Exception:  # pragma: no cover - best effort on shutdown
                pass
        self._local = threading.local()

    # -- statements -----------------------------------------------------------

    def _sql(self, sql: str) -> str:
        cached = self._sql_cache.get(sql)
        if cached is None:
            cached = translate_placeholders(sql)
            self._sql_cache[sql] = cached
        return cached

    @staticmethod
    def _result(cur: Any) -> Cursor:
        if cur.description is None:
            return Cursor([], cur.rowcount)
        names = tuple(col.name for col in cur.description)
        rows = [Row(names, tuple(values)) for values in cur.fetchall()]
        return Cursor(rows, cur.rowcount)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> Cursor:
        conn = self._raw()
        with conn.cursor() as cur:
            cur.execute(self._sql(sql), tuple(params) if params is not None else None)
            return self._result(cur)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> Cursor:
        conn = self._raw()
        with conn.cursor() as cur:
            cur.executemany(self._sql(sql), [tuple(p) for p in seq_of_params])
            return Cursor([], cur.rowcount)

    def executescript(self, script: str) -> None:
        """Run a multi-statement script verbatim (no placeholders)."""
        conn = self._raw()
        with conn.cursor() as cur:
            cur.execute(script)

    # -- transactions -----------------------------------------------------------

    def commit(self) -> None:
        """sqlite3 compatibility: statements outside ``with conn:`` autocommit."""

    def rollback(self) -> None:
        """sqlite3 compatibility: nothing to roll back outside ``with conn:``."""

    def __enter__(self) -> "PostgresConnection":
        conn = self._raw()
        tx = conn.transaction()
        tx.__enter__()
        self._local.tx.append(tx)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        tx = self._local.tx.pop()
        tx.__exit__(exc_type, exc, tb)

    @contextmanager
    def exclusive(self, lock_key: int) -> Iterator[None]:
        """A transaction holding a transaction-scoped advisory lock (released at commit)."""
        with self:
            self.execute("SELECT pg_advisory_xact_lock(?)", (lock_key,))
            yield

    # -- introspection ------------------------------------------------------------

    def collation(self) -> str:
        row = self.execute(
            "SELECT datcollate FROM pg_database WHERE datname = current_database()"
        ).fetchone()
        return str(row[0]) if row else ""

    def is_writable_primary(self) -> bool:
        row = self.execute("SELECT pg_is_in_recovery()").fetchone()
        return row is not None and not bool(row[0])

    def table_names(self) -> list[str]:
        rows = self.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
        return [str(r[0]) for r in rows]


def integrity_error_types() -> tuple[type[BaseException], ...]:
    return (psycopg.IntegrityError,) if psycopg is not None else ()


def database_error_types() -> tuple[type[BaseException], ...]:
    return (psycopg.Error,) if psycopg is not None else ()


def operational_error_types() -> tuple[type[BaseException], ...]:
    return (psycopg.OperationalError,) if psycopg is not None else ()
