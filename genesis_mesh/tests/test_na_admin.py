"""Tests for Network Authority admin routes."""

from __future__ import annotations

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


def test_admin_invite_requires_operator_signature(client):
    """Invite creation rejects missing operator authentication."""
    resp = client.post("/admin/invite", json={
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    })
    assert resp.status_code == 401


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
