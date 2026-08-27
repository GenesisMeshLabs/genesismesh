"""F-20: renewal supersedes the predecessor certificate after a grace window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import public_key_from_b64, verify_model_signature
from genesis_mesh.models.revocation import CertificateRevocationList, RevokedCertificate

from .na_server_helpers import join_node, revoke_cert, signed_heartbeat, signed_renew


def _crl_ids(client) -> list[str]:
    """Return the certificate IDs listed in the published CRL."""
    resp = client.get("/crl")
    assert resp.status_code == 200
    return [rc["certificate_id"] for rc in resp.get_json()["revoked_certificates"]]


def _error_code(resp) -> str:
    """Return the error code from an API error response."""
    return (resp.get_json() or {}).get("error", {}).get("code", "")


def test_predecessor_survives_the_grace_window(client, node_keypair, na_service):
    """Within the grace window the predecessor still works and can retry renewal."""
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    old_cert_id = join_data["cert_id"]

    renew_resp = signed_renew(client, old_cert_id, kp)
    assert renew_resp.status_code == 201

    # The predecessor is scheduled, not revoked: a node whose renewal response
    # was lost keeps heartbeating and can renew again.
    row = na_service.db.get_cert(old_cert_id)
    assert row["revoke_after"] is not None
    assert row["status"] == "issued"

    assert signed_heartbeat(client, old_cert_id, kp).status_code == 200
    retry = signed_renew(client, old_cert_id, kp)
    assert retry.status_code == 201
    assert old_cert_id not in _crl_ids(client)


def test_predecessor_is_rejected_and_revoked_after_the_grace_window(
    client, node_keypair, na_service
):
    """Once the grace window closes the predecessor is refused and CRL-listed."""
    na_service.renewal_grace_seconds = 0
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:client"])
    old_cert_id = join_data["cert_id"]

    renew_resp = signed_renew(client, old_cert_id, kp)
    assert renew_resp.status_code == 201
    new_cert_id = renew_resp.get_json()["cert_id"]

    hb = signed_heartbeat(client, old_cert_id, kp)
    assert hb.status_code == 403
    assert _error_code(hb) == "certificate_revoked"

    retry = signed_renew(client, old_cert_id, kp)
    assert retry.status_code == 403
    assert _error_code(retry) == "certificate_revoked"

    assert na_service.db.get_cert(old_cert_id)["revocation_reason"] == "superseded"
    assert old_cert_id in _crl_ids(client)
    assert new_cert_id not in _crl_ids(client)


def test_matured_predecessor_is_refused_before_any_sweep_runs(
    client, node_keypair, na_service
):
    """Rejection is time-based: it does not wait for a CRL publication."""
    _, join_data, kp = join_node(client, keypair=node_keypair)
    old_cert_id = join_data["cert_id"]
    assert signed_renew(client, old_cert_id, kp).status_code == 201

    # Close the window without letting anything publish a CRL.
    na_service.db.mark_superseded(
        old_cert_id, datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert na_service.db.get_cert(old_cert_id)["status"] == "issued"

    hb = signed_heartbeat(client, old_cert_id, kp)
    assert hb.status_code == 403
    assert _error_code(hb) == "certificate_superseded"

    retry = signed_renew(client, old_cert_id, kp)
    assert retry.status_code == 403
    assert _error_code(retry) == "certificate_superseded"


def test_renewed_certificate_keeps_working(client, node_keypair, na_service):
    """Negative control: superseding the predecessor never touches the successor."""
    na_service.renewal_grace_seconds = 0
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:anchor"])

    renew_resp = signed_renew(client, join_data["cert_id"], kp)
    new_cert_id = renew_resp.get_json()["cert_id"]

    assert signed_heartbeat(client, new_cert_id, kp).status_code == 200
    client.get("/crl")
    assert signed_heartbeat(client, new_cert_id, kp).status_code == 200


def test_published_crl_stays_na_signed(client, node_keypair, na_service):
    """The swept CRL is signed by the NA key and verifies."""
    na_service.renewal_grace_seconds = 0
    _, join_data, kp = join_node(client, keypair=node_keypair)
    signed_renew(client, join_data["cert_id"], kp)

    crl = CertificateRevocationList.model_validate(client.get("/crl").get_json())
    assert crl.signatures
    na_public_key = public_key_from_b64(
        na_service.genesis_block.network_authority.public_key
    )
    assert verify_model_signature(crl, crl.signatures[0], na_public_key)


def test_chained_renewal_supersedes_each_predecessor(client, node_keypair, na_service):
    """cert1 -> cert2 -> cert3 leaves only the newest certificate usable."""
    na_service.renewal_grace_seconds = 0
    _, join_data, kp = join_node(client, keypair=node_keypair, roles=["role:bridge"])
    cert1 = join_data["cert_id"]

    cert2 = signed_renew(client, cert1, kp).get_json()["cert_id"]
    cert3 = signed_renew(client, cert2, kp).get_json()["cert_id"]

    revoked = _crl_ids(client)
    assert cert1 in revoked
    assert cert2 in revoked
    assert cert3 not in revoked
    assert signed_heartbeat(client, cert3, kp).status_code == 200


def test_superseded_revocations_are_batched_into_one_crl_version(
    client, node_keypair, na_service
):
    """Predecessors maturing between publications share a single sequence bump."""
    _, join_a, kp_a = join_node(client, keypair=node_keypair)
    _, join_b, kp_b = join_node(client)

    before = client.get("/crl").get_json()["sequence"]
    cert_a = join_a["cert_id"]
    cert_b = join_b["cert_id"]
    assert signed_renew(client, cert_a, kp_a).status_code == 201
    assert signed_renew(client, cert_b, kp_b).status_code == 201

    # Both windows close while nothing is reading the CRL.
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    na_service.db.mark_superseded(cert_a, past)
    na_service.db.mark_superseded(cert_b, past)

    after = client.get("/crl").get_json()
    assert after["sequence"] == before + 1
    assert sorted(rc["certificate_id"] for rc in after["revoked_certificates"]) == sorted(
        [cert_a, cert_b]
    )


def test_expired_certificate_entries_are_pruned_from_the_crl(
    client, node_keypair, na_service
):
    """Entries for long-expired certificates drop out; live ones are retained."""
    _, join_data, _ = join_node(client, keypair=node_keypair)
    live_cert_id = join_data["cert_id"]
    assert revoke_cert(client, live_cert_id, reason="key_compromise").status_code == 200

    # An entry whose certificate expired well beyond the retention margin.
    expired_at = datetime.now(timezone.utc) - timedelta(days=2)
    na_service.db.conn.execute(
        """
        INSERT INTO issued_certs (
            cert_id, node_public_key, cert_json, roles_json, issued_at,
            expires_at, remote_addr, status
        ) VALUES (?, ?, '{}', '[]', ?, ?, 'test', 'revoked')
        """,
        (
            "expired-cert",
            "expired-node-key",
            (expired_at - timedelta(days=7)).isoformat(),
            expired_at.isoformat(),
        ),
    )
    na_service.db.conn.commit()

    stale = na_service.db.get_active_crl()
    stale.revoked_certificates.append(
        RevokedCertificate(
            certificate_id="expired-cert",
            revoked_at=expired_at,
            reason="superseded",
            issuer=na_service.key_id,
        )
    )
    na_service.db.save_crl(stale, active=True)
    assert "expired-cert" in [
        rc.certificate_id for rc in na_service.db.get_active_crl().revoked_certificates
    ]

    # Publishing drops the useless entry and keeps the still-valid one.
    published = _crl_ids(client)
    assert "expired-cert" not in published
    assert live_cert_id in published
