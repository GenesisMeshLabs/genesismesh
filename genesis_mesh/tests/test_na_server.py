"""Tests for Network Authority server /renew security hardening."""

import json
from datetime import datetime, timedelta

import pytest
import nacl.signing
import nacl.encoding

from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService


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


def _join(client, node_public_key="dGVzdC1rZXk=", roles=None):
    """Helper: issue a join certificate and return (response, data)."""
    payload = {"node_public_key": node_public_key}
    if roles is not None:
        payload["roles"] = roles
    resp = client.post("/join", json=payload)
    return resp, resp.get_json()


# ── /join role validation (baseline) ─────────────────────────────────


def test_join_valid_roles(client):
    """Join with valid roles succeeds."""
    resp, data = _join(client, roles=["role:client"])
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


def test_join_invalid_role_rejected(client):
    """Join with an invalid role prefix is rejected."""
    resp, data = _join(client, roles=["role:admin"])
    assert resp.status_code == 400
    assert "Invalid role" in data["error"]


def test_join_default_roles(client):
    """Join without specifying roles defaults to role:client."""
    resp, data = _join(client)
    assert resp.status_code == 201
    assert data["roles"] == ["role:client"]


# ── /renew: valid renewal preserving roles ───────────────────────────


def test_valid_renewal_preserves_roles(client):
    """A valid renewal with matching key preserves the original roles."""
    # Join first
    join_resp, join_data = _join(client, roles=["role:anchor"])
    assert join_resp.status_code == 201
    cert_id = join_data["cert_id"]
    node_key = join_data["node_public_key"]

    # Renew
    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
    })
    assert renew_resp.status_code == 201
    renew_data = renew_resp.get_json()
    assert renew_data["roles"] == ["role:anchor"]
    assert renew_data["cert_id"] != cert_id  # new cert ID


def test_valid_renewal_with_same_roles_explicit(client):
    """Renewal that explicitly passes the same roles succeeds."""
    join_resp, join_data = _join(client, roles=["role:client"])
    cert_id = join_data["cert_id"]
    node_key = join_data["node_public_key"]

    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
        "roles": ["role:client"],
    })
    assert renew_resp.status_code == 201


# ── /renew: role escalation rejected ─────────────────────────────────


def test_renew_role_escalation_rejected(client):
    """Attempting to add higher-privilege roles during renewal is rejected."""
    join_resp, join_data = _join(client, roles=["role:client"])
    cert_id = join_data["cert_id"]
    node_key = join_data["node_public_key"]

    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
        "roles": ["role:anchor", "role:operator"],
    })
    assert renew_resp.status_code == 403
    assert "not permitted" in renew_resp.get_json()["error"]


def test_renew_role_downgrade_also_rejected(client):
    """Even role 'downgrade' attempts are rejected — roles must be preserved."""
    join_resp, join_data = _join(client, roles=["role:anchor", "role:bridge"])
    cert_id = join_data["cert_id"]
    node_key = join_data["node_public_key"]

    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
        "roles": ["role:client"],
    })
    assert renew_resp.status_code == 403


def test_renew_add_extra_role_rejected(client):
    """Adding an extra role to the existing set during renewal is rejected."""
    join_resp, join_data = _join(client, roles=["role:client"])
    cert_id = join_data["cert_id"]
    node_key = join_data["node_public_key"]

    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
        "roles": ["role:client", "role:operator"],
    })
    assert renew_resp.status_code == 403


# ── /renew: key mismatch rejected ────────────────────────────────────


def test_renew_wrong_key_rejected(client):
    """Renewal with a different node_public_key is rejected."""
    join_resp, join_data = _join(client, roles=["role:client"])
    cert_id = join_data["cert_id"]

    renew_resp = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": "d3Jvbmcta2V5",  # different key
    })
    assert renew_resp.status_code == 403
    assert "does not match" in renew_resp.get_json()["error"]


# ── /renew: unknown cert rejected ────────────────────────────────────


def test_renew_unknown_cert_rejected(client):
    """Renewal of an unknown cert_id is rejected."""
    renew_resp = client.post("/renew", json={
        "cert_id": "nonexistent-cert-id",
        "node_public_key": "dGVzdC1rZXk=",
    })
    assert renew_resp.status_code == 403
    assert "Unknown certificate" in renew_resp.get_json()["error"]


# ── /renew: missing fields ───────────────────────────────────────────


def test_renew_missing_cert_id(client):
    """Renewal without cert_id returns 400."""
    renew_resp = client.post("/renew", json={
        "node_public_key": "dGVzdC1rZXk=",
    })
    assert renew_resp.status_code == 400


def test_renew_missing_public_key(client):
    """Renewal without node_public_key returns 400."""
    renew_resp = client.post("/renew", json={
        "cert_id": "some-cert",
    })
    assert renew_resp.status_code == 400


# ── /renew: renewed cert can be renewed again ────────────────────────


def test_chained_renewal(client):
    """A renewed certificate can itself be renewed (chain of renewals)."""
    join_resp, join_data = _join(client, roles=["role:bridge"])
    node_key = join_data["node_public_key"]
    cert_id = join_data["cert_id"]

    # First renewal
    renew1 = client.post("/renew", json={
        "cert_id": cert_id,
        "node_public_key": node_key,
    })
    assert renew1.status_code == 201
    new_cert_id = renew1.get_json()["cert_id"]

    # Second renewal using the new cert
    renew2 = client.post("/renew", json={
        "cert_id": new_cert_id,
        "node_public_key": node_key,
    })
    assert renew2.status_code == 201
    assert renew2.get_json()["roles"] == ["role:bridge"]


# ── _validate_roles shared logic ─────────────────────────────────────


def test_validate_roles_service_prefix(na_service):
    """Service-prefixed roles are accepted."""
    valid, error = na_service._validate_roles(["role:service:my-svc"])
    assert valid is True
    assert error is None


def test_validate_roles_empty_list(na_service):
    """Empty role list is valid (no invalid roles to reject)."""
    valid, error = na_service._validate_roles([])
    assert valid is True


def test_validate_roles_mixed_valid_invalid(na_service):
    """A mix of valid and invalid roles is rejected."""
    valid, error = na_service._validate_roles(["role:client", "role:superadmin"])
    assert valid is False
    assert "superadmin" in error
