"""Tests for Network Authority server security: role validation, renew,
heartbeat authentication, and proof-of-possession."""

import json
import uuid
from datetime import datetime, timedelta

import pytest
import nacl.signing
import nacl.encoding

from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.crypto import generate_keypair, sign_data


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def na_service():
    """Create a NetworkAuthorityService with a test keypair."""
    signing_key = nacl.signing.SigningKey.generate()
    pub_b64 = signing_key.verify_key.encode(
        encoder=nacl.encoding.Base64Encoder
    ).decode("utf-8")

    now = datetime.utcnow()
    genesis = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=pub_b64,
        network_authority=NetworkAuthority(
            public_key=pub_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )

    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=signing_key,
        key_id="test-key",
    )
    return service


@pytest.fixture
def client(na_service):
    """Create a Flask test client."""
    na_service.app.config["TESTING"] = True
    return na_service.app.test_client()


@pytest.fixture
def node_keypair():
    """Generate a fresh Ed25519 keypair for a test node."""
    return generate_keypair()


# ── Helpers ──────────────────────────────────────────────────────────


def _sign_payload(payload: dict, private_key) -> dict:
    """Add timestamp, nonce, and Ed25519 signature to a request payload."""
    payload["timestamp"] = datetime.utcnow().isoformat()
    payload["nonce"] = str(uuid.uuid4())
    canonical = json.dumps(
        {k: v for k, v in sorted(payload.items()) if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["signature"] = sign_data(canonical.encode("utf-8"), private_key)
    return payload


def _join(client, node_public_key=None, roles=None, keypair=None):
    """Helper: issue a join certificate. Returns (response, data, keypair)."""
    if keypair is None:
        keypair = generate_keypair()
    if node_public_key is None:
        node_public_key = keypair.public_key_b64
    payload = {"node_public_key": node_public_key}
    if roles is not None:
        payload["roles"] = roles
    resp = client.post("/join", json=payload)
    return resp, resp.get_json(), keypair


def _signed_heartbeat(client, cert_id, keypair, status="healthy"):
    """Send a signed heartbeat and return response."""
    payload = {
        "cert_id": cert_id,
        "node_public_key": keypair.public_key_b64,
        "status": status,
    }
    signed = _sign_payload(payload, keypair.private_key)
    return client.post("/heartbeat", json=signed)


def _signed_renew(client, cert_id, keypair, roles=None, validity_hours=168):
    """Send a signed renewal and return response."""
    payload = {
        "cert_id": cert_id,
        "node_public_key": keypair.public_key_b64,
        "validity_hours": validity_hours,
    }
    if roles is not None:
        payload["roles"] = roles
    signed = _sign_payload(payload, keypair.private_key)
    return client.post("/renew", json=signed)


# ── /join role validation (baseline) ─────────────────────────────────


def test_join_valid_roles(client, node_keypair):
    """Join with valid roles succeeds."""
    resp, data, _ = _join(client, keypair=node_keypair, roles=["role:client"])
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


def test_join_invalid_role_rejected(client, node_keypair):
    """Join with an invalid role prefix is rejected."""
    resp, data, _ = _join(client, keypair=node_keypair, roles=["role:admin"])
    assert resp.status_code == 400
    assert "Invalid role" in data["error"]


def test_join_default_roles(client, node_keypair):
    """Join without specifying roles defaults to role:client."""
    resp, data, _ = _join(client, keypair=node_keypair)
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


# ── /renew: valid signed renewal preserving roles ────────────────────


def test_valid_renewal_preserves_roles(client, node_keypair):
    """A valid signed renewal preserves the original roles."""
    join_resp, join_data, kp = _join(client, keypair=node_keypair, roles=["role:anchor"])
    assert join_resp.status_code == 201

    renew_resp = _signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    renew_data = renew_resp.get_json()
    assert renew_data["roles"] == ["role:anchor"]
    assert renew_data["cert_id"] != join_data["cert_id"]


def test_valid_renewal_with_same_roles_explicit(client, node_keypair):
    """Renewal that explicitly passes the same roles succeeds."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = _signed_renew(client, join_data["cert_id"], kp, roles=["role:client"])
    assert renew_resp.status_code == 201


# ── /renew: role escalation rejected ─────────────────────────────────


def test_renew_role_escalation_rejected(client, node_keypair):
    """Attempting to add higher-privilege roles during renewal is rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = _signed_renew(client, join_data["cert_id"], kp, roles=["role:anchor", "role:operator"])
    assert renew_resp.status_code == 403
    assert "not permitted" in renew_resp.get_json()["error"]


def test_renew_role_downgrade_also_rejected(client, node_keypair):
    """Even role 'downgrade' attempts are rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:anchor", "role:bridge"])
    renew_resp = _signed_renew(client, join_data["cert_id"], kp, roles=["role:client"])
    assert renew_resp.status_code == 403


def test_renew_add_extra_role_rejected(client, node_keypair):
    """Adding an extra role to the existing set during renewal is rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:client"])
    renew_resp = _signed_renew(client, join_data["cert_id"], kp, roles=["role:client", "role:operator"])
    assert renew_resp.status_code == 403


# ── /renew: key mismatch rejected ────────────────────────────────────


def test_renew_wrong_key_rejected(client, node_keypair):
    """Renewal with a different node_public_key is rejected (before auth)."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:client"])
    # Different key — fails the key-match check before auth
    other_kp = generate_keypair()
    renew_resp = _signed_renew(client, join_data["cert_id"], other_kp)
    assert renew_resp.status_code == 403
    assert "does not match" in renew_resp.get_json()["error"]


# ── /renew: unknown cert rejected ────────────────────────────────────


def test_renew_unknown_cert_rejected(client, node_keypair):
    """Renewal of an unknown cert_id is rejected."""
    payload = _sign_payload({
        "cert_id": "nonexistent-cert-id",
        "node_public_key": node_keypair.public_key_b64,
    }, node_keypair.private_key)
    renew_resp = client.post("/renew", json=payload)
    assert renew_resp.status_code == 403
    assert "Unknown certificate" in renew_resp.get_json()["error"]


# ── /renew: missing fields ───────────────────────────────────────────


def test_renew_missing_cert_id(client, node_keypair):
    """Renewal without cert_id returns 400."""
    resp = client.post("/renew", json={"node_public_key": node_keypair.public_key_b64})
    assert resp.status_code == 400


def test_renew_missing_public_key(client):
    """Renewal without node_public_key returns 400."""
    resp = client.post("/renew", json={"cert_id": "some-cert"})
    assert resp.status_code == 400


# ── /renew: chained renewal ──────────────────────────────────────────


def test_chained_renewal(client, node_keypair):
    """A renewed certificate can itself be renewed (chain of renewals)."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:bridge"])

    # First renewal
    renew1 = _signed_renew(client, join_data["cert_id"], kp)
    assert renew1.status_code == 201
    new_cert_id = renew1.get_json()["cert_id"]

    # Second renewal using the new cert
    renew2 = _signed_renew(client, new_cert_id, kp)
    assert renew2.status_code == 201
    assert renew2.get_json()["roles"] == ["role:bridge"]


