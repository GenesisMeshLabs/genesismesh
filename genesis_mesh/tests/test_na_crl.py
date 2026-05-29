"""Tests for Network Authority CRL and revocation routes."""

from __future__ import annotations

from .na_server_helpers import join_node, revoke_cert, signed_heartbeat, signed_renew


def test_get_crl_returns_signed_empty_crl(client):
    """The CRL endpoint returns a signed sequence-zero CRL initially."""
    resp = client.get("/crl")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sequence"] == 0
    assert data["revoked_certificates"] == []
    assert data["signatures"]


def test_revoke_updates_crl_and_blocks_heartbeat(client, node_keypair):
    """Revocation publishes a CRL entry and blocks further heartbeats."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])

    revoke_resp = revoke_cert(client, join_data["cert_id"], reason="key_compromise")
    assert revoke_resp.status_code == 200
    assert revoke_resp.get_json()["revoked_count"] == 1

    crl_resp = client.get("/crl")
    assert crl_resp.status_code == 200
    crl_data = crl_resp.get_json()
    revoked_ids = [rc["certificate_id"] for rc in crl_data["revoked_certificates"]]
    assert join_data["cert_id"] in revoked_ids

    hb_resp = signed_heartbeat(client, join_data["cert_id"], kp)
    assert hb_resp.status_code == 403


def test_revoked_cert_cannot_renew(client, node_keypair):
    """A revoked certificate cannot be renewed."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    assert revoke_cert(client, join_data["cert_id"]).status_code == 200

    renew_resp = signed_renew(client, join_data["cert_id"], kp)
    assert renew_resp.status_code == 403
