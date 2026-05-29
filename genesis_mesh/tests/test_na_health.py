"""Tests for Network Authority health and persistence behavior."""

from __future__ import annotations

from datetime import datetime

from genesis_mesh.crypto import sign_model
from genesis_mesh.na_service.server import NetworkAuthorityService


def test_readyz_returns_503_when_db_check_fails(na_service):
    """Readiness should fail closed when the database cannot be queried."""

    class BrokenConnection:
        """Connection stub that simulates a database outage."""

        def execute(self, *args, **kwargs):
            """Raise for every query."""
            raise RuntimeError("database unavailable")

    na_service.db.conn = BrokenConnection()
    resp = na_service.app.test_client().get("/readyz")

    assert resp.status_code == 503
    assert resp.get_json()["status"] == "not_ready"


def test_na_restart_preserves_persisted_state(tmp_path, na_service, node_keypair):
    """A new service instance should load durable NA state from SQLite."""
    db_path = tmp_path / "na-restart.db"
    first = NetworkAuthorityService(
        genesis_block=na_service.genesis_block,
        na_private_key=na_service.na_private_key,
        key_id=na_service.key_id,
        db_path=str(db_path),
        operator_public_keys=na_service.operator_public_keys,
    )

    invite = first.db.create_invite_token(["role:client"], 24, 1)
    cert = first._issue_join_certificate(
        node_public_key=node_keypair.public_key_b64,
        roles=["role:client"],
        validity_hours=24,
    )
    first.db.issue_cert(cert, "127.0.0.1")
    first.db.add_nonce("node:test", "nonce-1", datetime.utcnow())

    crl = first.db.revoke_cert(cert.cert_id, "key_compromise", first.key_id)
    crl.signatures.append(sign_model(crl, first.na_private_key, first.key_id))
    first.db.save_crl(crl, active=True)

    policy = first._get_default_policy()
    policy.policy_id = "policy-restart"
    policy.signatures = [sign_model(policy, first.na_private_key, first.key_id)]
    first.db.save_policy(policy, active=True)

    second = NetworkAuthorityService(
        genesis_block=na_service.genesis_block,
        na_private_key=na_service.na_private_key,
        key_id=na_service.key_id,
        db_path=str(db_path),
        operator_public_keys=na_service.operator_public_keys,
    )

    assert second.db.conn.execute(
        "SELECT 1 FROM invite_tokens WHERE token_id = ?",
        (invite.token_id,),
    ).fetchone()
    assert second.db.get_cert(cert.cert_id)["node_public_key"] == node_keypair.public_key_b64
    assert second.db.get_active_crl().is_cert_revoked(cert.cert_id)
    assert second.db.get_active_policy().policy_id == "policy-restart"
    assert second.db.has_nonce("node:test", "nonce-1") is True
