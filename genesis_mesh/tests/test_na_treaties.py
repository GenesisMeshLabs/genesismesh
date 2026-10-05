"""Tests for Network Authority recognition treaty routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from .na_server_helpers import admin_headers, make_client, make_na_service


@pytest.fixture
def sovereign_b():
    """A second, independent sovereign (its own NA, keys and database)."""
    service = make_na_service("sovereign-b")
    return service, make_client(service)


def _issue_treaty(client, na_service, allowed_roles=None, subject_public_keys=None):
    """Issue an operator-authorized recognition treaty for sovereign-b."""
    body = {
        "subject_sovereign_id": "sovereign-b",
        "subject_public_keys": subject_public_keys
        or [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": allowed_roles or ["role:client"]},
        "validity_hours": 24,
    }
    return client.post(
        "/admin/recognition-treaties",
        json=body,
        headers=admin_headers(client, body),
    )


def _recognize_b(client, na_service, sovereign_b, allowed_roles=None):
    """TEST recognizes sovereign-b, pinning sovereign-b's NA key."""
    b_service, _ = sovereign_b
    return _issue_treaty(
        client, na_service, allowed_roles,
        subject_public_keys=[b_service.genesis_block.network_authority.public_key],
    )


def _issue_attestation(client, subject_id: str = "alice", roles=None):
    """Issue an operator-authorized membership attestation at ``client``'s NA."""
    body = {
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


def test_attestation_verify_with_treaty_accepts_scoped_role(client, na_service, sovereign_b):
    """A treaty can back acceptance of a subject sovereign's attestation."""
    treaty = _recognize_b(client, na_service, sovereign_b).get_json()
    attestation = _issue_attestation(sovereign_b[1]).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_verify_with_treaty_rejects_role_outside_scope(client, na_service, sovereign_b):
    """Treaty role scope limits which attestations are accepted."""
    treaty = _recognize_b(client, na_service, sovereign_b, allowed_roles=["role:anchor"]).get_json()
    attestation = _issue_attestation(sovereign_b[1], roles=["role:client"]).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "attestation_role_not_allowed"


def test_revoking_treaty_changes_treaty_backed_verification(client, na_service, sovereign_b):
    """A revoked treaty cannot continue backing attestation verification."""
    treaty = _recognize_b(client, na_service, sovereign_b).get_json()
    attestation = _issue_attestation(sovereign_b[1]).get_json()

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
    assert "Surfaces" in body
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
    assert resp.get_json()["error"]["message"] == "from/source and to/target are required"


def test_imported_revocation_feed_blocks_treaty_backed_attestation(client, na_service, sovereign_b):
    """A propagated issuer revocation stops treaty-backed attestation acceptance."""
    b_client = sovereign_b[1]
    treaty = _recognize_b(client, na_service, sovereign_b).get_json()
    attestation = _issue_attestation(b_client).get_json()

    accepted = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["accepted"] is True

    revoke_body = {"reason": "key_compromise"}
    revoke = b_client.post(
        f"/admin/attestations/{attestation['attestation_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(b_client, revoke_body),
    )
    assert revoke.status_code == 200

    # sovereign-b publishes its own signed feed; TEST imports it under its treaty pin.
    feed_resp = b_client.get("/sovereign-revocation-feed")
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


def test_stale_sovereign_revocation_feed_import_is_rejected(client, na_service, sovereign_b):
    """The same issuer sequence cannot be imported twice."""
    b_client = sovereign_b[1]
    _recognize_b(client, na_service, sovereign_b)
    attestation = _issue_attestation(b_client).get_json()
    revoke_body = {"reason": "superseded"}
    b_client.post(
        f"/admin/attestations/{attestation['attestation_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(b_client, revoke_body),
    )
    feed = b_client.get("/sovereign-revocation-feed").get_json()
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
    assert second.get_json()["error"]["code"] == "stale_sequence"


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


def test_connectome_graph_scales_without_overlapping_nodes():
    """Nodes must stay apart as the graph grows; labels sit outside the ring."""
    import math
    import re

    from genesis_mesh.na_service.operator_console.connectome import (
        MAX_GRAPH_NODES,
        NODE_RADIUS,
        _connectome_graph,
    )

    def graph(count):
        names = [f"gm-sovereign-{i:02d}-na" for i in range(count)]
        return _connectome_graph({
            "sovereigns": [{"sovereign_id": name} for name in names],
            "recognition_edges": [
                {"from": names[0], "to": name, "status": "active", "lifecycle_state": "active"}
                for name in names[1:]
            ],
        })

    for count in (3, 10, 25, MAX_GRAPH_NODES):
        markup = graph(count)
        points = [
            (float(x), float(y))
            for x, y in re.findall(r'cx="([-\d.]+)" cy="([-\d.]+)"', markup)
        ]
        assert len(points) == count
        closest = min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:])
        assert closest > 2 * NODE_RADIUS, f"nodes overlap at {count} sovereigns"
        width, height = (float(v) for v in re.search(r'viewBox="0 0 (\d+) (\d+)"', markup).groups())
        assert all(0 <= x <= width and 0 <= y <= height for x, y in points)

    # Beyond the cap the ring stops growing and the page says so.
    oversized = graph(MAX_GRAPH_NODES + 20)
    assert oversized.count("<circle") == MAX_GRAPH_NODES
    assert f"Showing {MAX_GRAPH_NODES} of {MAX_GRAPH_NODES + 20} sovereigns" in oversized

    # A long id is trimmed for display but kept in full in a title.
    long_name = "gm-demo-" + "x" * 40 + "-na"
    trimmed = _connectome_graph({"sovereigns": [{"sovereign_id": long_name}], "recognition_edges": []})
    assert f"<title>{long_name}</title>" in trimmed
    assert "…" in trimmed


