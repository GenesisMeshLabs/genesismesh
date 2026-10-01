"""Storage backends for the Network Authority (v0.60).

SQLite is the default and behaves exactly as before. PostgreSQL is selected by
a ``postgresql://`` database URL and lets several NA instances share one
database. Both are reached through the same connection API (``execute`` with
``?`` placeholders, ``with conn:`` transactions, rows addressable by name or
position), so the store mixins carry no backend-specific code paths except
where a dialect genuinely differs.
"""

from .base import (
    DatabaseConfigError,
    is_postgres_url,
    redact_database_url,
)

__all__ = ["DatabaseConfigError", "is_postgres_url", "redact_database_url"]
