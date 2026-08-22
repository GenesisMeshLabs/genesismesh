"""Tests for Network Authority admin routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from genesis_mesh.crypto import generate_keypair

from .na_server_helpers import admin_headers, create_invite, publish_policy, sign_payload


def _error_message(resp) -> str:
    return resp.get_json()["error"]["message"]


def test_invite_token_is_single_use(client, node_keypair):
    """A persisted invite token can issue only one certificate."""
    invite_resp = create_invite(client, roles=["role:client"])
    assert invite_resp.status_code == 201
    token_id = invite_resp.get_json()["token_id"]

    first_payload = sign_payload(
        {
            "node_public_key": node_keypair.public_key_b64,
            "invite_token": token_id,
        },
        node_keypair.private_key,
    )
    first = client.post("/join", json=first_payload)
    assert first.status_code == 201

    second_keypair = generate_keypair()
    second = client.post("/join", json={
        "node_public_key": second_keypair.public_key_b64,
        "invite_token": token_id,
    })
    assert second.status_code == 403


def test_admin_invite_with_recipient_binding_is_audited(na_service, client, node_keypair):
    """Creating a recipient-bound invite persists and audits the binding (F-08)."""
    invite_resp = create_invite(
        client,
        roles=["role:client"],
        recipient_public_key=node_keypair.public_key_b64,
    )
    assert invite_resp.status_code == 201
    token_id = invite_resp.get_json()["token_id"]

    stored = na_service.db.get_available_invite_token(token_id)
    assert stored is not None
    assert stored.recipient_public_key == node_keypair.public_key_b64

    events = [
        event for event in na_service.db.list_audit_events()
        if event["event_type"] == "invite_created"
    ]
    assert events, "expected an invite_created audit event"
    assert events[-1]["details"]["recipient_public_key"] == node_keypair.public_key_b64


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
    assert _error_message(last_resp) == "Rate limit exceeded"


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

    join_resp = client.post(
        "/join",
        json=sign_payload(
            {
                "node_public_key": node_keypair.public_key_b64,
                "invite_token": token_id,
            },
            node_keypair.private_key,
        ),
    )
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


# ---------------------------------------------------------------------------
# F-21 (commit 1 of 2) — operator keys can be switched off at runtime.
#
# Revocation is keyed by key_id, so a second key id registered against the same
# key material is a faithful second operator for these tests.
#
# NOTE: this half does NOT add authorisation tiers. Any surviving operator key
# can still do everything, including revoking other operators. That is commit 2.
# ---------------------------------------------------------------------------


def _add_second_operator(na_service, key_id: str = "operator-two") -> str:
    """Register another operator key id so revocation has something to leave behind."""
    na_service.operator_public_keys[key_id] = na_service.operator_public_keys["operator-test"]
    return key_id


def _revoke(client, target: str, key_id: str = "operator-test", reason: str = "key_compromise"):
    body = {"reason": reason}
    return client.post(
        f"/admin/operator-keys/{target}/revoke",
        json=body,
        headers=admin_headers(client, body, key_id=key_id),
    )


def _invite_as(client, key_id: str):
    """Create an invite signed by a specific operator key id."""
    body = {
        "roles": ["role:client"],
        "max_validity_hours": 168,
        "token_expiry_hours": 24,
    }
    return client.post(
        "/admin/invite", json=body, headers=admin_headers(client, body, key_id=key_id)
    )


def test_revoked_operator_key_is_refused_immediately(client, na_service):
    """F-21: a stolen key is switched off live, with no restart."""
    victim = _add_second_operator(na_service)

    # It works before revocation.
    before = _invite_as(client, victim)
    assert before.status_code == 201, before.get_json()

    resp = _revoke(client, victim)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["revoked"] is True

    # Same service instance, no restart: the key is dead.
    after = _invite_as(client, victim)
    assert after.status_code == 401
    assert _error_message(after) == "Unknown admin key"


def test_revocation_response_does_not_reveal_that_the_key_existed(client, na_service):
    """F-21: a revoked key and an unrecognised key are indistinguishable."""
    victim = _add_second_operator(na_service)
    assert _revoke(client, victim).status_code == 200

    revoked = _invite_as(client, victim)
    unknown = _invite_as(client, "never-configured")

    assert revoked.status_code == unknown.status_code == 401
    assert _error_message(revoked) == _error_message(unknown) == "Unknown admin key"


def test_audit_records_the_real_reason(client, na_service):
    """The operator gets the truth from the audit trail, not the HTTP response."""
    victim = _add_second_operator(na_service)
    assert _revoke(client, victim).status_code == 200
    _invite_as(client, victim)

    events = na_service.db.list_audit_events()
    kinds = [e["event_type"] for e in events]
    assert "operator_key_revoked" in kinds

    failures = [e for e in events if e["event_type"] == "admin_auth_failed"]
    assert any("revoked_key" in str(e) for e in failures), failures


def test_revoked_key_cannot_revoke_other_operators(client, na_service):
    """A revoked key is refused before it can act at all."""
    victim = _add_second_operator(na_service)
    third = _add_second_operator(na_service, "operator-three")
    assert _revoke(client, victim).status_code == 200

    resp = _revoke(client, third, key_id=victim)
    assert resp.status_code == 401
    assert na_service.db.is_operator_key_revoked(third) is False


def test_revocation_is_terminal_and_idempotent(client, na_service):
    """Revoking twice is a no-op; there is no un-revoke path."""
    victim = _add_second_operator(na_service)
    assert _revoke(client, victim).status_code == 200

    again = _revoke(client, victim)
    assert again.status_code == 200
    assert again.get_json()["already_revoked"] is True
    assert na_service.db.is_operator_key_revoked(victim) is True


def test_revoking_the_last_operator_key_is_refused(client, na_service):
    """The incident-response tool must not cause the outage it exists to avoid."""
    assert list(na_service.operator_public_keys) == ["operator-test"]

    resp = _revoke(client, "operator-test")

    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "last_active_operator_key"
    assert na_service.db.is_operator_key_revoked("operator-test") is False
    # And it still works.
    assert create_invite(client, roles=["role:client"]).status_code == 201


def test_last_key_guard_counts_already_revoked_keys(client, na_service):
    """Two configured keys, one already revoked -> the survivor cannot be revoked."""
    victim = _add_second_operator(na_service)
    assert _revoke(client, victim).status_code == 200

    resp = _revoke(client, "operator-test")

    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "last_active_operator_key"


def test_revoking_an_unconfigured_key_is_404(client, na_service):
    resp = _revoke(client, "never-configured")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "unknown_operator_key"


def test_surviving_operator_keys_keep_working(client, na_service):
    """Negative control: revocation must not break the remaining operators."""
    victim = _add_second_operator(na_service)
    assert _revoke(client, victim).status_code == 200

    assert create_invite(client, roles=["role:client"]).status_code == 201
    assert publish_policy(client, "pol-f21", "0.1.0").status_code in (200, 201)