def test_connectome_uses_a_hub_layout_only_when_one_authority_issues_everything():
    """An authority's own graph is a star; draw the issuer as a hub, not on the rim."""
    import re

    from genesis_mesh.na_service.operator_console.connectome import _connectome_graph

    def graph(names, edges):
        return _connectome_graph({
            "sovereigns": [{"sovereign_id": n} for n in names],
            "recognition_edges": [
                {"from": f, "to": t, "status": "active", "lifecycle_state": "active"}
                for f, t in edges
            ],
        })

    names = [f"gm-sovereign-{i:02d}-na" for i in range(6)]

    # Single issuer: the hub is centred and visually distinct.
    star = graph(names, [(names[0], n) for n in names[1:]])
    assert "graph-node-hub" in star
    width, height = (float(v) for v in re.search(r'viewBox="0 0 (\d+) (\d+)"', star).groups())
    centre = [
        (x, y)
        for x, y in ((float(a), float(b)) for a, b in re.findall(r'cx="([-\d.]+)" cy="([-\d.]+)"', star))
        if abs(x - width / 2) < 1 and abs(y - height / 2) < 1
    ]
    assert len(centre) == 1, "the issuing authority should sit at the centre"

    # More than one issuer is a genuine mesh: fall back to the ring.
    mesh = graph(names, [(names[0], names[1]), (names[2], names[3]), (names[0], names[4])])
    assert "graph-node-hub" not in mesh

    # Two nodes need no hub; direction is already unambiguous.
    pair = graph(names[:2], [(names[0], names[1])])
    assert "graph-node-hub" not in pair


def test_a_feed_for_another_sovereign_is_refused(client):
    """An NA signs only its own revocation feed (v1.0.2)."""
    resp = client.get("/sovereign-revocation-feed?issuer_sovereign_id=sovereign-b")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "feed_issuer_mismatch"
    assert client.get("/sovereign-revocation-feed?issuer_sovereign_id=TEST").status_code == 200


def test_an_attestation_naming_another_issuer_is_refused(client):
    """An NA never signs an attestation in another sovereign's name (v1.0.2)."""
    body = {"issuer_sovereign_id": "sovereign-b", "subject_id": "alice", "roles": ["role:client"]}
    resp = client.post("/admin/attestations", json=body, headers=admin_headers(client, body))
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "attestation_issuer_mismatch"


