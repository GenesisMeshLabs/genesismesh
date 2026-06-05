"""Tests for Network Authority recognition treaty routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .na_server_helpers import admin_headers


def _issue_treaty(client, na_service, allowed_roles=None):
    """Issue an operator-authorized recognition treaty through the API."""
    body = {
        "subject_sovereign_id": "sovereign-b",
        "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": allowed_roles or ["role:client"]},
        "validity_hours": 24,
    }
    return client.post(
        "/admin/recognition-treaties",
        json=body,
        headers=admin_headers(client, body),
    )


def _issue_attestation(client, subject_id: str = "alice", roles=None):
    """Issue an operator-authorized membership attestation through the API."""
    body = {
        "issuer_sovereign_id": "sovereign-b",
        "subject_id": subject_id,
        "subject_public_key": "subject-public-key",
        "roles": roles or ["role:client"],
        "validity_hours": 24,
    }
    return client.post(
        "/admin/attestations",
        json=body,
        headers=admin_headers(client, body),
    )


def test_admin_can_issue_recognition_treaty(client, na_service):
    """An operator can issue a signed treaty for another sovereign."""
    resp = _issue_treaty(client, na_service)

    assert resp.status_code == 201
    treaty = resp.get_json()
    assert treaty["issuer_sovereign_id"] == "TEST"
    assert treaty["subject_sovereign_id"] == "sovereign-b"
    assert treaty["scope"]["allowed_roles"] == ["role:client"]
    assert treaty["signatures"]

    stored = client.get(f"/recognition-treaties/{treaty['treaty_id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "active"


def test_treaty_verification_accepts_signed_treaty(client, na_service):
    """The public verifier accepts a valid signed treaty."""
    treaty = _issue_treaty(client, na_service).get_json()

    resp = client.post("/recognition-treaties/verify", json={"treaty": treaty})

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_verify_with_treaty_accepts_scoped_role(client, na_service):
    """A treaty can back acceptance of a subject sovereign's attestation."""
    treaty = _issue_treaty(client, na_service).get_json()
    attestation = _issue_attestation(client).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_verify_with_treaty_rejects_role_outside_scope(client, na_service):
    """Treaty role scope limits which attestations are accepted."""
    treaty = _issue_treaty(client, na_service, allowed_roles=["role:anchor"]).get_json()
    attestation = _issue_attestation(client, roles=["role:client"]).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "attestation_role_not_allowed"


