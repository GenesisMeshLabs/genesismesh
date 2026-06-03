"""Tests for Network Authority public routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair


def test_homepage_links_to_operational_routes(client):
    """The Network Authority root should be useful in a browser."""
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"

    body = resp.get_data(as_text=True)
    assert "Genesis Mesh Network Authority" in body
    assert "TEST" in body
    assert "/healthz" in body
    assert "/readyz" in body
    assert "/sovereign.json" in body
    assert "/genesis" in body
    assert "/policy" in body
    assert "/crl" in body
    assert "/nodes" in body
    assert "/admin/invite" in body


def test_homepage_counts_recent_joined_nodes_as_active(na_service):
    """Recently joined nodes should be reflected in the operator summary."""
    active_cert = na_service._issue_join_certificate(
        node_public_key=generate_keypair().public_key_b64,
        roles=["role:anchor"],
        validity_hours=24,
    )
    stale_cert = na_service._issue_join_certificate(
        node_public_key=generate_keypair().public_key_b64,
        roles=["role:client"],
        validity_hours=24,
    )
    revoked_cert = na_service._issue_join_certificate(
        node_public_key=generate_keypair().public_key_b64,
        roles=["role:client"],
        validity_hours=24,
    )
    na_service.db.issue_cert(active_cert, "127.0.0.1")
    na_service.db.issue_cert(stale_cert, "127.0.0.1")
    na_service.db.issue_cert(revoked_cert, "127.0.0.1")
    na_service.db.conn.execute(
        "UPDATE issued_certs SET last_heartbeat = ? WHERE cert_id = ?",
        (
            (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            stale_cert.cert_id,
        ),
    )
    na_service.db.conn.execute(
        "UPDATE issued_certs SET status = 'revoked' WHERE cert_id = ?",
        (revoked_cert.cert_id,),
    )

    resp = na_service.app.test_client().get("/")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<span>Active Nodes</span><strong>1</strong>" in body
    assert "<span>Tracked Nodes</span><strong>2</strong>" in body


def test_sovereign_metadata_exposes_public_trust_material(client):
    """Public sovereign metadata should identify the operator trust domain."""
    resp = client.get("/sovereign.json", base_url="https://na.example.test")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["sovereign_id"] == "TEST"
    assert payload["network_name"] == "TEST"
    assert payload["network_version"] == "v0.1"
    assert payload["endpoint"] == "https://na.example.test"
    assert payload["network_authority"]["public_key"]
    assert payload["root_public_key"]
    assert payload["supported_surfaces"]["genesis"] == "https://na.example.test/genesis"
    assert payload["supported_surfaces"]["connectome"] == "https://na.example.test/connectome.json"
    assert "private" not in str(payload).lower()


def test_sovereign_metadata_honors_proxy_headers(client):
    """Public metadata should advertise the proxy-visible URL."""
    resp = client.get(
        "/sovereign.json",
        base_url="http://127.0.0.1:8443",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "na.genesismesh.connectorzzz.com",
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["endpoint"] == "https://na.genesismesh.connectorzzz.com"
    assert (
        payload["supported_surfaces"]["sovereign_revocation_feed"]
        == "https://na.genesismesh.connectorzzz.com/sovereign-revocation-feed"
    )
