"""Tests for Network Authority enrollment, heartbeat, and renewal routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from genesis_mesh.crypto import generate_keypair, sign_data
from .na_server_helpers import (
    join_node,
    revoke_cert,
    signed_heartbeat,
    signed_renew,
    sign_payload,
)


def test_join_valid_roles(client, node_keypair):
    """Join with valid roles succeeds."""
    resp, data, _ = join_node(client, keypair=node_keypair, roles=["role:client"])
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


def test_join_invalid_role_rejected(client, node_keypair):
    """Join with an invalid role prefix is rejected."""
    resp, data, _ = join_node(client, keypair=node_keypair, roles=["role:admin"])
    assert resp.status_code == 400
    assert "Invalid role" in data["error"]


def test_join_default_roles(client, node_keypair):
    """Join without specifying roles defaults to role:client."""
    resp, data, _ = join_node(client, keypair=node_keypair)
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


def test_join_requires_invite_token(client, node_keypair):
    """Join without an invite token is rejected."""
    resp = client.post("/join", json={
        "node_public_key": node_keypair.public_key_b64,
    })
    assert resp.status_code == 403
    assert "invite_token" in resp.get_json()["error"]


def test_key_compromise_blocks_rejoin_with_same_public_key(client, node_keypair):
    """A key-compromise revocation blocks re-enrollment with that public key."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    assert revoke_cert(client, join_data["cert_id"], reason="key_compromise").status_code == 200

    second = join_node(client, keypair=kp, roles=["role:client"])
    assert second[0].status_code == 403


def test_non_compromise_revocation_allows_rejoin_with_same_public_key(client, node_keypair):
    """A non-compromise revocation does not block re-enrollment by key."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    assert revoke_cert(
        client,
        join_data["cert_id"],
        reason="cessation_of_operation",
    ).status_code == 200

    second = join_node(client, keypair=kp, roles=["role:client"])
    assert second[0].status_code == 201


def test_valid_renewal_preserves_roles(client, node_keypair):
    """A valid signed renewal preserves the original roles."""
    join_resp, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:anchor"])
    assert join_resp.status_code == 201

    renew_resp = signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    renew_data = renew_resp.get_json()
    assert renew_data["roles"] == ["role:anchor"]
    assert renew_data["cert_id"] != join_data["cert_id"]


def test_valid_renewal_with_same_roles_explicit(client, node_keypair):
    """Renewal that explicitly passes the same roles succeeds."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = signed_renew(client, join_data["cert_id"], kp, roles=["role:client"])
    assert renew_resp.status_code == 201


def test_renew_role_escalation_rejected(client, node_keypair):
    """Attempting to add higher-privilege roles during renewal is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = signed_renew(
        client,
        join_data["cert_id"],
        kp,
        roles=["role:anchor", "role:operator"],
    )
    assert renew_resp.status_code == 403
    assert "not permitted" in renew_resp.get_json()["error"]


def test_renew_role_downgrade_also_rejected(client, node_keypair):
    """Even role downgrade attempts are rejected."""
    _, join_data, kp = join_node(
        client,
        keypair=node_keypair,
        roles=["role:anchor", "role:bridge"],
    )
    renew_resp = signed_renew(client, join_data["cert_id"], kp, roles=["role:client"])
    assert renew_resp.status_code == 403


def test_renew_add_extra_role_rejected(client, node_keypair):
    """Adding an extra role to the existing set during renewal is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = signed_renew(
        client,
        join_data["cert_id"],
        kp,
        roles=["role:client", "role:operator"],
    )
    assert renew_resp.status_code == 403


def test_renew_wrong_key_rejected(client, node_keypair):
    """Renewal with a different node_public_key is rejected before auth."""
    _, join_data, _ = join_node(client, keypair=node_keypair, roles=["role:client"])
    other_kp = generate_keypair()
    renew_resp = signed_renew(client, join_data["cert_id"], other_kp)
    assert renew_resp.status_code == 403
    assert "does not match" in renew_resp.get_json()["error"]


def test_renew_unknown_cert_rejected(client, node_keypair):
    """Renewal of an unknown cert_id is rejected."""
    payload = sign_payload({
        "cert_id": "nonexistent-cert-id",
        "node_public_key": node_keypair.public_key_b64,
    }, node_keypair.private_key)
    renew_resp = client.post("/renew", json=payload)
    assert renew_resp.status_code == 403
    assert "Unknown certificate" in renew_resp.get_json()["error"]


def test_renew_missing_cert_id(client, node_keypair):
    """Renewal without cert_id returns 400."""
    resp = client.post("/renew", json={"node_public_key": node_keypair.public_key_b64})
    assert resp.status_code == 400


