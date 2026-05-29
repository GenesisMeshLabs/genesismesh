"""Tests for Network Authority admin routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .na_server_helpers import admin_headers, create_invite, publish_policy


def test_invite_token_is_single_use(client, node_keypair):
    """A persisted invite token can issue only one certificate."""
    invite_resp = create_invite(client, roles=["role:client"])
    assert invite_resp.status_code == 201
    token_id = invite_resp.get_json()["token_id"]

    first = client.post("/join", json={
        "node_public_key": node_keypair.public_key_b64,
        "invite_token": token_id,
    })
    assert first.status_code == 201

    from genesis_mesh.crypto import generate_keypair

    second_keypair = generate_keypair()
    second = client.post("/join", json={
        "node_public_key": second_keypair.public_key_b64,
        "invite_token": token_id,
    })
    assert second.status_code == 403


def test_invite_token_concurrent_use_is_atomic(na_service):
    """Concurrent token use can succeed for only one caller."""
    token = na_service.db.create_invite_token(["role:client"], 168, 24)

    def use_token(node_suffix: int):
        return na_service.db.use_invite_token(token.token_id, f"node-{node_suffix}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(use_token, range(6)))

    assert sum(result is not None for result in results) == 1


def test_admin_invite_requires_operator_signature(client):
    """Invite creation rejects missing operator authentication."""
    resp = client.post("/admin/invite", json={
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    })
    assert resp.status_code == 401


def test_admin_invite_rejects_malformed_signature(na_service, client):
    """Invite creation rejects malformed operator signatures cleanly."""
    body = {
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    }
    headers = admin_headers(client, body)
    headers["X-Admin-Signature"] = "not-base64"

    resp = client.post("/admin/invite", json=body, headers=headers)

    assert resp.status_code == 401
    assert "Traceback" not in resp.get_data(as_text=True)
    events = na_service.db.list_audit_events()
    assert events[-1]["event_type"] == "admin_auth_failed"
    assert events[-1]["details"]["reason"] == "invalid_signature"
    assert "body" not in events[-1]["details"]


def test_admin_invite_rate_limit_returns_429(client):
    """Admin endpoints return 429 after the configured request burst."""
    body = {
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    }

    last_resp = None
    for _ in range(31):
        last_resp = client.post("/admin/invite", json=body)

    assert last_resp is not None
    assert last_resp.status_code == 429
    assert last_resp.get_json()["error"] == "Rate limit exceeded"


def test_replayed_admin_nonce_is_audited_without_request_body(na_service, client):
    """Admin nonce replay creates a scoped audit event without body leakage."""
    body = {
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    }
    headers = admin_headers(client, body)

    first = client.post("/admin/invite", json=body, headers=headers)
    second = client.post("/admin/invite", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 401
    events = na_service.db.list_audit_events()
    replay = events[-1]
    assert replay["event_type"] == "admin_auth_failed"
    assert replay["details"]["reason"] == "nonce_replay"
    assert replay["details"]["scope"] == "admin:operator-test"
    assert "body" not in replay["details"]


def test_invite_token_secret_is_not_persisted_in_audit_details(na_service, client, node_keypair):
    """Invite token audit records use fingerprints rather than token secrets."""
    invite_resp = create_invite(client, roles=["role:client"])
    assert invite_resp.status_code == 201
    token_id = invite_resp.get_json()["token_id"]

    join_resp = client.post("/join", json={
        "node_public_key": node_keypair.public_key_b64,
        "invite_token": token_id,
    })
    assert join_resp.status_code == 201

    events = na_service.db.list_audit_events()
    serialized = str(events)
    assert token_id not in serialized
    assert any(
        event["event_type"] == "invite_created"
        and "token_fingerprint" in event["details"]
        for event in events
    )
    assert any(
        event["event_type"] == "certificate_issued"
        and "invite_token_fingerprint" in event["details"]
        for event in events
    )


def test_policy_publish_updates_active_policy(client):
    """Publishing a policy makes it the active DB-backed policy."""
    publish_resp = publish_policy(client, "policy-test-2", "0.2.0")
    assert publish_resp.status_code == 201

    active_resp = client.get("/policy")
    assert active_resp.status_code == 200
    active = active_resp.get_json()
    assert active["policy_id"] == "policy-test-2"
    assert active["min_client_version"] == "0.2.0"
    assert active["signatures"]


def test_policy_history_requires_operator_signature(client):
    """Policy history rejects missing operator authentication."""
    resp = client.get("/admin/policy/history")
    assert resp.status_code == 401


def test_policy_rollback_restores_previous_version(client):
    """Policy rollback activates a previously published policy."""
    first = publish_policy(client, "policy-test-1", "0.1.0")
    second = publish_policy(client, "policy-test-2", "0.2.0")
    assert first.status_code == 201
    assert second.status_code == 201

    history_resp = client.get(
        "/admin/policy/history",
        headers=admin_headers(client, {}),
    )
    assert history_resp.status_code == 200
    assert len(history_resp.get_json()["versions"]) == 2

    body = {"policy_id": "policy-test-1"}
    rollback_resp = client.post(
        "/admin/policy/rollback",
        json=body,
        headers=admin_headers(client, body),
    )
    assert rollback_resp.status_code == 200

    active = client.get("/policy").get_json()
    assert active["policy_id"] == "policy-test-1"
    assert active["min_client_version"] == "0.1.0"