def _forged_treaty_and_attestation():
    """A treaty and attestation that claim TEST as issuer, signed by a random key."""
    from genesis_mesh.crypto import generate_keypair, sign_model
    from genesis_mesh.models import MembershipAttestation, RecognitionTreaty, RecognitionTreatyScope

    forger = generate_keypair()
    now = datetime.now(timezone.utc)
    treaty = RecognitionTreaty(
        treaty_id="00000000-0000-4000-8000-00000000f0f0",
        issuer_sovereign_id="TEST",
        subject_sovereign_id="sovereign-x",
        subject_public_keys=[forger.public_key_b64],
        scope=RecognitionTreatyScope(allowed_roles=["role:client"]),
        status="active",
        issued_at=now,
        valid_from=now,
        expires_at=now + timedelta(hours=1),
        issued_by=forger.public_key_b64,
        signatures=[],
    )
    treaty.signatures.append(sign_model(treaty, forger.private_key, "forger"))
    attestation = MembershipAttestation(
        attestation_id="00000000-0000-4000-8000-00000000a0a0",
        issuer_sovereign_id="sovereign-x",
        subject_id="mallory",
        roles=["role:client"],
        status="active",
        issued_at=now,
        valid_from=now,
        expires_at=now + timedelta(hours=1),
        issued_by="forger",
        signatures=[],
    )
    attestation.signatures.append(sign_model(attestation, forger.private_key, "forger"))
    return forger, treaty.model_dump(mode="json"), attestation.model_dump(mode="json")


def test_a_forged_treaty_naming_this_authority_is_never_accepted(client):
    """Caller keys cannot make this NA vouch for a treaty it never issued (v1.0.2)."""
    forger, treaty, attestation = _forged_treaty_and_attestation()

    with_keys = client.post("/attestations/verify-with-treaty", json={
        "attestation": attestation, "treaty": treaty,
        "treaty_issuer_public_keys": [forger.public_key_b64],
    })
    assert with_keys.status_code == 422
    assert with_keys.get_json()["error"]["code"] == "caller_keys_not_accepted"

    without_keys = client.post("/attestations/verify-with-treaty", json={
        "attestation": attestation, "treaty": treaty,
    })
    assert without_keys.status_code == 200
    assert without_keys.get_json()["accepted"] is False
    assert without_keys.get_json()["reason"] == "treaty_not_held"

    verify = client.post("/recognition-treaties/verify", json={
        "treaty": treaty, "issuer_public_keys": [forger.public_key_b64],
    })
    assert verify.status_code == 422
    assert verify.get_json()["error"]["code"] == "caller_keys_not_accepted"


def test_a_tampered_copy_of_a_held_treaty_is_not_held(client, na_service):
    treaty = _issue_treaty(client, na_service).get_json()
    tampered = {**treaty, "scope": {**treaty["scope"], "allowed_roles": ["role:operator"]}}
    resp = client.post("/recognition-treaties/verify", json={"treaty": tampered})
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "not_held"
    held = client.post("/recognition-treaties/verify", json={"treaty": treaty}).get_json()
    assert held["accepted"] is True and held["trust_basis"] == "this_authority"


def test_another_sovereigns_treaty_uses_pinned_or_supplied_keys(client, na_service, sovereign_b):
    """A treaty issued by sovereign-b verifies here against keys TEST pinned for it."""
    b_service, b_client = sovereign_b
    reverse = {
        "subject_sovereign_id": "TEST",
        "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": ["role:client"]},
        "validity_hours": 24,
    }
    b_treaty = b_client.post(
        "/admin/recognition-treaties", json=reverse, headers=admin_headers(b_client, reverse),
    ).get_json()

    unknown = client.post("/recognition-treaties/verify", json={"treaty": b_treaty}).get_json()
    assert unknown == {**unknown, "accepted": False, "reason": "issuer_not_recognized"}

    _recognize_b(client, na_service, sovereign_b)
    pinned = client.post("/recognition-treaties/verify", json={"treaty": b_treaty}).get_json()
    assert pinned["accepted"] is True and pinned["trust_basis"] == "recognized_issuer_keys"

    b_key = b_service.genesis_block.network_authority.public_key
    supplied = client.post("/recognition-treaties/verify", json={
        "treaty": b_treaty, "issuer_public_keys": [b_key],
    }).get_json()
    assert supplied["accepted"] is True and supplied["trust_basis"] == "caller_supplied_keys"