def test_renew_missing_public_key(client):
    """Renewal without node_public_key returns 400."""
    resp = client.post("/renew", json={"cert_id": "some-cert"})
    assert resp.status_code == 400


def test_chained_renewal(client, node_keypair):
    """A renewed certificate can itself be renewed."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:bridge"])

    renew1 = signed_renew(client, join_data["cert_id"], kp)
    assert renew1.status_code == 201
    new_cert_id = renew1.get_json()["cert_id"]

    renew2 = signed_renew(client, new_cert_id, kp)
    assert renew2.status_code == 201
    assert renew2.get_json()["roles"] == ["role:bridge"]


def test_validate_roles_service_prefix(na_service):
    """Service-prefixed roles are accepted."""
    valid, error = na_service._validate_roles(["role:service:my-svc"])
    assert valid is True
    assert error is None


def test_validate_roles_empty_list(na_service):
    """Empty role list is valid."""
    valid, _ = na_service._validate_roles([])
    assert valid is True


def test_validate_roles_mixed_valid_invalid(na_service):
    """A mix of valid and invalid roles is rejected."""
    valid, error = na_service._validate_roles(["role:client", "role:superadmin"])
    assert valid is False
    assert "superadmin" in error


def test_heartbeat_preserves_roles(client, node_keypair):
    """Signed heartbeat must not overwrite roles stored during join."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:anchor"])

    hb_resp = signed_heartbeat(client, join_data["cert_id"], kp)
    assert hb_resp.status_code == 200

    renew_resp = signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    assert renew_resp.get_json()["roles"] == ["role:anchor"]


def test_heartbeat_then_role_escalation_still_rejected(client, node_keypair):
    """After heartbeat, role escalation via renewal is still rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    signed_heartbeat(client, join_data["cert_id"], kp)

    renew_resp = signed_renew(client, join_data["cert_id"], kp, roles=["role:operator"])
    assert renew_resp.status_code == 403


def test_multiple_heartbeats_preserve_roles(client, node_keypair):
    """Multiple heartbeats should not degrade role data."""
    _, join_data, kp = join_node(
        client,
        keypair=node_keypair,
        roles=["role:bridge", "role:anchor"],
    )

    for _ in range(5):
        signed_heartbeat(client, join_data["cert_id"], kp)

    renew_resp = signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    assert sorted(renew_resp.get_json()["roles"]) == ["role:anchor", "role:bridge"]


def test_heartbeat_without_signature_rejected(client, node_keypair):
    """Heartbeat without auth fields is rejected with 401."""
    _, join_data, kp = join_node(client, keypair=node_keypair)
    resp = client.post("/heartbeat", json={
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    })
    assert resp.status_code == 401
    assert "authentication" in resp.get_json()["error"].lower() or "Missing" in resp.get_json()["error"]


def test_heartbeat_with_wrong_key_rejected(client, node_keypair):
    """Heartbeat signed by a different key is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair)
    imposter = generate_keypair()

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    }
    signed = sign_payload(payload, imposter.private_key)
    resp = client.post("/heartbeat", json=signed)
    assert resp.status_code == 401


def test_heartbeat_stale_timestamp_rejected(client, node_keypair):
    """Heartbeat with a stale timestamp is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair)

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
        "timestamp": (datetime.utcnow() - timedelta(minutes=10)).isoformat(),
        "nonce": str(uuid.uuid4()),
    }
    canonical = json.dumps(
        {k: v for k, v in sorted(payload.items()) if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["signature"] = sign_data(canonical.encode("utf-8"), kp.private_key)

    resp = client.post("/heartbeat", json=payload)
    assert resp.status_code == 401
    assert "too old" in resp.get_json()["error"]


def test_heartbeat_nonce_replay_rejected(client, node_keypair):
    """Replaying the exact same heartbeat request is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair)

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    }
    signed = sign_payload(payload, kp.private_key)

    resp1 = client.post("/heartbeat", json=signed)
    assert resp1.status_code == 200

    resp2 = client.post("/heartbeat", json=signed)
    assert resp2.status_code == 401
    assert "replay" in resp2.get_json()["error"].lower()


def test_renew_without_signature_rejected(client, node_keypair):
    """Renewal without auth fields is rejected with 401."""
    _, join_data, kp = join_node(client, keypair=node_keypair)
    resp = client.post("/renew", json={
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
    })
    assert resp.status_code == 401


def test_renew_with_wrong_signature_rejected(client, node_keypair):
    """Renewal signed by wrong key is rejected."""
    _, join_data, kp = join_node(client, keypair=node_keypair)
    imposter = generate_keypair()

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
    }
    signed = sign_payload(payload, imposter.private_key)
    resp = client.post("/renew", json=signed)
    assert resp.status_code == 401
