"""Privacy, replay, status and read-only regression tests for the reference overlay."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest

from examples.public_dashboard.app import create_app
from examples.public_dashboard.records import ImportEvent, freshness, import_feed, sensitive_authorization_allowed, validate_snapshot
from examples.public_dashboard.seed import seed
from examples.public_dashboard.store import read_snapshot, write_snapshot
from examples.public_dashboard.view import dashboard
from genesis_mesh.crypto import load_private_key, sign_model


@pytest.fixture
def demo(tmp_path):
    root = tmp_path / "demo"
    snapshot = seed(root)
    return root, snapshot


def resign(snapshot, root):
    snapshot.signatures = []
    snapshot.signatures.append(sign_model(snapshot, load_private_key(str(root / "keys" / "gm-demo-public-na.key")), "demo-na"))


def test_public_routes_expose_only_clean_signed_data_and_are_read_only(demo):
    root, snapshot = demo
    app = create_app(root, "abcdef1")
    client = app.test_client()
    paths = ["/", "/dashboard", "/dashboard.json", "/connectome", "/connectome.json", "/atlas", "/atlas.json",
             "/recognition-graph", "/recognition-treaties", "/genesis", "/sovereign.json", "/evidence.json", "/readyz"]
    original = (root / "public.db").read_bytes()
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        text = response.get_data(as_text=True)
        for forbidden in ["USG", "Rayen", "AMINE", "MiraOS", "ONS-A", "db_path", str(root), "private_key", "token"]:
            assert forbidden not in text, (path, forbidden)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
        assert response.headers["Strict-Transport-Security"]
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            assert client.open(path, method=method).status_code == 405
    assert (root / "public.db").read_bytes() == original
    assert client.get("/admin/invite").status_code == 404
    assert client.get("/operator-console-static/../../keys/na.key").status_code == 404
    assert client.get("/dashboard.json").json["software"]["build"] == "abcdef1"
    assert client.get("/dashboard.json").json["connectome_summary"]["sovereign_count"] == 10
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Network protocol:" not in html
    assert "v0.1" not in html
    assert "Genesis Mesh: v" in html


@pytest.mark.parametrize("hours,expected", [(23.999, "fresh"), (24, "warning"), (72, "warning"), (72.001, "stale")])
def test_exact_feed_age_boundaries(hours, expected):
    now = datetime.now(timezone.utc)
    assert freshness(now - timedelta(hours=hours), now) == expected


def test_expected_expiry_degrades_but_history_does_not(demo):
    _, snapshot = demo
    now = datetime.now(timezone.utc)
    t = snapshot.treaties[0]
    t.treaty.issued_at = t.treaty.valid_from = now - timedelta(days=2)
    t.treaty.expires_at = now - timedelta(days=1)
    model = dashboard(snapshot, {}, {"version": "0.56.0"}, now)
    assert model["trust_posture"] == "degraded"
    assert "expired" in " ".join(model["warnings"])
    t.retired = True
    model = dashboard(snapshot, {}, {"version": "0.56.0"}, now)
    assert model["trust_posture"] == "healthy"
    assert model["treaty_summary"]["historical"] == 1
    assert not model["warnings"]


def test_missing_or_stale_feed_denies_sensitive_authorization(demo):
    _, snapshot = demo
    now = datetime.now(timezone.utc)
    issuer = "gm-demo-edge-na"
    assert sensitive_authorization_allowed(snapshot, issuer, now)
    snapshot.feeds[issuer].issued_at = now - timedelta(hours=73)
    assert not sensitive_authorization_allowed(snapshot, issuer, now)
    assert dashboard(snapshot, {}, {"version": "0.56.0"}, now)["trust_posture"] == "degraded"
    del snapshot.feeds[issuer]
    assert not sensitive_authorization_allowed(snapshot, issuer, now)


def test_signed_heartbeat_keeps_sequence_and_replay_does_not_refresh(demo):
    root, snapshot = demo
    issuer = "gm-demo-edge-na"
    old = snapshot.feeds[issuer]
    heartbeat = old.model_copy(deep=True)
    heartbeat.feed_id = str(uuid.uuid4())
    heartbeat.issued_at += timedelta(seconds=1)
    heartbeat.signatures = []
    key = load_private_key(str(root / "keys" / (issuer + ".key")))
    heartbeat.signatures.append(sign_model(heartbeat, key, "demo-na"))
    now = heartbeat.issued_at
    import_feed(snapshot, heartbeat, now)
    assert snapshot.feeds[issuer].sequence == old.sequence
    with pytest.raises(ValueError, match="replayed_feed"):
        import_feed(snapshot, heartbeat, now + timedelta(hours=1))
    assert snapshot.imports[issuer] == now
    heartbeat.issued_at += timedelta(seconds=1)
    heartbeat.revoked_attestation_ids.append(str(uuid.uuid4()))
    heartbeat.signatures = []
    heartbeat.signatures.append(sign_model(heartbeat, key, "demo-na"))
    with pytest.raises(ValueError, match="sequence_content_mismatch"):
        import_feed(snapshot, heartbeat, heartbeat.issued_at)


def test_tampered_signed_record_and_arbitrary_metadata_fail_closed(demo):
    root, snapshot = demo
    snapshot.treaties[0].treaty.metadata = {"name": "private person"}
    resign(snapshot, root)
    with pytest.raises(ValueError, match="unexpected_treaty_metadata"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)
    snapshot.treaties[0].treaty.metadata = {}
    snapshot.treaties[0].expected_active = False
    with pytest.raises(ValueError, match="invalid_snapshot_signature"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)


def test_pagination_search_sort_and_load_more(demo):
    root, snapshot = demo
    key = load_private_key(str(root / "keys" / "gm-demo-public-na.key"))
    for i in range(55):
        record = snapshot.treaties[0].model_copy(deep=True)
        record.treaty.treaty_id = str(uuid.uuid4())
        record.treaty.signatures = []
        record.treaty.signatures.append(sign_model(record.treaty, key, "demo-na"))
        snapshot.treaties.append(record)
    snapshot.events = [ImportEvent(at=datetime.now(timezone.utc), issuer="gm-demo-edge-na", outcome="success") for _ in range(50)]
    resign(snapshot, root)
    write_snapshot(root / "public.db", snapshot)
    client = create_app(root).test_client()
    first = client.get("/dashboard.json").json
    second = client.get("/dashboard.json?page=2").json
    assert first["pagination"]["total"] == 64
    assert len(first["treaties"]) == len(second["treaties"]) == 25
    assert {t['treaty_id'] for t in first['treaties']}.isdisjoint({t['treaty_id'] for t in second['treaties']})
    assert len(client.get("/dashboard.json?page_size=50").json["treaties"]) == 50
    record_id = first["treaties"][0]["treaty_id"]
    assert client.get("/dashboard.json?q=" + record_id).json["pagination"]["total"] == 1
    assert client.get("/dashboard.json?status=historical").json["pagination"]["total"] == 0
    assert client.get("/dashboard.json?page_size=500").status_code == 400
    assert client.get("/dashboard.json?events=999999").status_code == 400
    assert len(client.get("/dashboard.json?events=33").json["recent_changes"]) == 33
    assert "Load more" in client.get("/dashboard").get_data(as_text=True)


def test_rate_limit_and_safe_errors(demo):
    root, _ = demo
    client = create_app(root).test_client()
    for _ in range(120):
        assert client.get("/healthz").status_code == 200
    response = client.get("/healthz")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "Traceback" not in response.get_data(as_text=True)


def test_unsigned_snapshot_cannot_change_expected_relationships(demo):
    root, snapshot = demo
    snapshot.treaties[0].expected_active = False
    with pytest.raises(ValueError):
        write_snapshot(root / "public.db", snapshot)
    stored = read_snapshot(root / "public.db", snapshot.genesis.root_public_key)
    assert stored.treaties[0].expected_active