def _store_expired_treaty(na_service, subject_sovereign_id, subject_public_key):
    """An active, unrevoked treaty whose validity window has passed."""
    import uuid

    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models import RecognitionTreaty, RecognitionTreatyScope

    now = datetime.now(timezone.utc)
    treaty = RecognitionTreaty(
        treaty_id=str(uuid.uuid4()),
        issuer_sovereign_id=na_service.genesis_block.network_name,
        subject_sovereign_id=subject_sovereign_id,
        subject_public_keys=[subject_public_key],
        scope=RecognitionTreatyScope(allowed_roles=["role:client"]),
        status="active",
        issued_at=now - timedelta(hours=3),
        valid_from=now - timedelta(hours=3),
        expires_at=now - timedelta(hours=2),
        issued_by=na_service.signer.key_id,
    )
    treaty.signatures.append(na_service.signer.sign_model(treaty))
    na_service.db.save_recognition_treaty(treaty)
    return treaty


def test_an_expired_treaty_no_longer_pins_keys(client, na_service, sovereign_b):
    """Keys of an expired (but unrevoked) treaty are not recognized issuer keys (v1.0.2)."""
    b_service, b_client = sovereign_b
    b_key = b_service.genesis_block.network_authority.public_key
    _store_expired_treaty(na_service, "sovereign-b", b_key)
    reverse = {
        "subject_sovereign_id": "TEST",
        "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": ["role:client"]},
        "validity_hours": 24,
    }
    b_treaty = b_client.post(
        "/admin/recognition-treaties", json=reverse, headers=admin_headers(b_client, reverse),
    ).get_json()

    answer = client.post("/recognition-treaties/verify", json={"treaty": b_treaty}).get_json()
    assert answer["accepted"] is False
    assert answer["reason"] == "issuer_not_recognized"

    feed = b_client.get("/sovereign-revocation-feed").get_json()
    import_body = {"feed": feed}
    refused = client.post(
        "/admin/sovereign-revocation-feeds/import", json=import_body,
        headers=admin_headers(client, import_body),
    )
    assert refused.status_code == 400
    assert refused.get_json()["error"]["code"] == "missing_issuer_public_keys"


def test_a_feed_from_a_recognized_issuer_verifies_only_against_pinned_keys(client, na_service, sovereign_b):
    """Caller keys cannot replace the keys this NA's treaty pinned (v1.0.2)."""
    import base64

    import nacl.signing

    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models import SovereignRevocationFeed

    b_service, b_client = sovereign_b
    _recognize_b(client, na_service, sovereign_b)
    attacker = nacl.signing.SigningKey.generate()
    attacker_pub = base64.b64encode(bytes(attacker.verify_key)).decode()
    feed = SovereignRevocationFeed.model_validate(b_client.get("/sovereign-revocation-feed").get_json())
    forged = feed.model_copy(update={"signatures": [], "revoked_attestation_ids": ["victim"]})
    forged.signatures.append(sign_model(forged, attacker, "attacker"))
    import_body = {"feed": forged.model_dump(mode="json"), "issuer_public_keys": [attacker_pub]}

    refused = client.post(
        "/admin/sovereign-revocation-feeds/import", json=import_body,
        headers=admin_headers(client, import_body),
    )
    assert refused.status_code == 422
    assert refused.get_json()["error"]["code"] == "caller_keys_not_accepted"

    genuine = {"feed": feed.model_dump(mode="json")}
    imported = client.post(
        "/admin/sovereign-revocation-feeds/import", json=genuine,
        headers=admin_headers(client, genuine),
    )
    assert imported.status_code == 200
    assert imported.get_json()["accepted"] is True
    events = [e for e in na_service.db.list_audit_events() if e["event_type"] == "sovereign_revocation_feed_imported"]
    assert events[-1]["details"]["trust_basis"] == "recognized_issuer_keys"


def test_a_feed_from_an_unrecognized_issuer_uses_supplied_keys(client, na_service, sovereign_b):
    """Without a treaty, a feed verifies against keys the operator supplies, labelled as such."""
    b_service, b_client = sovereign_b
    b_key = b_service.genesis_block.network_authority.public_key
    feed = b_client.get("/sovereign-revocation-feed").get_json()
    import_body = {"feed": feed, "issuer_public_keys": [b_key]}
    imported = client.post(
        "/admin/sovereign-revocation-feeds/import", json=import_body,
        headers=admin_headers(client, import_body),
    )
    assert imported.status_code == 200
    events = [e for e in na_service.db.list_audit_events() if e["event_type"] == "sovereign_revocation_feed_imported"]
    assert events[-1]["details"]["trust_basis"] == "caller_supplied_keys"

