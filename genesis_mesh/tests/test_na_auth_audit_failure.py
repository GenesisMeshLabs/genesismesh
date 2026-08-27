"""Regression tests for F-16 — auth-failure audit events must not vanish silently.

Before the fix, ``_audit_auth_failure`` wrapped audit persistence in a bare
``except Exception: pass`` (``na_service/auth.py``): authentication still failed
closed, but a failing audit store (disk full, DB locked) silently lost the
security event with no log line and no counter. These tests pin the fixed
behavior: the event loss is logged at ERROR and counted, and the counter is
exposed on ``/metrics`` — while auth behavior itself stays byte-for-byte the
same.
"""

import logging

import pytest

from genesis_mesh.na_service.auth import verify_node_request_signature


def _break_audit_store(service):
    def failing_add_audit_event(event_type, details):
        raise RuntimeError("disk full")

    service.db.add_audit_event = failing_add_audit_event


def test_audit_store_failure_is_logged_and_counted(na_service, node_keypair, caplog):
    """A failing audit store must not silently swallow the auth-failure event."""
    _break_audit_store(na_service)

    with na_service.app.test_request_context("/"):
        with caplog.at_level(logging.ERROR, logger="genesis_mesh.na_service.auth"):
            ok, err = verify_node_request_signature(
                na_service, {}, node_keypair.public_key_b64
            )

    # Auth still fails closed — the fix must not change auth semantics.
    assert ok is False
    assert "Missing authentication fields" in err

    # The lost event is now observable: one ERROR log line naming the event.
    records = [r for r in caplog.records if "node_auth_failed" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "missing_fields" in records[0].getMessage()
    assert "disk full" in records[0].getMessage()

    # ...and counted in-process.
    assert na_service.audit_write_failures == 1


def test_audit_store_failure_never_leaks_into_auth_flow(na_service, node_keypair):
    """The audit exception must be contained; callers see the normal failure tuple."""
    _break_audit_store(na_service)

    with na_service.app.test_request_context("/"):
        ok, err = verify_node_request_signature(
            na_service, {}, node_keypair.public_key_b64
        )

    assert (ok, err) == (
        False,
        "Missing authentication fields: signature, timestamp, and nonce required",
    )


def test_audit_write_failures_exposed_on_metrics(na_service, node_keypair):
    """/metrics must report the dropped-audit-event counter."""
    client = na_service.app.test_client()

    body = client.get("/metrics").get_data(as_text=True)
    assert "genesis_mesh_na_audit_write_failures_total 0" in body

    _break_audit_store(na_service)
    with na_service.app.test_request_context("/"):
        verify_node_request_signature(na_service, {}, node_keypair.public_key_b64)

    body = client.get("/metrics").get_data(as_text=True)
    assert "genesis_mesh_na_audit_write_failures_total 1" in body


def test_healthy_audit_store_neither_logs_nor_counts(na_service, node_keypair, caplog):
    """With a working store the exception path stays untouched: no log, no count."""
    with na_service.app.test_request_context("/"):
        with caplog.at_level(logging.ERROR, logger="genesis_mesh.na_service.auth"):
            ok, _ = verify_node_request_signature(
                na_service, {}, node_keypair.public_key_b64
            )

    assert ok is False
    assert not caplog.records
    assert na_service.audit_write_failures == 0
