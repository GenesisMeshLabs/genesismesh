"""Integration test: a vendor's secret history, decision to execution, across an NA restart (v0.59).

A vendor is admitted with an attestation.  The NA authorizes each secret
operation against it and stores the signed decision; a secrets controller
creates, rotates and revokes the secret and submits signed evidence.  The
attestation is then revoked: the next decision is denied and evidence
against it is refused.  After a restart on the same database the vendor's
and the secret's full history are shown and verified from the NA alone,
and an export verifies offline.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.crypto import generate_keypair, sign_data, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
from genesis_mesh.trust.execution import record_execution

pytestmark = pytest.mark.integration

VENDOR = "vendor-acme"
SECRET = "kv:vendor-acme/api-key"


def _headers(keypair, body: dict) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {"body": body, "key_id": "ops", "timestamp": ts, "nonce": nonce}, sort_keys=True, separators=(",", ":")
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
        evidence_store="on",
    )


def test_secret_history_is_shown_and_verified_from_the_na_alone(tmp_path):
    root = nacl.signing.SigningKey.generate()
    na_pub = root.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="integration-evidence",
        network_version="v0.1",
        root_public_key=na_pub,
        network_authority=NetworkAuthority(public_key=na_pub, valid_from=now, valid_to=now + timedelta(days=90)),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    genesis.signatures.append(sign_model(genesis, root, "root"))
    operator_keypair = generate_keypair()
    db_path = str(tmp_path / "na.db")

    # --- boot 1: admit the vendor, register the controller, act on the secret
    op = _Operator(_boot(db_path, root, genesis, operator_keypair), operator_keypair)
    attestation = op.post("/admin/attestations", {
        "subject_id": VENDOR, "roles": ["role:client"],
        "claims": {"capabilities": ["secret.manage"], "apps": ["billing"]},
    }).get_json()
    controller_key = nacl.signing.SigningKey.generate()
    controller_pub = controller_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    assert op.post("/admin/evidence/executor-keys", {
        "key_id": "ctrl", "public_key": controller_pub, "executor_sovereign_id": "secrets-controller",
    }).status_code == 201

    def decide() -> BoundaryDecision:
        resp = op.post("/admin/boundary/evaluate", {
            "attestation_id": attestation["attestation_id"], "requested_capability": "secret.manage",
        })
        assert resp.status_code == 201
        return BoundaryDecision.model_validate(resp.get_json()["decision"])

    prior = None
    for action in ("create", "rotate", "revoke"):
        decision = decide()
        assert decision.authorized
        record = record_execution(
            decision, "secrets-controller", "secret.manage", "success", controller_key,
            issued_by="ctrl", execution_parameters={"secret_version": action},
            resource_id=SECRET, resource_action=action, prior_resource_record=prior,
        )
        assert op.client.post("/evidence/execution", json={"evidence": record.model_dump(mode="json")}).status_code == 201
        prior = record

    # Membership withdrawn: the next decision is denied, and evidence under it is refused.
    assert op.post(f"/admin/attestations/{attestation['attestation_id']}/revoke", {"reason": "offboarded"}).status_code == 200
    denied = decide()
    assert not denied.authorized and denied.denial_reason == "attestation_revoked"
    late = record_execution(
        denied, "secrets-controller", "secret.manage", "success", controller_key, issued_by="ctrl",
        resource_id=SECRET, resource_action="update", prior_resource_record=prior,
    )
    refused = op.client.post("/evidence/execution", json={"evidence": late.model_dump(mode="json")})
    assert refused.status_code == 422 and refused.get_json()["error"]["code"] == "evidence_decision_denied"

    # --- boot 2: same database; everything is still there and verifies
    op = _Operator(_boot(db_path, root, genesis, operator_keypair), operator_keypair)
    secret = op.get(f"/admin/evidence/resources/{SECRET}").get_json()
    actions = [e["payload"]["resource_action"] for e in secret["entries"] if e["entry"]["entry_kind"] == "execution"]
    assert actions == ["create", "rotate", "revoke"]
    assert secret["verification"]["verified"], secret["verification"]

    vendor = op.get(f"/admin/evidence/vendors/{VENDOR}").get_json()
    assert vendor["verification"]["verified"]
    assert vendor["verification"]["decisions"] == 4  # three authorized, one denied
    assert vendor["verification"]["executions"] == 3
    assert op.get("/admin/evidence/verify").get_json()["verified"]

    lines = op.get("/admin/evidence/export").get_data(as_text=True).splitlines()
    keys = {"ctrl": ExecutorKey("ctrl", controller_pub, "secrets-controller")}
    offline = verify_evidence_events(parse_export_lines(lines), na_public_keys=[na_pub], executor_keys=keys)
    assert offline.verified and offline.executions == 3
