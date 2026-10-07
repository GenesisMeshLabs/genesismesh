"""Admin authentication cannot be used to flood the Network Authority (v1.1.0).

Every admin-authenticated route is rate limited, oversized X-Admin-* headers
are refused before they reach the audit log, a timestamp without a UTC offset
is an ordinary failure rather than a 500, and the public dashboard reads a
bounded set of audit events.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from genesis_mesh.crypto import sign_data
from genesis_mesh.na_service.auth import MAX_ADMIN_HEADER_LENGTH
from genesis_mesh.na_service.operator_console.dashboard import build_dashboard_model
from genesis_mesh.na_service.rate_limit import RateLimits

from .na_server_helpers import join_node, make_client, make_na_service

BOGUS_ADMIN_HEADERS = {
    "X-Admin-Key-Id": "nobody",
    "X-Admin-Signature": "x",
    "X-Admin-Timestamp": "2026-01-01T00:00:00+00:00",
    "X-Admin-Nonce": "n",
}

# The routes that verified admin headers without the admin limit in 1.0.2.
ROUTES_LIMITED_SINCE_1_1 = [
    ("GET", "/admin/policy/history"),
    ("POST", "/admin/policy/rollback"),
    ("GET", "/nodes"),
    ("GET", "/attestations"),
]


def _auth_failures(service) -> list[dict]:
    return [e for e in service.db.list_audit_events() if e["event_type"] == "admin_auth_failed"]


@pytest.mark.parametrize(("method", "path"), ROUTES_LIMITED_SINCE_1_1)
def test_admin_requests_are_rate_limited(method, path):
    service = make_na_service()
    # v1.1.0: an admin limit below the failed-authentication limit, so the
    # route's own admin limit is what refuses the request.
    service.rate_limits = RateLimits(admin=5)
    client = service.app.test_client()
    body = {} if method == "POST" else None
    limit = service.rate_limits.admin

    for _ in range(limit):
        resp = client.open(path, method=method, headers=BOGUS_ADMIN_HEADERS, json=body)
        assert resp.status_code == 401, (path, resp.status_code, resp.get_json())
    resp = client.open(path, method=method, headers=BOGUS_ADMIN_HEADERS, json=body)

    assert resp.status_code == 429
    # A refused request over the limit writes nothing to the audit log.
    assert len(_auth_failures(service)) == limit


def test_oversized_admin_headers_are_refused_before_the_audit_log():
    service = make_na_service()
    client = service.app.test_client()
    headers = {**BOGUS_ADMIN_HEADERS, "X-Admin-Key-Id": "k" * 8000}

    resp = client.get("/admin/policy/history", headers=headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "admin_auth_failed"
    (event,) = _auth_failures(service)
    assert event["details"]["reason"] == "oversized_headers"
    assert len(event["details"]["key_id"]) == MAX_ADMIN_HEADER_LENGTH


def test_admin_timestamp_without_offset_is_not_a_server_error():
    """It raised TypeError (a 500) against an aware "now"; it is read as UTC."""
    service = make_na_service()
    client = service.app.test_client()
    naive_now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    headers = {
        **BOGUS_ADMIN_HEADERS,
        "X-Admin-Key-Id": "operator-test",
        "X-Admin-Timestamp": naive_now,
    }

    resp = client.get("/admin/policy/history", headers=headers)

    # Fresh as UTC, so it reaches the signature check, which the bogus
    # signature fails.
    assert resp.status_code == 401
    assert resp.get_json()["error"]["message"] == "Invalid admin signature"


def test_node_timestamp_without_offset_is_read_as_utc():
    service = make_na_service()
    client = make_client(service)
    resp, join_data, keypair = join_node(client)
    assert resp.status_code in (200, 201), join_data
    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": keypair.public_key_b64,
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "nonce": str(uuid.uuid4()),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = sign_data(canonical.encode("utf-8"), keypair.private_key)

    resp = client.post("/heartbeat", json=payload)

    assert resp.status_code == 200, resp.get_json()


def test_audit_events_can_be_filtered_and_bounded():
    service = make_na_service()
    db = service.db
    for i in range(5):
        db.add_audit_event("admin_auth_failed", {"key_id": f"k{i}"})
        db.add_audit_event("treaty_attestation_verified", {"n": i})
    db.add_audit_event("sovereign_revocation_feed_imported", {"n": 0})

    only = db.list_audit_events(event_types=("treaty_attestation_verified",))
    assert [e["details"]["n"] for e in only] == [0, 1, 2, 3, 4]
    without = db.list_audit_events(exclude_event_types=("admin_auth_failed",))
    assert {e["event_type"] for e in without} == {
        "treaty_attestation_verified",
        "sovereign_revocation_feed_imported",
    }
    newest = db.list_audit_events(event_types=("treaty_attestation_verified",), limit=2)
    # The newest two, still oldest first.
    assert [e["details"]["n"] for e in newest] == [3, 4]
    # A type that only shares a prefix does not match.
    assert db.list_audit_events(event_types=("treaty_attestation",)) == []


def test_failed_admin_attempts_do_not_reach_the_public_dashboard():
    service = make_na_service()
    for i in range(50):
        service.db.add_audit_event("admin_auth_failed", {"key_id": "x" * 200, "reason": "unknown_key"})
    service.db.add_audit_event("recognition_treaty_created", {"treaty_id": "t-1"})

    model = build_dashboard_model(service)

    rendered = json.dumps(model)
    assert "admin_auth_failed" not in rendered
    assert "x" * 200 not in rendered
