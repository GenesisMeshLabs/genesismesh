"""The public reference's signed CRL and external treaties (v0.65).

A gateway pins and refreshes the reference like any authority, so it needs a
signed CRL; the reference recognizes sovereigns outside its demo set (the live
`genesis-mesh` NA behind mesh.genesismesh.org) through operator-configured
external treaties that never touch the demo posture.
"""

from datetime import datetime, timedelta, timezone
import json

import pytest

from examples.public_dashboard.app import create_app
from examples.public_dashboard.maintenance import (
    load_external_treaties,
    refresh_crl,
    refresh_external_treaties,
)
from examples.public_dashboard.records import current_issuers, validate_snapshot
from examples.public_dashboard.seed import seed
from examples.public_dashboard.store import read_snapshot, write_snapshot
from genesis_mesh.crypto import generate_keypair, load_private_key, sign_model, verify_model_signature
from genesis_mesh.models.revocation import CertificateRevocationList, RevokedCertificate


@pytest.fixture
def demo(tmp_path):
    root = tmp_path / "demo"
    snapshot = seed(root)
    key = load_private_key(str(root / "keys" / "gm-demo-public-na.key"))
    return root, snapshot, key


def save(root, snapshot, key):
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    write_snapshot(root / "public.db", snapshot)


def external(subject="genesis-mesh", days=30):
    return {"subject_sovereign_id": subject, "subject_public_key": generate_keypair().public_key_b64,
            "validity_days": days}


def test_snapshots_signed_before_v065_still_verify(demo):
    root, snapshot, _ = demo
    body = snapshot.model_dump(mode="json", exclude={"signatures", "crl", "external_treaties"})
    assert snapshot.to_canonical_json() == json.dumps(body, sort_keys=True, separators=(",", ":"))
    read_snapshot(root / "public.db", snapshot.genesis.root_public_key)


def test_crl_is_signed_served_and_refreshed_only_when_expiring(demo):
    root, snapshot, key = demo
    now = datetime.now(timezone.utc)
    refresh_crl(snapshot, key, now)
    first = snapshot.crl
    assert first.sequence == 0 and first.issuer == "demo-na" and not first.revoked_certificates
    assert verify_model_signature(first, first.signatures[0], snapshot.genesis.network_authority.public_key)
    refresh_crl(snapshot, key, now + timedelta(hours=11))
    assert snapshot.crl is first
    refresh_crl(snapshot, key, now + timedelta(hours=13))
    assert snapshot.crl.sequence == 1
    save(root, snapshot, key)

    served = create_app(root, "abcdef1").test_client().get("/crl")
    assert served.status_code == 200
    assert CertificateRevocationList.model_validate(served.get_json()).sequence == 1


def test_crl_is_absent_until_maintenance_signs_one(demo):
    root, _, _ = demo
    assert create_app(root, "abcdef1").test_client().get("/crl").status_code == 404


def test_tampered_or_non_empty_crl_fails_closed(demo):
    root, snapshot, key = demo
    refresh_crl(snapshot, key, datetime.now(timezone.utc))
    snapshot.crl = snapshot.crl.model_copy(update={"sequence": 7})
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    with pytest.raises(ValueError, match="invalid_crl_signature"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)

    crl = CertificateRevocationList.create_empty(issuer="demo-na", sequence=0)
    crl.revoked_certificates.append(RevokedCertificate(
        certificate_id="c", revoked_at=datetime.now(timezone.utc), reason="key_compromise", issuer="demo-na"))
    crl.signatures.append(sign_model(crl, key, "demo-na"))
    snapshot.crl = crl
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    with pytest.raises(ValueError, match="unexpected_crl"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)


