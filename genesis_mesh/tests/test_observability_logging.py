"""Shared logging configuration and redaction tests."""

from __future__ import annotations

import io
import json
import logging

from genesis_mesh.observability.logging import (
    configure_logging,
    redact_log_text,
    redacted_exception_text,
)


def test_redact_log_text_removes_common_secret_shapes():
    text = redact_log_text(
        "invite_token=abc token=def password=hunter2 "
        "Authorization: Bearer jwt-value C:/secrets/operator.key "
        "/etc/genesis-mesh/keys/na.key"
    )

    assert "abc" not in text
    assert "def" not in text
    assert "hunter2" not in text
    assert "jwt-value" not in text
    assert "operator.key" not in text
    assert "na.key" not in text
    assert "[REDACTED]" in text


def test_redacted_exception_text_removes_secrets_from_tracebacks():
    try:
        raise RuntimeError("token=abc at C:/secrets/operator.key")
    except RuntimeError as exc:
        text = redacted_exception_text(exc)

    assert "RuntimeError" in text
    assert "token=abc" not in text
    assert "operator.key" not in text


def test_configure_logging_redacts_existing_handler_output():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    try:
        root.handlers = [handler]
        configure_logging(level="INFO")

        logging.getLogger("genesis_mesh.tests.redaction").info(
            "token=abc C:/secrets/operator.key"
        )

        output = stream.getvalue()
        assert "token=abc" not in output
        assert "operator.key" not in output
        assert "[REDACTED]" in output
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_json_logging_promotes_extra_fields_and_strips_ansi():
    """JSON logs should be parseable SIEM records with first-class fields."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    server_logger = logging.getLogger("genesis_mesh.na_service.server")
    original_server_handlers = server_logger.handlers[:]
    original_server_propagate = server_logger.propagate
    original_server_level = server_logger.level
    try:
        root.handlers = [handler]
        server_logger.handlers = []
        configure_logging(level="INFO", log_format="json")

        server_logger.info(
            "\x1b[31mAPI request\x1b[0m",
            extra={
                "request_id": "req-json",
                "method": "GET",
                "path": "/healthz",
                "status": 200,
                "duration_ms": 1.25,
                "remote_addr": "127.0.0.1",
            },
        )

        payload = json.loads(stream.getvalue())
        assert payload["message"] == "API request"
        assert payload["request_id"] == "req-json"
        assert payload["method"] == "GET"
        assert payload["path"] == "/healthz"
        assert payload["status"] == 200
        assert payload["duration_ms"] == 1.25
        assert payload["remote_addr"] == "127.0.0.1"
        assert "\x1b" not in stream.getvalue()
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        server_logger.handlers = original_server_handlers
        server_logger.propagate = original_server_propagate
        server_logger.setLevel(original_server_level)