def test_revoking_treaty_changes_treaty_backed_verification(client, na_service):
    """A revoked treaty cannot continue backing attestation verification."""
    treaty = _issue_treaty(client, na_service).get_json()
    attestation = _issue_attestation(client).get_json()

    revoke_body = {"reason": "relationship_ended"}
    revoke = client.post(
        f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    assert revoke.status_code == 200

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "treaty_locally_revoked"


def test_recognition_graph_exports_edges_and_revoked_material(client, na_service):
    """The graph export exposes sovereign nodes, treaty edges, and revocations."""
    treaty = _issue_treaty(client, na_service).get_json()
    revoke_body = {"reason": "relationship_ended"}
    client.post(
        f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )

    resp = client.get("/recognition-graph")

    assert resp.status_code == 200
    graph = resp.get_json()
    assert {"sovereign_id": "TEST"} in graph["sovereigns"]
    assert {"sovereign_id": "sovereign-b"} in graph["sovereigns"]
    assert graph["recognition_edges"][0]["from"] == "TEST"
    assert graph["recognition_edges"][0]["to"] == "sovereign-b"
    assert graph["recognition_edges"][0]["status"] == "revoked"
    assert graph["revoked_trust_material"][0]["id"] == treaty["treaty_id"]


def test_connectome_json_summarizes_recognition_graph(client, na_service):
    """The Connectome JSON endpoint gives operators graph metrics and edges."""
    treaty = _issue_treaty(client, na_service).get_json()

    resp = client.get("/connectome.json")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["summary"]["sovereign_count"] == 2
    assert data["summary"]["active_edge_count"] == 1
    assert data["recognition_edges"][0]["treaty_id"] == treaty["treaty_id"]
    assert data["recognition_edges"][0]["status"] == "active"


def test_connectome_page_renders_html(client, na_service):
    """The operator Connectome page renders as HTML."""
    _issue_treaty(client, na_service)

    resp = client.get("/connectome")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert b"Genesis Mesh Connectome" in resp.data
    assert b"Recognition Edges" in resp.data
    body = resp.get_data(as_text=True)
    assert 'class="shell operator-console"' in body
    assert "Connectome derived view" not in body
    assert "Sovereign Graph" in body
    assert "Current Recognition Edges" in body
    assert "Historical Recognition Edges" in body
    assert "Persisted status" in body
    assert "Valid from" in body
    assert "Expires at" in body
    assert "Lifecycle" in body
    assert "Expiry risk" in body
    edge_table = body.split("Current Recognition Edges", 1)[1].split("</table>", 1)[0]
    assert "+00:00" not in edge_table
    assert "UTC" in edge_table
    assert "connectome-graph" in body
    assert "graph-node" in body
    assert "data-table" in body
    assert "Download Connectome JSON" in body
    assert "The Connectome explains current trust state" in body
    assert "Console" in body
    assert "API Docs" in body
    assert "CLI Docs" in body
    assert "nav-link-active" in body
    assert 'href="/operator-console-static/styles.css"' in body
    assert 'src="/operator-console-static/console.js"' in body


def test_connectome_page_separates_expired_persisted_active_edges(client, na_service):
    """Expired active DB rows should be historical, not current trust."""
    treaty = _issue_treaty(client, na_service).get_json()
    row = na_service.db.get_recognition_treaty(treaty["treaty_id"])
    assert row is not None
    now = datetime.now(timezone.utc)
    expired_treaty = row["treaty"].model_copy(update={
        "issued_at": now - timedelta(days=2),
        "valid_from": now - timedelta(days=2),
        "expires_at": now - timedelta(days=1),
    })
    na_service.db.save_recognition_treaty(expired_treaty, status="active")

    resp = client.get("/connectome")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    current = body.split("<h2>Current Recognition Edges</h2>", 1)[1].split("</table>", 1)[0]
    historical = body.split("<h2>Historical Recognition Edges</h2>", 1)[1].split("</table>", 1)[0]
    assert treaty["treaty_id"] not in current
    assert "No current recognition edges" in current
    assert treaty["treaty_id"] in historical
    assert "active" in historical
    assert "expired" in historical


def test_connectome_page_uses_single_empty_state_when_fresh(client):
    """A fresh Connectome should not render multiple empty diagnostic tables."""
    resp = client.get("/connectome")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No recognition or revocation state yet." in body
    assert "No recognition edges" not in body
    assert "No revoked trust material" not in body
    assert "No imported revocation blast radius" not in body
    assert "<h2>Trust State</h2>" in body
    assert "Download Connectome JSON" in body


def test_connectome_trust_path_reports_active_and_revoked_edges(client, na_service):
    """Trust path explanation changes when a treaty is revoked."""
    treaty = _issue_treaty(client, na_service).get_json()

    active = client.get("/connectome/trust-path?from=TEST&to=sovereign-b")
    assert active.status_code == 200
    assert active.get_json()["trusted"] is True
    assert active.get_json()["reason"] == "active_treaty_path"

    revoke_body = {"reason": "relationship_ended"}
    client.post(
        f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    revoked = client.get("/connectome/trust-path?from=TEST&to=sovereign-b")

    assert revoked.status_code == 200
    assert revoked.get_json()["trusted"] is False
    assert revoked.get_json()["reason"] == "direct_treaty_revoked"


def test_connectome_trust_path_requires_source_and_target(client):
    """Trust path route returns a controlled error for missing parameters."""
    resp = client.get("/connectome/trust-path?from=TEST")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "from/source and to/target are required"


def test_imported_revocation_feed_blocks_treaty_backed_attestation(client, na_service):
    """A propagated issuer revocation stops treaty-backed attestation acceptance."""
    treaty = _issue_treaty(client, na_service).get_json()
    attestation = _issue_attestation(client).get_json()

    accepted = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["accepted"] is True

    revoke_body = {"reason": "key_compromise"}
    revoke = client.post(
        f"/admin/attestations/{attestation['attestation_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    assert revoke.status_code == 200

    feed_resp = client.get("/sovereign-revocation-feed?issuer_sovereign_id=sovereign-b")
    assert feed_resp.status_code == 200
    feed = feed_resp.get_json()
    assert feed["revoked_attestation_ids"] == [attestation["attestation_id"]]

    import_body = {"feed": feed}
    imported = client.post(
        "/admin/sovereign-revocation-feeds/import",
        json=import_body,
        headers=admin_headers(client, import_body),
    )
    assert imported.status_code == 200
    assert imported.get_json()["accepted"] is True

    rejected = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["accepted"] is False
    assert rejected.get_json()["reason"] == "attestation_locally_revoked"

    graph = client.get("/recognition-graph").get_json()
    assert any(
        item["type"] == "membership_attestation"
        and item["id"] == attestation["attestation_id"]
        and item["issuer_sovereign_id"] == "sovereign-b"
        for item in graph["revoked_trust_material"]
    )

    connectome = client.get("/connectome.json").get_json()
    assert connectome["summary"]["imported_revocation_count"] == 1
    assert connectome["revocation_blast_radius"][0]["id"] == attestation["attestation_id"]
    assert connectome["revocation_blast_radius"][0]["affected_accepting_sovereigns"] == [
        "TEST",
    ]

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    dashboard_body = dashboard.get_data(as_text=True)
    assert "Revocation Feed Freshness" in dashboard_body
    assert feed["feed_id"] in dashboard_body
    assert "fresh" in dashboard_body


def test_stale_sovereign_revocation_feed_import_is_rejected(client, na_service):
    """The same issuer sequence cannot be imported twice."""
    _issue_treaty(client, na_service)
    attestation = _issue_attestation(client).get_json()
    revoke_body = {"reason": "superseded"}
    client.post(
        f"/admin/attestations/{attestation['attestation_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    feed = client.get(
        "/sovereign-revocation-feed?issuer_sovereign_id=sovereign-b"
    ).get_json()
    import_body = {"feed": feed}

    first = client.post(
        "/admin/sovereign-revocation-feeds/import",
        json=import_body,
        headers=admin_headers(client, import_body),
    )
    second = client.post(
        "/admin/sovereign-revocation-feeds/import",
        json=import_body,
        headers=admin_headers(client, import_body),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["reason"] == "stale_sequence"


def test_treaty_issue_requires_operator_signature(client, na_service):
    """Treaty issuance rejects missing operator authentication."""
    resp = client.post(
        "/admin/recognition-treaties",
        json={
            "subject_sovereign_id": "sovereign-b",
            "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        },
    )

    assert resp.status_code == 401