def test_external_treaty_is_issued_listed_graphed_and_kept_out_of_demo_posture(demo):
    root, snapshot, key = demo
    entry = external()
    (root / "external-treaties.json").write_text(json.dumps([entry]))
    issuers_before = current_issuers(snapshot)
    refresh_external_treaties(snapshot, load_external_treaties(root / "external-treaties.json"), key,
                              datetime.now(timezone.utc))
    treaty = snapshot.external_treaties[0].treaty
    assert treaty.subject_sovereign_id == "genesis-mesh"
    assert treaty.subject_public_keys == [entry["subject_public_key"]]
    assert treaty.scope.allowed_roles == ["role:client"]
    assert verify_model_signature(treaty, treaty.signatures[0], snapshot.genesis.network_authority.public_key)
    assert current_issuers(snapshot) == issuers_before
    save(root, snapshot, key)

    client = create_app(root, "abcdef1").test_client()
    listed = client.get("/recognition-treaties").get_json()
    assert [r["treaty"]["treaty_id"] for r in listed["external_treaties"]] == [treaty.treaty_id]
    assert client.get(f"/recognition-treaties/{treaty.treaty_id}").status_code == 200
    graph = client.get("/recognition-graph").get_json()
    assert {"sovereign_id": "genesis-mesh", "external": True} in graph["sovereigns"]
    assert any(e["to"] == "genesis-mesh" and e.get("external") for e in graph["recognition_edges"])


def test_external_treaty_is_renewed_near_expiry_and_dropped_when_unlisted(demo):
    root, snapshot, key = demo
    entry = external(days=10)
    now = datetime.now(timezone.utc)
    refresh_external_treaties(snapshot, [entry], key, now)
    first = snapshot.external_treaties[0].treaty
    refresh_external_treaties(snapshot, [entry], key, now + timedelta(days=1))
    assert snapshot.external_treaties[0].treaty.treaty_id == first.treaty_id
    refresh_external_treaties(snapshot, [entry], key, now + timedelta(days=4))
    assert snapshot.external_treaties[0].treaty.treaty_id != first.treaty_id
    refresh_external_treaties(snapshot, [], key, now)
    assert snapshot.external_treaties == []


@pytest.mark.parametrize("change, reason", [
    ({"subject_sovereign_id": "gm-demo-edge-na"}, "unexpected_external_subject"),
    ({"subject_sovereign_id": "Not Valid"}, "unexpected_external_subject"),
])
def test_external_treaties_cannot_shadow_demo_identities_or_use_odd_names(demo, change, reason):
    root, snapshot, key = demo
    refresh_external_treaties(snapshot, [{**external(), **change}], key, datetime.now(timezone.utc))
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    with pytest.raises(ValueError, match=reason):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)


def test_external_treaty_scope_and_signature_are_enforced(demo):
    root, snapshot, key = demo
    refresh_external_treaties(snapshot, [external()], key, datetime.now(timezone.utc))
    record = snapshot.external_treaties[0]
    record.treaty.scope.allowed_roles = ["role:operator"]
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    with pytest.raises(ValueError, match="unexpected_scope"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)
    record.treaty.scope.allowed_roles = ["role:client"]
    record.treaty.expires_at += timedelta(days=1)
    snapshot.signatures = [sign_model(snapshot, key, "demo-na")]
    with pytest.raises(ValueError, match="invalid_treaty_signature"):
        validate_snapshot(snapshot, snapshot.genesis.root_public_key)


@pytest.mark.parametrize("content", [
    "{}",
    json.dumps([{"subject_sovereign_id": "x", "subject_public_key": "not-a-key", "validity_days": 30}]),
    json.dumps([{**external(), "validity_days": 365}]),
    json.dumps([{**external(), "allowed_roles": ["role:operator"]}]),
])
def test_invalid_external_treaty_configuration_is_refused(tmp_path, content):
    path = tmp_path / "external-treaties.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="external_treaties_invalid"):
        load_external_treaties(path)


def test_missing_external_treaty_configuration_means_none(tmp_path):
    assert load_external_treaties(tmp_path / "absent.json") == []
