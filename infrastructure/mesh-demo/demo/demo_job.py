"""Keeps the mesh.genesismesh.org demo alive with real, signed activity.

Runs next to the `genesis-mesh` NA on the internal network, every
``DEMO_INTERVAL_SECONDS``. Each cycle is idempotent:

1. Bootstrap (when missing): a recognition policy, a treaty recognizing the
   public reference (`gm-demo-public-na`), the demo boundary policy, the
   executor key and a long-lived controller attestation.
2. Import the reference's signed revocation feed.
3. Visitor badges: issue a short-lived `demo:visitor-*` attestation and revoke
   older ones, so verification scenarios always have an accepted and a
   revoked example.
4. A governed secret rotation on `kv:mesh-demo/rotating-secret`, linked to the
   resource head; every third cycle also a request the policy denies.
5. Publish signed records to ``DEMO_DATA_DIR`` (served read-only at
   ``/demo-data/``) for the browser scenarios.

Keys come from the environment: ``DEMO_OPERATOR_SEED`` (a dedicated
privileged operator key, ``demo-ops``; attestation issuance, revocation and
feed import need that tier) and ``DEMO_EXECUTOR_SEED``. Neither is the
maintainer's operator key. Nothing secret is written to the demo data.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from nacl.signing import SigningKey

from genesis_mesh.crypto import sign_model
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.trust.execution import record_execution

log = logging.getLogger("mesh-demo")

NA_URL = os.environ.get("NA_URL", "http://na:8000").rstrip("/")
SOVEREIGN = os.environ.get("DEMO_SOVEREIGN_ID", "genesis-mesh")
NA_KEY = os.environ["NA_PUBLIC_KEY"]
REFERENCE_URL = os.environ.get("REFERENCE_URL", "https://na.genesismesh.connectorzzz.com").rstrip("/")
REFERENCE_ID = os.environ.get("REFERENCE_SOVEREIGN_ID", "gm-demo-public-na")
REFERENCE_KEY = os.environ["REFERENCE_PUBLIC_KEY"]
OPERATOR_ID = os.environ.get("DEMO_OPERATOR_KEY_ID", "demo-ops")
OPERATOR = SigningKey(base64.b64decode(os.environ["DEMO_OPERATOR_SEED"]))
EXECUTOR_ID = os.environ.get("DEMO_EXECUTOR_KEY_ID", "mesh-demo-controller")
EXECUTOR = SigningKey(base64.b64decode(os.environ["DEMO_EXECUTOR_SEED"]))
OUT = Path(os.environ.get("DEMO_DATA_DIR", "/demo-data"))
STATE = Path(os.environ.get("DEMO_STATE_FILE", "/state/demo-state.json"))
INTERVAL = int(os.environ.get("DEMO_INTERVAL_SECONDS", "600"))

POLICY_ID = "mesh-demo-secrets"
RESOURCE = "kv:mesh-demo/rotating-secret"
CONTROLLER = "demo:secrets-controller"
APP = "mesh-demo"
BADGE_LIFETIME = timedelta(hours=3)
BADGE_REVOKE_AFTER = timedelta(minutes=40)
EXPORT_TAIL = 300


def now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def call(method: str, path: str, body: dict | None = None, *, admin: bool = False,
         params: dict | None = None, ok: tuple[int, ...] = (200, 201)) -> requests.Response:
    headers = {}
    if admin:
        ts, nonce = now().isoformat(), str(uuid.uuid4())
        signed = canonical({"body": body if method == "POST" else {}, "key_id": OPERATOR_ID,
                            "timestamp": ts, "nonce": nonce})
        headers = {"X-Admin-Key-Id": OPERATOR_ID, "X-Admin-Timestamp": ts, "X-Admin-Nonce": nonce,
                   "X-Admin-Signature": base64.b64encode(OPERATOR.sign(signed.encode()).signature).decode()}
    response = requests.request(method, NA_URL + path, json=body if method == "POST" else None,
                                params=params, headers=headers, timeout=15)
    if response.status_code not in ok:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
    return response


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"badges": [], "revoked": [], "cycle": 0}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(STATE)


def publish(name: str, value: Any, text: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    tmp.write_text(value if text else json.dumps(value, indent=1), encoding="utf-8")
    tmp.replace(OUT / name)


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def issue(subject: str, lifetime: timedelta, claims: dict) -> dict:
    hours = max(1, int(lifetime.total_seconds() // 3600))
    return call("POST", "/admin/attestations", {
        "subject_id": subject, "roles": ["role:client"], "validity_hours": hours, "claims": claims,
    }, admin=True).json()


# -- bootstrap ---------------------------------------------------------------

def bootstrap(state: dict) -> None:
    if not state.get("recognition_policy"):
        call("POST", "/admin/recognition-policy", {"recognition_policy": {
            "local_sovereign_id": SOVEREIGN,
            "recognized_issuers": [{"sovereign_id": SOVEREIGN, "public_keys": [NA_KEY],
                                    "allowed_roles": ["role:client"], "accepted_statuses": ["active"]}],
            "revoked_attestation_ids": [],
        }}, admin=True)
        state["recognition_policy"] = True

    treaties = call("GET", "/recognition-treaties", params={"status": "active"}).json()
    current = [r["treaty"] for r in treaties.get("recognition_treaties", [])
               if r["treaty"]["subject_sovereign_id"] == REFERENCE_ID
               and r["treaty"]["subject_public_keys"] == [REFERENCE_KEY]
               and parse(r["treaty"]["expires_at"]) - now() > timedelta(days=7)]
    if not current:
        treaty = call("POST", "/admin/recognition-treaties", {
            "subject_sovereign_id": REFERENCE_ID, "subject_public_keys": [REFERENCE_KEY],
            "scope": {"allowed_roles": ["role:client"]}, "validity_hours": 720,
        }, admin=True).json()
        log.info("recognized %s: treaty %s", REFERENCE_ID, treaty.get("treaty_id"))

    active = call("GET", "/admin/boundary-policies/active", admin=True).json()
    if not any(p.get("policy_id") == POLICY_ID for p in active.get("active", [])):
        policy = call("POST", "/admin/boundary-policies", {
            "policy_id": POLICY_ID,
            "description": "mesh.genesismesh.org demo: secret rotation for the demo controller",
            "valid_from": (now() - timedelta(minutes=5)).isoformat(),
            "valid_until": (now() + timedelta(days=365)).isoformat(),
            "selector": {"parent_kinds": ["attestation"], "capabilities": ["sp-secret.*"]},
            "gates": [
                {"gate_id": "app", "gate_type": "attestation_claim.v1", "order": 0,
                 "config": {"path": "request_parameters.app_id", "claim": "apps"}},
                {"gate_id": "lifetime", "gate_type": "max_value.v1", "order": 1,
                 "config": {"path": "request_parameters.lifetime_days", "max": 90}},
            ],
        }, admin=True).json()
        call("POST", f"/admin/boundary-policies/{POLICY_ID}/activate", {"version": policy["version"]}, admin=True)
        log.info("activated policy %s v%s", POLICY_ID, policy["version"])

    keys = call("GET", "/admin/evidence/executor-keys", admin=True).json()["executor_keys"]
    if not any(k["key_id"] == EXECUTOR_ID for k in keys):
        call("POST", "/admin/evidence/executor-keys", {
            "key_id": EXECUTOR_ID, "executor_sovereign_id": EXECUTOR_ID,
            "public_key": base64.b64encode(bytes(EXECUTOR.verify_key)).decode(),
        }, admin=True)

    controller = state.get("controller")
    if controller is None or parse(controller["expires_at"]) - now() < timedelta(days=1):
        fresh = issue(CONTROLLER, timedelta(days=7), {
            "capabilities": ["sp-secret.create", "sp-secret.rotate"], "apps": [APP],
            "public_mesh": True, "demo": True,
        })
        if controller is not None:
            call("POST", f"/admin/attestations/{controller['attestation_id']}/revoke",
                 {"reason": "superseded"}, admin=True, ok=(200, 404, 409))
        state["controller"] = fresh


# -- cycle -------------------------------------------------------------------

def import_reference_feed() -> dict:
    feed = requests.get(REFERENCE_URL + "/sovereign-revocation-feed", timeout=15).json()
    result = call("POST", "/admin/sovereign-revocation-feeds/import",
                  {"feed": feed, "issuer_public_keys": [REFERENCE_KEY]}, admin=True, ok=(200, 201, 409))
    return {"sequence": feed.get("sequence"), "issued_at": feed.get("issued_at"),
            "status": "imported" if result.status_code in (200, 201) else "unchanged"}


def rotate_badges(state: dict) -> None:
    stamp = now()
    state["badges"].append(issue(f"demo:visitor-{stamp:%H%M}", BADGE_LIFETIME, {"public_mesh": True, "demo": True}))
    keep = []
    for badge in state["badges"]:
        if stamp - parse(badge["issued_at"]) > BADGE_REVOKE_AFTER:
            call("POST", f"/admin/attestations/{badge['attestation_id']}/revoke",
                 {"reason": "demo rotation"}, admin=True, ok=(200, 404, 409))
            state["revoked"] = (state["revoked"] + [badge])[-10:]
        else:
            keep.append(badge)
    state["badges"] = keep


def governed_rotation(state: dict, lifetime_days: int) -> dict:
    controller = state["controller"]
    evaluation = call("POST", "/admin/boundary/evaluate", {
        "attestation_id": controller["attestation_id"], "requested_capability": "sp-secret.rotate",
        "context": {"context_id": str(uuid.uuid4()),
                    "request_parameters": {"app_id": APP, "lifetime_days": lifetime_days}},
    }, admin=True).json()
    decision = evaluation["decision"]
    if not decision["authorized"]:
        return {"authorized": False, "decision_id": decision["decision_id"], "denial_reason": decision["denial_reason"]}
    head_response = call("GET", f"/admin/evidence/resource-heads/{RESOURCE}", admin=True, ok=(200, 404))
    head = head_response.json() if head_response.status_code == 200 else None
    version = (head["resource_sequence"] + 1) if head else 1
    record = record_execution(BoundaryDecision.model_validate(decision), EXECUTOR_ID, "sp-secret.rotate",
                              "success", EXECUTOR, issued_by=EXECUTOR_ID,
                              execution_parameters={"secret_version": f"v{version}"},
                              resource_id=RESOURCE, resource_action="rotate" if head else "create")
    # Link to the head from the NA's lookup rather than a stored full record.
    unsigned = record.model_copy(update={
        "resource_sequence": version, "prev_resource_digest": head["record_digest"] if head else None,
        "signature": None,
    })
    record = unsigned.model_copy(update={"signature": sign_model(unsigned, EXECUTOR, EXECUTOR_ID)})
    submission = call("POST", "/evidence/execution", {"evidence": json.loads(record.model_dump_json())}).json()
    return {"authorized": True, "decision_id": decision["decision_id"], "resource_sequence": version,
            "status": submission.get("status")}


def publish_demo_data(state: dict, feed: dict, actions: list[dict]) -> None:
    status = call("GET", "/admin/evidence/status", admin=True).json()
    last = status.get("last_store_sequence") or 0
    since = max(0, last - EXPORT_TAIL)
    export = call("GET", "/admin/evidence/export", admin=True,
                  params={"since_sequence": since, "limit": 1000}).text
    publish("evidence.ndjson", export, text=True)
    publish("executor-keys.json", call("GET", "/admin/evidence/executor-keys", admin=True).json())
    head = call("GET", f"/admin/evidence/resource-heads/{RESOURCE}", admin=True, ok=(200, 404))
    history = call("GET", f"/admin/boundary-policies/{POLICY_ID}/history", admin=True).json()
    active_policy = next((v["policy"] for v in history.get("versions", []) if v.get("active")), None)
    treaties = call("GET", "/recognition-treaties", params={"status": "active"}).json()
    try:
        reference = requests.get(REFERENCE_URL + "/recognition-treaties", timeout=15).json()
        reverse = [r["treaty"] for r in reference.get("external_treaties", [])
                   if r["treaty"]["subject_sovereign_id"] == SOVEREIGN]
    except (requests.RequestException, ValueError):
        reverse = []
    publish("network.json", {
        "sovereign_id": SOVEREIGN, "na_public_key": NA_KEY,
        "reference": {"sovereign_id": REFERENCE_ID, "public_key": REFERENCE_KEY, "url": REFERENCE_URL},
        "treaties_issued": [r["treaty"] for r in treaties.get("recognition_treaties", [])],
        "treaties_received": reverse,
        "policy": active_policy,
        "resource_id": RESOURCE,
        "resource_head": head.json() if head.status_code == 200 else None,
        "evidence_export_since_sequence": since,
    })
    publish("attestations.json", {
        "controller": state["controller"],
        "active": state["badges"],
        "revoked": state["revoked"],
    })
    publish("status.json", {
        "updated_at": now().isoformat(), "cycle": state["cycle"], "interval_seconds": INTERVAL,
        "reference_feed": feed, "last_actions": actions, "store": status,
    })


def cycle(state: dict) -> None:
    state["cycle"] += 1
    bootstrap(state)
    save_state(state)
    try:
        feed = import_reference_feed()
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        log.warning("reference feed import failed: %s", exc)
        feed = {"status": "unavailable"}
    rotate_badges(state)
    save_state(state)
    actions = [governed_rotation(state, 30)]
    if state["cycle"] % 3 == 0:
        actions.append(governed_rotation(state, 400))
    save_state(state)
    publish_demo_data(state, feed, actions)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = load_state()
    while True:
        try:
            cycle(state)
            log.info("cycle %s complete", state["cycle"])
        except Exception:  # noqa: BLE001 - keep the demo running; the next cycle retries
            log.exception("cycle %s failed", state["cycle"])
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
