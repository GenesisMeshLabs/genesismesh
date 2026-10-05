"""Leg 1 (Python): negotiate an agreement and obtain signed decisions and a policy.

Two sovereigns with their own Ed25519 keys negotiate an agreement
(offer -> counter -> accept, dual-signed). The running Network Authority
(``na_server.py``) publishes a boundary policy, evaluates requests under the
agreement and under an attestation, and signs a data license policy. Every
artifact is written to ``fixtures/`` with the public keys needed to verify it,
together with deliberately tampered copies, and the Python reference records
its verdict on each in ``fixtures/results/python.json``.

    python interop/python/setup.py
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import requests

from genesis_mesh.crypto import generate_keypair, verify_model_signature
from genesis_mesh.models import MembershipAttestation
from genesis_mesh.models.agreement import AgreementRecord
from genesis_mesh.models.boundary_policy import BoundaryPolicy
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.trust.agreement import AgreementTerms, accept_counter, build_counter, build_offer, verify_agreement
from genesis_mesh.trust.context import verify_boundary_decision
from genesis_mesh.trust.data_usage import DataLicensePolicy

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RESULTS = FIXTURES / "results"
ORG_A, BANK_A = "org-a", "bank-a"


def write(name: str, data: object) -> None:
    (FIXTURES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class NA:
    """Operator client for the local Network Authority."""

    def __init__(self, info: dict) -> None:
        self.url = info["base_url"]
        self.key_id = info["operator_key_id"]
        self.key = nacl.signing.SigningKey(base64.b64decode(info["operator_seed"]))

    def post(self, path: str, body: dict) -> dict:
        from genesis_mesh.crypto.admin_auth import sign_admin_request

        if not getattr(self, "audience", None):
            self.audience = requests.get(self.url + "/sovereign.json", timeout=10).json()["network_authority"]["public_key"]
        headers = sign_admin_request(
            self.key, self.key_id, method="POST", path=path, audience=self.audience, body=body,
        )
        resp = requests.post(self.url + path, json=body, headers=headers, timeout=10)
        if resp.status_code >= 300:
            raise SystemExit(f"{path}: HTTP {resp.status_code} {resp.text}")
        return resp.json()


def graph(org_pub: str, bank_pub: str, now: datetime) -> dict:
    edge = {"status": "active", "lifecycle_state": "active", "expiry_risk": "low",
            "valid_from": now.isoformat(), "expires_at": (now + timedelta(days=365)).isoformat()}
    return {
        "sovereigns": [{"sovereign_id": ORG_A, "public_key": org_pub}, {"sovereign_id": BANK_A, "public_key": bank_pub}],
        "recognition_edges": [{"from": ORG_A, "to": BANK_A, "treaty_id": "t-ab", **edge},
                              {"from": BANK_A, "to": ORG_A, "treaty_id": "t-ba", **edge}],
    }


def main() -> int:
    na_info = json.loads((FIXTURES / "na.json").read_text(encoding="utf-8"))
    na = NA(na_info)
    now = datetime.now(timezone.utc)
    RESULTS.mkdir(parents=True, exist_ok=True)

    # 1. Two sovereigns with their own keys negotiate a dual-signed agreement.
    org, bank = generate_keypair(), generate_keypair()
    g = graph(org.public_key_b64, bank.public_key_b64, now)
    terms = AgreementTerms(
        capabilities=["transactions.read", "statements.read"],
        scope={"accounts": ["acc-001"], "region": "Zürich ✓", "max_ratio": 0.25, "limit": 1.0},
        valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=30),
    )
    offer = build_offer(ORG_A, BANK_A, terms, g, org.private_key, issued_by=org.public_key_b64, expires_at=now + timedelta(days=1))
    counter = build_counter(offer, terms, g, bank.private_key, issued_by=bank.public_key_b64)
    agreement = accept_counter(counter, offer, org.private_key, issued_by=org.public_key_b64)
    agreement_json = agreement.model_dump(mode="json")
    tampered_agreement = json.loads(json.dumps(agreement_json))
    tampered_agreement["agreed_terms"]["capabilities"].append("transactions.write")

    # 2. The NA publishes a policy and decides under the agreement and an attestation.
    policy = na.post("/admin/boundary-policies", {
        "policy_id": "bank-read-limits", "description": "Row limits for bank data — Zürich ✓",
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=30)).isoformat(),
        "selector": {"capabilities": ["transactions.*", "statements.*"]},
        "gates": [
            {"gate_id": "max-rows", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.rows", "max": 90}},
            {"gate_id": "purpose", "gate_type": "required_parameter.v1", "order": 1, "mode": "observe",
             "config": {"path": "attributes.purpose"}},
        ],
    })
    na.post(f"/admin/boundary-policies/{policy['policy_id']}/activate", {"version": policy["version"]})
    context = {"request_parameters": {"rows": 10}, "attributes": {"purpose": "statement"},
               "requester_sovereign_id": BANK_A, "provider_sovereign_id": ORG_A}
    allowed = na.post("/admin/boundary/evaluate", {
        "agreement": agreement_json, "requested_capability": "transactions.read", "context": context})["decision"]
    denied = na.post("/admin/boundary/evaluate", {
        "agreement": agreement_json, "requested_capability": "transactions.read",
        "context": {**context, "request_parameters": {"rows": 500}}})["decision"]
    attestation = na.post("/admin/attestations", {
        "subject_id": BANK_A, "roles": ["role:client"], "subject_public_key": bank.public_key_b64,
        "claims": {"capabilities": ["transactions.read"], "region": "Zürich ✓"}})
    attested = na.post("/admin/boundary/evaluate", {
        "attestation_id": attestation["attestation_id"], "requested_capability": "transactions.read",
        "context": {"request_parameters": {"rows": 10}, "attributes": {"purpose": "statement"}}})["decision"]
    tampered_decision = {**allowed, "denial_reason": "edited after signing"}

    # 3. The NA, as licensor, signs a data license policy for bank-a.
    data_policy = na.post("/admin/data-usage/policy", {
        "licensee_sovereign_id": BANK_A, "allowed_source_ids": ["db-prod", "db-archive"],
        "allowed_access_types": ["read"], "prohibited_classification_tags": ["pii-raw"],
        "max_volume_bytes_per_session": 10_000_000,
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=30)).isoformat(),
    })

    keys = {
        ORG_A: org.public_key_b64, BANK_A: bank.public_key_b64, "na": na_info["na_public_key"],
        "na_network": na_info["network"],
    }
    write("public_keys.json", keys)
    write("agreement.json", agreement_json)
    write("agreement_tampered.json", tampered_agreement)
    write("boundary_policy.json", policy)
    write("boundary_decision.json", allowed)
    write("boundary_decision_denied.json", denied)
    write("boundary_decision_attestation.json", attested)
    write("boundary_decision_tampered.json", tampered_decision)
    write("attestation.json", attestation)
    write("data_policy.json", data_policy)

    # 4. The reference verdict on every artifact.
    verify_at = datetime.now(timezone.utc)
    policies = [BoundaryPolicy.model_validate(policy)]

    def agreement_verdict(record: dict) -> dict:
        r = verify_agreement(AgreementRecord.model_validate(record), [keys[ORG_A]], [keys[BANK_A]])
        return {"accepted": r.accepted, "reason": r.reason}

    def decision_verdict(decision: dict, **expected) -> dict:
        r = verify_boundary_decision(BoundaryDecision.model_validate(decision), [keys["na"]], now=verify_at, **expected)
        return {"accepted": r.accepted, "reason": r.reason, "authorized": r.authorized}

    att_model = MembershipAttestation.model_validate(attestation)
    policy_model = DataLicensePolicy.model_validate(data_policy)
    verdicts = {
        "agreement": agreement_verdict(agreement_json),
        "agreement_tampered": agreement_verdict(tampered_agreement),
        "boundary_decision": decision_verdict(allowed, expected_policies=policies),
        "boundary_decision_denied": decision_verdict(denied, expected_policies=policies),
        "boundary_decision_attestation": decision_verdict(attested, expected_policies=policies,
                                                         expected_attestation=att_model),
        "boundary_decision_tampered": decision_verdict(tampered_decision),
        "data_policy": {"valid": policy_model.signature is not None
                        and verify_model_signature(policy_model, policy_model.signature, keys["na"])},
    }
    (RESULTS / "python.json").write_text(json.dumps({"leg": "python", "verdicts": verdicts}, indent=2) + "\n")
    for name, verdict in verdicts.items():
        print(f"[PYTHON] {name}: {verdict}")
    ok = (verdicts["agreement"]["accepted"] and verdicts["boundary_decision"]["authorized"]
          and verdicts["boundary_decision_attestation"]["authorized"] and verdicts["data_policy"]["valid"])
    print(f"[PYTHON] fixtures written: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
