"""Integration test: declarative boundary policy lifecycle across an NA restart (v0.57).

A privileged operator publishes two versions of a policy on a file-backed
Network Authority, activates the strict one, and the policy-aware route
denies an over-limit request.  The NA restarts on the same database: the
active policy still enforces.  The operator rolls back to the lenient
version and the same request is authorised.  An auditor holding only the NA
public key and the signed policy versions verifies every decision and
justification proof offline, and can tell which policy version produced each.
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
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.trust.context import verify_boundary_decision, verify_boundary_policy
from genesis_mesh.trust.justification import verify_justification_proof

pytestmark = pytest.mark.integration


def _headers(keypair, body: dict) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {"body": body, "key_id": "ops", "timestamp": ts, "nonce": nonce},
        sort_keys=True, separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": "ops",
        "X-Admin-Timestamp": ts,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(canonical.encode("utf-8"), keypair.private_key),
    }


class _Operator:
    def __init__(self, service: NetworkAuthorityService, keypair) -> None:
        service.app.config["TESTING"] = True
        self.client = service.app.test_client()
        self.keypair = keypair

    def post(self, url: str, body: dict):
        return self.client.post(url, json=body, headers=_headers(self.keypair, body))

    def get(self, url: str):
        return self.client.get(url, headers=_headers(self.keypair, {}))


def _boot(db_path: str, na_key, genesis, operator_keypair) -> NetworkAuthorityService:
    return NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_key,
        key_id="na-int",
        db_path=db_path,
        operator_public_keys={"ops": operator_keypair.public_key_b64},
        operator_key_tiers={"ops": "privileged"},
        boundary_policy_enforcement="required",
    )


def _agreement(op: _Operator, na_pub: str) -> dict:
    now = datetime.now(timezone.utc)
    treaty = {
        "subject_sovereign_id": "partner",
        "subject_public_keys": [na_pub],
        "scope": {"allowed_roles": ["role:client"]},
        "validity_hours": 24,
    }
    assert op.post("/admin/recognition-treaties", treaty).status_code == 201
    offer = op.post("/admin/agreements/offer", {
        "responder_sovereign_id": "partner",
        "capabilities": ["payments.transfer"],
        "scope": {},
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }).get_json()
    return op.post("/admin/agreements/accept", {"offer": offer}).get_json()


def _intent(limit: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "policy_id": "transfer-limits",
        "valid_from": (now - timedelta(minutes=5)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat(),
        "selector": {"capabilities": ["payments.*"]},
        "gates": [
            {"gate_id": "amount-cap", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.amount", "max": limit}},
            {"gate_id": "mfa", "gate_type": "boolean_required.v1", "order": 1,
             "config": {"path": "attributes.mfa_verified"}},
        ],
    }


def _evaluate(op: _Operator, agreement: dict) -> tuple[BoundaryDecision, JustificationProof]:
    resp = op.post("/admin/boundary/evaluate", {
        "agreement": agreement,
        "requested_capability": "payments.transfer",
        "context": {"request_parameters": {"amount": 2500}, "attributes": {"mfa_verified": True}},
    })
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    return (
        BoundaryDecision.model_validate(body["decision"]),
        JustificationProof.model_validate(body["justification_proof"]),
    )


def test_policy_lifecycle_survives_restart_and_is_verifiable_offline(tmp_path):
    root = nacl.signing.SigningKey.generate()
    na_pub = root.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="integration-policy",
        network_version="v0.1",
        root_public_key=na_pub,
        network_authority=NetworkAuthority(public_key=na_pub, valid_from=now, valid_to=now + timedelta(days=90)),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    genesis.signatures.append(sign_model(genesis, root, "root"))
    operator_keypair = generate_keypair()
    db_path = str(tmp_path / "na.db")

    # --- boot 1: publish lenient v1 and strict v2, activate strict --------
    op = _Operator(_boot(db_path, root, genesis, operator_keypair), operator_keypair)
    agreement = _agreement(op, na_pub)
    v1 = BoundaryPolicy.model_validate(op.post("/admin/boundary-policies", _intent(10_000)).get_json())
    v2 = BoundaryPolicy.model_validate(op.post("/admin/boundary-policies", _intent(1_000)).get_json())
    assert (v1.version, v2.version) == (1, 2)
    assert op.post("/admin/boundary-policies/transfer-limits/activate", {"version": 2}).status_code == 200

    # The legacy route cannot bypass policy under required enforcement.
    legacy = op.post("/admin/boundary/decide", {"agreement": agreement, "requested_capability": "payments.transfer"})
    assert legacy.status_code == 409

    denied, denied_proof = _evaluate(op, agreement)
    assert denied.authorized is False
    assert denied.denial_reason == "policy gate 'transfer-limits/amount-cap' failed"

    # --- boot 2: same database, new process state -------------------------
    service = _boot(db_path, root, genesis, operator_keypair)
    op = _Operator(service, operator_keypair)
    active = op.get("/admin/boundary-policies/active").get_json()
    assert [(p["policy_id"], p["version"]) for p in active["active"]] == [("transfer-limits", 2)]
    assert active["policy_set_healthy"] is True
    still_denied, _ = _evaluate(op, agreement)
    assert still_denied.authorized is False

    # --- rollback to v1 ---------------------------------------------------
    rollback = op.post("/admin/boundary-policies/transfer-limits/activate", {"version": 1}).get_json()
    assert rollback["previous_version"] == 2
    allowed, allowed_proof = _evaluate(op, agreement)
    assert allowed.authorized is True

    history = op.get("/admin/boundary-policies/transfer-limits/history").get_json()
    assert [(v["version"], v["active"]) for v in history["versions"]] == [(2, False), (1, True)]

    # --- offline audit with only public material --------------------------
    assert verify_boundary_policy(v1, [na_pub]).valid
    assert verify_boundary_policy(v2, [na_pub]).valid

    r = verify_boundary_decision(denied, [na_pub], expected_policies=[v2])
    assert r.accepted and r.reason == "unauthorized_policy_gate_failure"
    assert verify_boundary_decision(denied, [na_pub], expected_policies=[v1]).reason == "policy_binding_mismatch"
    assert verify_justification_proof(denied_proof, [na_pub], decision=denied).valid

    r = verify_boundary_decision(allowed, [na_pub], expected_policies=[v1])
    assert r.accepted and r.reason == "authorized"
    assert verify_justification_proof(allowed_proof, [na_pub], decision=allowed).valid

    # The proof explains the rule without disclosing the amount.
    entry = next(e for e in denied_proof.trace.entries if e.gate_name == "transfer-limits/amount-cap")
    assert entry.inputs["condition"] == {"operator": "<=", "max": 1000.0}
    assert "2500" not in denied_proof.to_canonical_json()

    # The audit trail, persisted across the restart, records the full lifecycle.
    events = [e["event_type"] for e in service.db.list_audit_events()]
    for expected in (
        "boundary_policy_published",
        "boundary_policy_activated",
        "boundary_legacy_decide_refused",
        "boundary_policy_decision_made",
    ):
        assert expected in events
    assert events.count("boundary_policy_activated") == 2
