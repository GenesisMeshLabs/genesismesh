"""A small client for the operations demos: signed admin requests and governed actions.

Run in the directory ``genesis-mesh init`` wrote (it reads genesis-mesh.toml):

    python ops-demo-client.py admin GET /admin/evidence/status
    python ops-demo-client.py admin --status POST /admin/evidence/anchors
    python ops-demo-client.py admin GET /admin/evidence/export > export.jsonl
    python ops-demo-client.py record --count 2

``admin`` signs one admin request with the operator key from the config and
prints the NA's answer (exit 1 on an HTTP error). ``record`` acts as a
controller: on its first run it publishes and activates a boundary policy,
issues an attestation and registers its executor key (kept in
``controller.key``); then, per action, it asks the NA for a decision
(``/admin/boundary/evaluate``) and reports the signed execution evidence
(``/evidence/execution``), continuing the resource's chain.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import nacl.signing
import requests

from genesis_mesh.crypto import load_private_key
from genesis_mesh.crypto.admin_auth import sign_admin_request

POLICY_ID = "ops-demo"
SUBJECT = "vendor-acme"
EXECUTOR = "secrets-controller"
EXECUTOR_KEY_ID = "ctrl-1"
STATE = Path("controller-state.json")


class NA:
    def __init__(self, config: str) -> None:
        cfg = tomllib.loads(Path(config).read_text(encoding="utf-8"))
        self.base = cfg["network"]["na_endpoint"].rstrip("/")
        self.key = load_private_key(cfg["paths"]["operator_private_key"])
        self.key_id = cfg.get("operator", {}).get("key_id", "operator-local")
        self.audience = requests.get(f"{self.base}/genesis", timeout=10).json()["network_authority"]["public_key"]

    def admin(self, method: str, path: str, body=None) -> requests.Response:
        parts = urlsplit(path)
        headers = sign_admin_request(self.key, self.key_id, method=method, path=parts.path,
                                     query=parse_qs(parts.query, keep_blank_values=True),
                                     audience=self.audience, body=body if body is not None else {})
        kwargs = {"headers": headers, "timeout": 30}
        if method != "GET":
            kwargs["json"] = body if body is not None else {}
        return requests.request(method, self.base + path, **kwargs)

    def expect(self, resp: requests.Response, *codes: int) -> dict:
        if resp.status_code not in codes:
            raise SystemExit(f"{resp.request.method} {urlsplit(resp.request.url).path}: "
                             f"HTTP {resp.status_code} {resp.text.strip()}")
        return resp.json()


def _pub(key: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(key.verify_key)).decode()


def _setup(na: NA) -> dict:
    now = datetime.now(timezone.utc)
    policy = na.expect(na.admin("POST", "/admin/boundary-policies", {
        "policy_id": POLICY_ID, "description": "Operations demo",
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=30)).isoformat(),
        "selector": {"parent_kinds": ["attestation"], "capabilities": ["secret.*"]},
        "gates": [{"gate_id": "app", "gate_type": "attestation_claim.v1", "order": 0,
                   "config": {"path": "request_parameters.app_id", "claim": "apps"}}],
    }), 201)
    na.expect(na.admin("POST", f"/admin/boundary-policies/{POLICY_ID}/activate", {"version": policy["version"]}), 200)
    attestation = na.expect(na.admin("POST", "/admin/attestations", {
        "subject_id": SUBJECT, "roles": ["role:client"],
        "claims": {"capabilities": ["secret.rotate"], "apps": ["billing"]}, "validity_hours": 24 * 30,
    }), 201)
    executor = nacl.signing.SigningKey.generate()
    Path("controller.key").write_text(base64.b64encode(bytes(executor)).decode() + "\n", encoding="utf-8")
    na.expect(na.admin("POST", "/admin/evidence/executor-keys", {
        "key_id": EXECUTOR_KEY_ID, "public_key": _pub(executor), "executor_sovereign_id": EXECUTOR,
    }), 201)
    state = {"attestation_id": attestation["attestation_id"], "heads": {}}
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def record(na: NA, count: int, resource: str) -> None:
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.trust.execution import record_execution

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else _setup(na)
    executor = nacl.signing.SigningKey(base64.b64decode(Path("controller.key").read_text(encoding="utf-8").strip()))
    for _ in range(count):
        decision = na.expect(na.admin("POST", "/admin/boundary/evaluate", {
            "attestation_id": state["attestation_id"], "requested_capability": "secret.rotate",
            "context": {"request_parameters": {"app_id": "billing"}},
        }), 201)["decision"]
        prior = state["heads"].get(resource)
        evidence = record_execution(
            BoundaryDecision.model_validate(decision), EXECUTOR, "secret.rotate", "success", executor,
            issued_by=EXECUTOR_KEY_ID, sequence_no=1, resource_id=resource,
            resource_action="rotate" if prior else "create",
            prior_resource_record=ExecutionEvidence.model_validate(prior) if prior else None,
            now=datetime.now(timezone.utc),
        ).model_dump(mode="json")
        na.expect(requests.post(f"{na.base}/evidence/execution", json={"evidence": evidence}, timeout=30), 201)
        state["heads"][resource] = evidence
        print(f"{resource} {evidence['resource_action']:<6} seq {evidence['resource_sequence']}  "
              f"decision {decision['decision_id'][:8]} authorized={decision['authorized']}  "
              f"evidence {evidence['evidence_id'][:8]}")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="genesis-mesh.toml")
    sub = ap.add_subparsers(dest="command", required=True)
    adm = sub.add_parser("admin", help="Send one signed admin request and print the answer.")
    adm.add_argument("method")
    adm.add_argument("path")
    adm.add_argument("--body", help="JSON body")
    adm.add_argument("--status", action="store_true", help="Print the HTTP status line first.")
    rec = sub.add_parser("record", help="Record governed actions: a decision and its execution evidence each.")
    rec.add_argument("--count", type=int, default=1)
    rec.add_argument("--resource", default="kv:billing/api-key")
    args = ap.parse_args()
    na = NA(args.config)
    if args.command == "admin":
        resp = na.admin(args.method.upper(), args.path, json.loads(args.body) if args.body else None)
        if args.status:
            print(f"HTTP {resp.status_code}")
        sys.stdout.write(resp.text if resp.text.endswith("\n") else resp.text + "\n")
        return 0 if resp.status_code < 400 else 1
    record(na, args.count, args.resource)
    return 0


if __name__ == "__main__":
    sys.exit(main())
