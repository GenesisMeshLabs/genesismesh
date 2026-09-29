"""Tests for the v0.57 Network Authority boundary policy routes.

Covers publish / validate / list / active / history / activate / deactivate /
rollback / verify, the policy-aware /admin/boundary/evaluate route, the
legacy-route enforcement switch, policy-set health, operator tiers, audit
events and fail-closed behaviour on tampered storage.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.crypto import generate_keypair, sign_data, sign_model
from genesis_mesh.models import BoundaryPolicy, GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.trust.context import GateRegistry, verify_boundary_decision
from genesis_mesh.trust.justification import verify_justification_proof

from .test_na_trust_api import _make_agreement


def _iso(delta: timedelta = timedelta()) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _headers(keypair, key_id: str, body: dict) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {"body": body, "key_id": key_id, "timestamp": timestamp, "nonce": nonce},
        sort_keys=True, separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(canonical.encode("utf-8"), keypair.private_key),
    }


def _make_service(**kwargs) -> NetworkAuthorityService:
    signing_key = nacl.signing.SigningKey.generate()
    pub = signing_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    privileged = generate_keypair()
    standard = generate_keypair()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=pub,
        network_authority=NetworkAuthority(public_key=pub, valid_from=now, valid_to=now + timedelta(days=90)),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    genesis.signatures.append(sign_model(genesis, signing_key, "root"))
    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=signing_key,
        key_id="test-key",
        operator_public_keys={
            "operator-test": privileged.public_key_b64,
            "operator-std": standard.public_key_b64,
        },
        operator_key_tiers={"operator-test": "privileged", "operator-std": "standard"},
        **kwargs,
    )
    setattr(service, "_test_operator_keypair", privileged)
    setattr(service, "_std_keypair", standard)
    return service


@pytest.fixture
def na_service():
    return _make_service()


@pytest.fixture
def client(na_service):
    na_service.app.config["TESTING"] = True
    c = na_service.app.test_client()
    setattr(c, "operator_keypair", na_service._test_operator_keypair)
    setattr(c, "std_keypair", na_service._std_keypair)
    return c


def _post(client, url: str, body: dict, *, standard: bool = False):
    if standard:
        headers = _headers(client.std_keypair, "operator-std", body)
    else:
        headers = _headers(client.operator_keypair, "operator-test", body)
    return client.post(url, json=body, headers=headers)


def _get(client, url: str):
    return client.get(url, headers=_headers(client.operator_keypair, "operator-test", {}))


def _intent(policy_id: str = "read-limits", max_rows: int = 100, **overrides) -> dict:
    body = {
        "policy_id": policy_id,
        "description": "cap rows returned per read",
        "valid_from": _iso(-timedelta(hours=1)),
        "valid_until": _iso(timedelta(days=7)),
        "selector": {"capabilities": ["read"]},
        "gates": [
            {"gate_id": "row-cap", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.rows", "max": max_rows}},
        ],
    }
    body.update(overrides)
    return body


def _publish(client, **kw) -> dict:
    resp = _post(client, "/admin/boundary-policies", _intent(**kw))
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _activate(client, policy_id: str, version: int):
    return _post(client, f"/admin/boundary-policies/{policy_id}/activate", {"version": version})


def _evaluate(client, na_service, rows: int | None = 10, agreement=None):
    agreement = agreement or _make_agreement(client, na_service)
    params = {} if rows is None else {"rows": rows}
    body = {
        "agreement": agreement,
        "requested_capability": "read",
        "context": {"request_parameters": params},
    }
    return _post(client, "/admin/boundary/evaluate", body)


def _audit_events(na_service) -> list[dict]:
    return na_service.db.list_audit_events()


def _audit_types(na_service) -> list[str]:
    return [e["event_type"] for e in _audit_events(na_service)]


# ── publish / validate ─────────────────────────────────────────────────────


def test_publish_returns_signed_inactive_policy(client, na_service):
    policy = _publish(client)
    assert policy["version"] == 1
    assert policy["signature"]["key_id"] == "test-key"
    assert policy["issuer_sovereign_id"] == "TEST"
    parsed = BoundaryPolicy.model_validate(policy)
    assert parsed.digest() == na_service.db.get_boundary_policy_row("read-limits", 1)["policy_digest"]
    active = _get(client, "/admin/boundary-policies/active").get_json()
    assert active["active"] == []


def test_publish_increments_version(client):
    _publish(client)
    assert _publish(client)["version"] == 2


def test_publish_requires_privileged_tier(client):
    resp = _post(client, "/admin/boundary-policies", _intent(), standard=True)
    assert resp.status_code == 403


def test_publish_rejects_unauthenticated(client):
    assert client.post("/admin/boundary-policies", json=_intent()).status_code == 401


@pytest.mark.parametrize("field", ["signature", "version", "issued_by", "issued_at", "issuer_sovereign_id"])
def test_publish_rejects_na_assigned_fields(client, field):
    resp = _post(client, "/admin/boundary-policies", _intent(**{field: "x"}))
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "unexpected_field"


def test_publish_rejects_unknown_gate_type(client):
    gates = [{"gate_id": "x", "gate_type": "shell.v1", "order": 0, "config": {}}]
    resp = _post(client, "/admin/boundary-policies", _intent(gates=gates))
    assert resp.status_code == 400
    err = resp.get_json()["error"]
    assert err["code"] == "boundary_policy_invalid"
    assert err["details"]["issues"][0]["code"] == "unknown_gate_type"


def test_publish_rejects_malformed_gate(client):
    resp = _post(client, "/admin/boundary-policies", _intent(gates=[{"gate_id": "x"}]))
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_boundary_policy"


def test_validate_reports_issues_without_storing(client, na_service):
    gates = [{"gate_id": "a", "gate_type": "max_value.v1", "order": 0, "config": {"path": "bad root"}}]
    resp = _post(client, "/admin/boundary-policies/validate", _intent(gates=gates), standard=True)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert data["issues"][0]["code"] == "invalid_gate_config"
    assert na_service.db.list_boundary_policy_rows() == []
    assert "boundary_policy_validated" in _audit_types(na_service)


def test_validate_accepts_valid_intent(client):
    data = _post(client, "/admin/boundary-policies/validate", _intent()).get_json()
    assert data["valid"] is True and data["next_version"] == 1


# ── lifecycle ──────────────────────────────────────────────────────────────


def test_activate_and_inspect_active_set(client, na_service):
    _publish(client)
    resp = _activate(client, "read-limits", 1)
    assert resp.status_code == 200
    assert resp.get_json()["previous_version"] is None
    active = _get(client, "/admin/boundary-policies/active").get_json()
    assert active["policy_set_healthy"] is True
    assert active["enforcement"] == "optional"
    assert [(p["policy_id"], p["version"]) for p in active["active"]] == [("read-limits", 1)]
    assert "boundary_policy_activated" in _audit_types(na_service)


def test_activate_requires_privileged_tier(client):
    _publish(client)
    resp = _post(client, "/admin/boundary-policies/read-limits/activate", {"version": 1}, standard=True)
    assert resp.status_code == 403


def test_activate_unknown_version_is_404(client):
    assert _activate(client, "nope", 1).status_code == 404


def test_activate_rejects_bad_version_field(client):
    _publish(client)
    resp = _post(client, "/admin/boundary-policies/read-limits/activate", {"version": True})
    assert resp.status_code == 400


def test_rollback_reactivates_previous_version(client, na_service):
    _publish(client, max_rows=100)
    _publish(client, max_rows=5)
    _activate(client, "read-limits", 2)
    resp = _activate(client, "read-limits", 1)
    assert resp.get_json()["previous_version"] == 2
    active = _get(client, "/admin/boundary-policies/active").get_json()["active"]
    assert [p["version"] for p in active] == [1]
    activations = [e for e in _audit_events(na_service) if e["event_type"] == "boundary_policy_activated"]
    assert activations[-1]["details"]["rollback"] is True
    assert activations[-1]["details"]["previous_version"] == 2


def test_deactivate(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    resp = _post(client, "/admin/boundary-policies/read-limits/deactivate", {"version": 1})
    assert resp.status_code == 200
    assert _get(client, "/admin/boundary-policies/active").get_json()["active"] == []
    again = _post(client, "/admin/boundary-policies/read-limits/deactivate", {"version": 1})
    assert again.status_code == 409
    assert "boundary_policy_deactivated" in _audit_types(na_service)


def test_list_and_history(client):
    _publish(client)
    _publish(client, policy_id="other")
    listed = _get(client, "/admin/boundary-policies").get_json()["policies"]
    assert {(p["policy_id"], p["version"]) for p in listed} == {("read-limits", 1), ("other", 1)}
    _publish(client)
    history = _get(client, "/admin/boundary-policies/read-limits/history").get_json()
    assert [v["version"] for v in history["versions"]] == [2, 1]
    assert history["versions"][0]["policy"]["signature"]


def test_list_rejects_unauthenticated(client):
    assert client.get("/admin/boundary-policies").status_code == 401


# ── public verify ──────────────────────────────────────────────────────────


def test_public_verify_accepts_published_policy(client, na_service):
    policy = _publish(client)
    resp = client.post("/boundary-policies/verify", json={"policy": policy})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is True and data["reason"] == "valid"
    assert "boundary_policy_verified" in _audit_types(na_service)


def test_public_verify_rejects_tampered_policy(client):
    policy = _publish(client)
    policy["gates"][0]["config"]["max"] = 10**9
    data = client.post("/boundary-policies/verify", json={"policy": policy}).get_json()
    assert data["valid"] is False and data["reason"] == "invalid_signature"


def test_public_verify_requires_policy(client):
    assert client.post("/boundary-policies/verify", json={}).status_code == 400


# ── policy-aware evaluation ────────────────────────────────────────────────


def test_evaluate_without_policies_authorizes_and_binds(client, na_service):
    resp = _evaluate(client, na_service)
    assert resp.status_code == 201
    decision = resp.get_json()["decision"]
    assert decision["authorized"] is True
    assert decision["policy_binding"]["policies"] == []


def test_evaluate_applies_active_policy(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    ok = _evaluate(client, na_service, rows=50).get_json()
    denied = _evaluate(client, na_service, rows=500).get_json()
    assert ok["decision"]["authorized"] is True
    assert denied["decision"]["authorized"] is False
    assert denied["decision"]["denial_reason"] == "policy gate 'read-limits/row-cap' failed"
    pub = na_service.na_private_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    decision = BoundaryDecision.model_validate(denied["decision"])
    policy = BoundaryPolicy.model_validate(
        _get(client, "/admin/boundary-policies/active").get_json()["active"][0]["policy"]
    )
    result = verify_boundary_decision(decision, [pub], expected_policies=[policy])
    assert result.accepted is True and result.reason == "unauthorized_policy_gate_failure"
    from genesis_mesh.models.justification import JustificationProof

    proof = JustificationProof.model_validate(denied["justification_proof"])
    assert verify_justification_proof(proof, [pub], decision=decision).valid


def test_evaluate_missing_fact_denies(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    decision = _evaluate(client, na_service, rows=None).get_json()["decision"]
    assert decision["authorized"] is False
    assert decision["policy_binding"]["gate_evaluations"][0]["outcome"] == "missing_context"


def test_evaluate_audit_never_records_values(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    _evaluate(client, na_service, rows=424242)
    dumped = json.dumps(_audit_events(na_service))
    assert "boundary_policy_decision_made" in dumped
    assert "424242" not in dumped


def test_evaluate_malformed_request_is_http_error(client, na_service):
    resp = _post(client, "/admin/boundary/evaluate", {"requested_capability": "read"})
    assert resp.status_code == 400
    resp = _post(client, "/admin/boundary/evaluate", {"agreement": {"x": 1}, "requested_capability": "read"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_agreement"


def test_evaluate_unauthenticated_is_401(client, na_service):
    agreement = _make_agreement(client, na_service)
    resp = client.post("/admin/boundary/evaluate", json={"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 401


def test_evaluate_allowed_for_standard_tier(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"agreement": agreement, "requested_capability": "read"}
    assert _post(client, "/admin/boundary/evaluate", body, standard=True).status_code == 201


# ── fail closed on storage tampering / health ─────────────────────────────


def test_tampered_stored_policy_denies_and_reports_unhealthy(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    row = na_service.db.get_boundary_policy_row("read-limits", 1)
    tampered = json.loads(row["policy_json"])
    tampered["gates"][0]["config"]["max"] = 10**9
    with na_service.db.conn:
        na_service.db.conn.execute(
            "UPDATE boundary_policy_versions SET policy_json = ? WHERE policy_id = ?",
            (json.dumps(tampered), "read-limits"),
        )
    decision = _evaluate(client, na_service, rows=5).get_json()["decision"]
    assert decision["authorized"] is False
    assert decision["policy_binding"]["resolution_failure"] == "policy_store_integrity_failed"
    active = _get(client, "/admin/boundary-policies/active").get_json()
    assert active["policy_set_healthy"] is False
    assert active["problems"][0]["reason"] == "policy_store_integrity_failed"
    assert client.get("/health").get_json()["boundary_policies"] == "unhealthy"


def test_tampered_version_cannot_be_activated(client, na_service):
    _publish(client)
    with na_service.db.conn:
        na_service.db.conn.execute(
            "UPDATE boundary_policy_versions SET policy_digest = 'x' WHERE policy_id = ?", ("read-limits",)
        )
    resp = _activate(client, "read-limits", 1)
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "boundary_policy_integrity_failed"


def test_health_reports_healthy_by_default(client):
    data = client.get("/health").get_json()
    assert data["boundary_policies"] == "healthy"
    assert data["boundary_policy_enforcement"] == "optional"


def test_store_rejects_two_active_versions(na_service, client):
    _publish(client)
    _publish(client)
    _activate(client, "read-limits", 1)
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        with na_service.db.conn:
            na_service.db.conn.execute(
                "UPDATE boundary_policy_versions SET active = 1 WHERE policy_id = ? AND version = 2",
                ("read-limits",),
            )


# ── legacy route enforcement ───────────────────────────────────────────────


def test_legacy_decide_unchanged_when_optional(client, na_service):
    agreement = _make_agreement(client, na_service)
    resp = _post(client, "/admin/boundary/decide", {"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 201
    assert "policy_binding" not in resp.get_json()


def test_legacy_decide_refused_when_enforcement_required():
    service = _make_service(boundary_policy_enforcement="required")
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", service._test_operator_keypair)
    setattr(c, "std_keypair", service._std_keypair)
    agreement = _make_agreement(c, service)
    resp = _post(c, "/admin/boundary/decide", {"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "boundary_policy_required"
    assert "boundary_legacy_decide_refused" in _audit_types(service)
    assert _evaluate(c, service, agreement=agreement).status_code == 201
    assert _get(c, "/admin/boundary-policies/active").get_json()["enforcement"] == "required"


def test_service_rejects_unknown_enforcement_mode():
    with pytest.raises(ValueError):
        _make_service(boundary_policy_enforcement="sometimes")


def test_service_rejects_unfrozen_registry():
    with pytest.raises(ValueError):
        _make_service(gate_registry=GateRegistry.builtin())


# ── operator console ───────────────────────────────────────────────────────


def test_dashboard_shows_empty_boundary_policy_state(client):
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Boundary Policies" in html
    assert "No active boundary policies." in html


def test_dashboard_lists_active_policy_without_thresholds(client):
    _publish(client, max_rows=31337)
    _activate(client, "read-limits", 1)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "read-limits" in html
    assert "31337" not in html
    summary = client.get("/dashboard.json").get_json()["boundary_policies"]
    assert summary["status"] == "healthy"
    assert summary["active"][0]["scope"] == "selected"
    assert "31337" not in json.dumps(summary)


def test_dashboard_warns_when_policy_set_unhealthy(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    with na_service.db.conn:
        na_service.db.conn.execute("UPDATE boundary_policy_versions SET policy_digest = 'x'")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Boundary policy set unhealthy" in html


def test_dashboard_recent_changes_exclude_evaluations(client, na_service):
    _publish(client)
    _activate(client, "read-limits", 1)
    _evaluate(client, na_service)
    changes = client.get("/dashboard.json").get_json()["recent_changes"]
    types = [c["event_type"] for c in changes]
    assert "boundary_policy_activated" in types
    assert "boundary_policy_decision_made" not in types
