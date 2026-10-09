"""Backend-neutral storage helpers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

POSTGRES_SCHEMES = ("postgresql", "postgres")


class DatabaseConfigError(ValueError):
    """The configured database cannot be used by the Network Authority."""


def is_postgres_url(url: str | None) -> bool:
    """True when ``url`` selects the PostgreSQL backend."""
    if not url:
        return False
    scheme = urlsplit(url).scheme.split("+", 1)[0]
    return scheme in POSTGRES_SCHEMES


def sqlite_path_from_url(url: str) -> str:
    """Return the file path of a ``sqlite:///path`` URL (``sqlite:///:memory:`` allowed)."""
    parts = urlsplit(url)
    if parts.scheme != "sqlite":
        raise DatabaseConfigError(f"not a SQLite URL: {redact_database_url(url)}")
    path = parts.path
    if path.startswith("/") and path[1:] == ":memory:":
        return ":memory:"
    # sqlite:///C:/data/na.db names a Windows drive path, not /C:/data/na.db.
    if re.match(r"^/[A-Za-z]:[/\\]", path):
        return path[1:]
    return path


def redact_database_url(url: str) -> str:
    """Return ``url`` with any password removed, safe for logs and readiness output."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.rsplit("@", 1)
    host = netloc[-1]
    user = parts.username or ""
    return urlunsplit((parts.scheme, f"{user}:***@{host}", parts.path, parts.query, parts.fragment))
