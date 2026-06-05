"""Shared logging configuration and redaction helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(x-operator-signature[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(signature[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(invite[_-]?token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(password[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)(private[_ -]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;]+"),
    re.compile(r"(?i)/etc/genesis-mesh/keys/[^\s,;]+"),
    re.compile(r"(?i)[A-Z]:[\\/][^\s,;]*?(?:\.key|\.pem)"),
)


def redact_log_text(value: Any) -> str:
    """Return log text with operational secrets and key paths redacted."""
    text = str(value)
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(lambda match: _redact_match(match), text)
    return text


def redacted_exception_text(exc: BaseException) -> str:
    """Return a redacted traceback string for safe server-side logging."""
    return redact_log_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


class RedactionFilter(logging.Filter):
    """Redact sensitive values from log records before handlers format them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_log_text(record.getMessage())
        record.args = ()
        return True


class RedactingFormatter(logging.Formatter):
    """Text formatter that redacts the final rendered line."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


class JsonLogFormatter(logging.Formatter):
    """Small JSON formatter for machine-ingested service logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_log_text(self.formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True)


def configure_logging(
    *,
    debug: bool = False,
    level: str | int | None = None,
    log_format: str | None = None,
    force: bool = False,
) -> None:
    """Configure process-wide logging with consistent redaction.

    Environment:
        GENESIS_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, or CRITICAL.
        GENESIS_LOG_FORMAT: text or json.
    """
    resolved_level = _resolve_level(level, debug)
    resolved_format = (log_format or os.environ.get("GENESIS_LOG_FORMAT") or "text").lower()

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactionFilter())
    if resolved_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(RedactingFormatter(DEFAULT_LOG_FORMAT))

    root = logging.getLogger()
    if force:
        root.handlers.clear()
    if not root.handlers:
        root.addHandler(handler)
    else:
        for existing in root.handlers:
            existing.addFilter(RedactionFilter())
            existing.setFormatter(handler.formatter)
    root.setLevel(resolved_level)


def _resolve_level(level: str | int | None, debug: bool) -> int:
    if debug:
        return logging.DEBUG
    raw = level if level is not None else os.environ.get("GENESIS_LOG_LEVEL", "INFO")
    if isinstance(raw, int):
        return raw
    resolved = logging.getLevelName(raw.upper())
    if isinstance(resolved, int):
        return resolved
    return logging.INFO