# ── _validate_roles shared logic ─────────────────────────────────────


def test_validate_roles_service_prefix(na_service):
    """Service-prefixed roles are accepted."""
    valid, error = na_service._validate_roles(["role:service:my-svc"])
    assert valid is True
    assert error is None


def test_validate_roles_empty_list(na_service):
    """Empty role list is valid."""
    valid, error = na_service._validate_roles([])
    assert valid is True


def test_validate_roles_mixed_valid_invalid(na_service):
    """A mix of valid and invalid roles is rejected."""
    valid, error = na_service._validate_roles(["role:client", "role:superadmin"])
    assert valid is False
    assert "superadmin" in error


# ── /heartbeat: authenticated + role preservation ────────────────────


def test_heartbeat_preserves_roles(client, node_keypair):
    """Signed heartbeat should NOT overwrite roles stored during /join."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:anchor"])

    hb_resp = _signed_heartbeat(client, join_data["cert_id"], kp)
    assert hb_resp.status_code == 200

    renew_resp = _signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    assert renew_resp.get_json()["roles"] == ["role:anchor"]


def test_heartbeat_then_role_escalation_still_rejected(client, node_keypair):
    """After heartbeat, role escalation via /renew should still be rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:client"])
    _signed_heartbeat(client, join_data["cert_id"], kp)

    renew_resp = _signed_renew(client, join_data["cert_id"], kp, roles=["role:operator"])
    assert renew_resp.status_code == 403


def test_multiple_heartbeats_preserve_roles(client, node_keypair):
    """Multiple heartbeats should not degrade role data."""
    _, join_data, kp = _join(client, keypair=node_keypair, roles=["role:bridge", "role:anchor"])

    for _ in range(5):
        _signed_heartbeat(client, join_data["cert_id"], kp)

    renew_resp = _signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 201
    assert sorted(renew_resp.get_json()["roles"]) == ["role:anchor", "role:bridge"]


# ── /heartbeat: authentication enforcement ───────────────────────────


def test_heartbeat_without_signature_rejected(client, node_keypair):
    """Heartbeat without auth fields is rejected with 401."""
    _, join_data, kp = _join(client, keypair=node_keypair)
    resp = client.post("/heartbeat", json={
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    })
    assert resp.status_code == 401
    assert "authentication" in resp.get_json()["error"].lower() or "Missing" in resp.get_json()["error"]


def test_heartbeat_with_wrong_key_rejected(client, node_keypair):
    """Heartbeat signed by a different key is rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair)
    imposter = generate_keypair()

    # Sign with imposter key but claim our public key
    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    }
    signed = _sign_payload(payload, imposter.private_key)
    resp = client.post("/heartbeat", json=signed)
    assert resp.status_code == 401


def test_heartbeat_stale_timestamp_rejected(client, node_keypair):
    """Heartbeat with a stale timestamp is rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair)

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
    _, join_data, kp = _join(client, keypair=node_keypair)

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
        "status": "healthy",
    }
    signed = _sign_payload(payload, kp.private_key)

    resp1 = client.post("/heartbeat", json=signed)
    assert resp1.status_code == 200

    # Replay same nonce
    resp2 = client.post("/heartbeat", json=signed)
    assert resp2.status_code == 401
    assert "replay" in resp2.get_json()["error"].lower()


# ── /renew: authentication enforcement ───────────────────────────────


def test_renew_without_signature_rejected(client, node_keypair):
    """Renewal without auth fields is rejected with 401."""
    _, join_data, kp = _join(client, keypair=node_keypair)
    resp = client.post("/renew", json={
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
    })
    assert resp.status_code == 401


def test_renew_with_wrong_signature_rejected(client, node_keypair):
    """Renewal signed by wrong key is rejected."""
    _, join_data, kp = _join(client, keypair=node_keypair)
    imposter = generate_keypair()

    payload = {
        "cert_id": join_data["cert_id"],
        "node_public_key": kp.public_key_b64,
    }
    signed = _sign_payload(payload, imposter.private_key)
    resp = client.post("/renew", json=signed)
    assert resp.status_code == 401
