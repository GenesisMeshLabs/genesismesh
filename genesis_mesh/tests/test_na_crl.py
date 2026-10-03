"""Tests for Network Authority CRL and revocation routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto.signing import verify_model_signature
from genesis_mesh.models.revocation import CertificateRevocationList

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


def _age_active_crl(service, hours: float) -> None:
    """Move the active CRL's validity window into the past, as time passing would."""
    crl = service.db.get_active_crl()
    shift = timedelta(hours=hours)
    aged = crl.model_copy(update={"issued_at": crl.issued_at - shift, "next_update": crl.next_update - shift})
    with service.db.conn:
        service.db.conn.execute(
            "UPDATE crl_versions SET crl_json = ? WHERE sequence = ? AND active = 1",
            (aged.model_dump_json(), crl.sequence),
        )


def test_quiet_na_republishes_an_expiring_crl_with_the_same_revocations(client, node_keypair, na_service):
    _, join_data, _ = join_node(client, keypair=node_keypair, roles=["role:client"])
    assert revoke_cert(client, join_data["cert_id"]).status_code == 200
    before = client.get("/crl").get_json()
    _age_active_crl(na_service, hours=13)

    after = client.get("/crl").get_json()
    assert after["sequence"] == before["sequence"] + 1
    assert after["revoked_certificates"] == before["revoked_certificates"]
    crl = CertificateRevocationList.model_validate(after)
    assert crl.next_update - datetime.now(timezone.utc) > timedelta(hours=23)
    assert verify_model_signature(crl, crl.signatures[0], na_service.signer.public_key_b64)


def test_expired_crl_is_replaced_and_a_fresh_one_is_not(client, na_service):
    first = client.get("/crl").get_json()
    assert client.get("/crl").get_json()["sequence"] == first["sequence"]
    _age_active_crl(na_service, hours=30)
    assert client.get("/crl").get_json()["sequence"] == first["sequence"] + 1
    assert client.get("/crl").get_json()["sequence"] == first["sequence"] + 1
