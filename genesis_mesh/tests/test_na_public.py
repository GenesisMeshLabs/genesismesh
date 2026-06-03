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
    assert "Console" in body
    assert "API Docs" in body
    assert "CLI Docs" in body
    assert "Operator Docs" in body
    assert '/operator-console-static/logo.svg' in body
    assert "/healthz" in body
    assert "/readyz" in body
    assert "/sovereign.json" in body
    assert "/api-reference" in body
    assert "/cli-reference" in body
    assert "All surfaces" in body
    assert "Safe GET" in body
    assert "Signed" in body
    assert "CLI" in body
    assert 'data-surface-filter="safe"' in body
    assert 'data-surface-section="signed"' in body
    assert 'data-back-to-top' in body
    assert "Quick Links" not in body
    assert "Safe Browser Links" in body
    assert "Representative safe GET surfaces" in body
    assert "View all API routes" in body
    assert "View all CLI commands" in body
    assert "/connectome" in body
    assert "Node and Agent Runtime" in body
    assert "/agents" in body
    assert "/admin/invite" in body
    assert "/admin/recognition-treaties" in body
    assert "/admin/sovereign-revocation-feeds/import" in body
    assert "Managed Operations" in body
    assert "genesis-mesh managed backup" in body
    assert "genesis-mesh managed restore" in body
    assert "genesis-mesh managed audit-export" in body
    assert 'href="/favicon.svg"' in body
    assert 'href="/operator-console-static/styles.css"' in body
    assert 'src="/operator-console-static/console.js"' in body
    assert "theme-icon-dark" in body
    assert "theme-icon-light" in body
    assert 'href="genesis-mesh managed backup"' not in body
    assert 'class="shell operator-console"' in body


def test_operator_console_static_assets_are_served(client):
    """The packaged operator-console assets should be reachable in browsers."""
    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.mimetype == "image/svg+xml"
    assert b"<svg" in favicon.data

    fallback = client.get("/favicon.ico")
    assert fallback.status_code == 200
    assert fallback.mimetype == "image/x-icon"

    logo = client.get("/operator-console-static/logo.svg")
    assert logo.status_code == 200
    assert logo.mimetype == "image/svg+xml"
    assert b"<svg" in logo.data

    styles = client.get("/operator-console-static/styles.css")
    assert styles.status_code == 200
    assert styles.mimetype == "text/css"
    assert b'data-theme="light"' in styles.data
    assert b"filter: invert(1)" in styles.data

    script = client.get("/operator-console-static/console.js")
    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    assert b"data-search-input" in script.data
    assert b"data-theme-toggle" in script.data
    assert b"data-surface-filter" in script.data
    assert b"data-back-to-top" in script.data


def test_swagger_json_exposes_generated_api_metadata(client):
    """The generated OpenAPI metadata should cover key HTTP surfaces."""
    resp = client.get("/swagger.json", base_url="https://na.example.test")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["openapi"] == "3.0.3"
    assert payload["servers"] == [{"url": "https://na.example.test"}]
    assert payload["paths"]["/healthz"]["get"]["summary"] == "Liveness"
    assert payload["paths"]["/admin/invite"]["post"]["x-genesis-mesh-access"] == "operator_signed"
    assert payload["paths"]["/join"]["post"]["x-genesis-mesh-auth-hint"] == "Node PoP"
    assert "try-it" in payload["x-genesis-mesh-note"]


def test_api_reference_is_read_only_and_links_swagger(client):
    """The API reference should enumerate routes without request execution UI."""
    resp = client.get("/api-reference")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    body = resp.get_data(as_text=True)
    assert "Network Authority API" in body
    assert "/swagger.json" in body
    assert "/admin/invite" in body
    assert "Search API routes" in body
    assert "data-search-input" in body
    assert "no try-it or request execution controls" in body
    assert "Try it" not in body


def test_cli_reference_is_generated_from_click_tree(client):
    """The CLI reference should expose command groups and managed commands."""
    resp = client.get("/cli-reference")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    body = resp.get_data(as_text=True)
    assert "Genesis Mesh CLI" in body
    assert "genesis-mesh managed backup" in body
    assert "genesis-mesh managed restore" in body
    assert "genesis-mesh supply-chain verify" in body
    assert "Search CLI commands" in body
    assert "data-search-input" in body
    assert 'data-search-target="tbody tr"' in body
    assert body.index("Managed Operations") > body.index('id="cli-reference-results"')
    assert "Command Reference" in body
    assert "cli-reference-table" in body
    assert "command-card-grid" not in body
    assert "command-card" not in body
    managed_section = body[body.index("Managed Operations"):body.index("genesis-mesh admin")]
    assert "<th>Method</th>" not in managed_section
    assert "method-cli" not in managed_section
    assert "Command and option reference generated from the Click command" in body
    assert "No options" not in body


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
