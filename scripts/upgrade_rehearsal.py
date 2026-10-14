"""Upgrade rehearsal: a database written by a past release, upgraded and verified by this one.

    python scripts/upgrade_rehearsal.py --from 0.59.1 [--postgres-url URL]
    python scripts/upgrade_rehearsal.py --installed dist/genesis_mesh-X.whl

1. Run the past release from its git tag (``git archive vFROM``, its pinned
   requirements in a temporary virtualenv), as source deployments and the
   container image do, and run this script under it (``populate``). The
   wheels published before v0.62.0 lack the migration files, so a release
   installed from PyPI cannot run a Network Authority. The past release's NA
   writes a recognition treaty, partner attestations, an imported revocation
   feed, NA attestations (one revoked), an active boundary policy, decisions
   and a resource's execution chain, all through its stable HTTP routes.
2. Back the database up (SQLite online backup).
3. Start the current release on the database (``verify``), with the store's
   out-of-band records on (``EVIDENCE_OUT_OF_BAND=on``) and, since 1.4, its
   remediation records (``EVIDENCE_REMEDIATION=on``): migrations run, the
   policy history is backfilled from the past release's audit log, every
   record and decision is checked through the current HTTP routes and offline
   verifiers, an observation is judged and its remediation recorded, then the
   resource chain is extended. Since 1.5, the genesis key is the first entry of
   the key history and an audit pack of the whole store verifies offline from
   the root key and the anchors. Since 1.6, with grants on
   (``EVIDENCE_GRANTS=on``), a grant is issued under the past release's
   attestation and policy, a use of it continues the past release's resource
   chain at the position the NA assigns, and the export and the pack holding
   them verify offline. A past release with out-of-band records (1.3+)
   populates with them on and records an observation and its judgement, so a
   1.3 store with its Stage 2 records is upgraded; that judgement is not
   remediated when the remediation records are turned on.
4. Restore the backup and verify again.
5. With --postgres-url, migrate the restored database to PostgreSQL and
   verify it there.

Throwaway keys and temporary databases only. Exit status 0 when every check
passes.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

POLICY_ID = "upgrade-rehearsal"
RESOURCE = "kv:upgrade-rehearsal/secret"
PARTNER = "partner-b"
VENDOR = "vendor-acme"
EXECUTOR = "secrets-controller"


# ── shared helpers (must run on every supported past release) ───────────────


def _seed(key) -> str:
    return base64.b64encode(bytes(key)).decode()


def _key(seed: str):
    import nacl.signing

    return nacl.signing.SigningKey(base64.b64decode(seed))


def _pub(key) -> str:
    return base64.b64encode(bytes(key.verify_key)).decode()


def _has_out_of_band() -> bool:
    """Whether the release running this script records changes outside the controlled path (1.3+)."""
    try:
        import genesis_mesh.models.out_of_band  # noqa: F401
    except ImportError:
        return False
    return True


def _service(state: dict, *, db_path: str | None = None, database_url: str | None = None, out_of_band: bool = False,
             remediation: bool = False, grants: bool = False):
    from genesis_mesh.models import GenesisBlock
    from genesis_mesh.na_service.server import NetworkAuthorityService

    kwargs: dict[str, Any] = {}
    if database_url:
        kwargs["database_url"] = database_url
    if out_of_band:  # 1.3+ only: past releases before it populate without it
        kwargs["evidence_out_of_band"] = "on"
    if remediation:  # 1.4+ only
        kwargs["evidence_remediation"] = "on"
    if grants:  # 1.6+ only
        kwargs["evidence_grants"] = "on"
    service = NetworkAuthorityService(
        genesis_block=GenesisBlock.model_validate(state["genesis"]),
        na_private_key=_key(state["seeds"]["na"]), key_id="na-upgrade",
        db_path=db_path or ":memory:",
        operator_public_keys={"ops": _pub(_key(state["seeds"]["operator"]))},
        operator_key_tiers={"ops": "privileged"},
        boundary_policy_enforcement="required", evidence_store="on", **kwargs,
    )
    service.rate_limiter.allow = lambda *a, **k: True
    service.app.config["TESTING"] = True
    return service


class Api:
    """Signed operator calls through the Flask test client."""

    def __init__(self, service, operator_seed: str) -> None:
        self.client = service.app.test_client()
        self.key = _key(operator_seed)
        self.audience = service.genesis_block.network_authority.public_key

    def admin(self, method: str, path: str, body: dict | None = None):
        from genesis_mesh.crypto import sign_data

        body = body or {}
        try:
            # v1.0.2+: the signature binds method, path, query and audience.
            from genesis_mesh.crypto.admin_auth import sign_admin_request
        except ImportError:  # a past release: version 1 signs the body only
            ts = datetime.now(timezone.utc).isoformat()
            nonce = str(uuid.uuid4())
            canonical = json.dumps({"body": body, "key_id": "ops", "timestamp": ts, "nonce": nonce},
                                   sort_keys=True, separators=(",", ":"))
            headers = {"X-Admin-Key-Id": "ops", "X-Admin-Timestamp": ts, "X-Admin-Nonce": nonce,
                       "X-Admin-Signature": sign_data(canonical.encode("utf-8"), self.key)}
        else:
            from urllib.parse import parse_qs, urlsplit

            parts = urlsplit(path)
            headers = sign_admin_request(
                self.key, "ops", method=method, path=parts.path,
                query=parse_qs(parts.query, keep_blank_values=True),
                audience=self.audience, body=body,
            )
        if method == "GET":
            return self.client.get(path, headers=headers)
        return self.client.post(path, json=body, headers=headers)

    def expect(self, resp, status: int) -> Any:
        if resp.status_code != status:
            raise SystemExit(f"{resp.request.method} {resp.request.path}: HTTP {resp.status_code} {resp.get_data(as_text=True)}")
        return resp.get_json()


def _decide(api: Api, attestation_id: str) -> dict:
    return api.expect(api.admin("POST", "/admin/boundary/evaluate", {
        "attestation_id": attestation_id, "requested_capability": "secret.rotate",
        "context": {"request_parameters": {"app_id": "billing"}},
    }), 201)["decision"]


def _execute(state: dict, decision: dict, prior: dict | None, sequence: int) -> dict:
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.trust.execution import record_execution

    evidence = record_execution(
        BoundaryDecision.model_validate(decision), EXECUTOR, "secret.rotate", "success",
        _key(state["seeds"]["executor"]), issued_by="ctrl-1", sequence_no=1,
        execution_parameters={"secret_version": f"v{sequence}"},
        resource_id=RESOURCE, resource_action="rotate" if prior else "create",
        prior_resource_record=ExecutionEvidence.model_validate(prior) if prior else None,
        now=datetime.now(timezone.utc),
    )
    return evidence.model_dump(mode="json")


# ── populate: runs under the past release ───────────────────────────────────


def populate(state_path: Path, db_path: str | None, database_url: str | None = None) -> None:
    import genesis_mesh
    from genesis_mesh.crypto import generate_keypair, sign_model
    from genesis_mesh.models import (
        GenesisBlock, MembershipAttestation, NetworkAuthority, PolicyManifestRef, SovereignRevocationFeed,
    )

    now = datetime.now(timezone.utc)
    keys = {name: generate_keypair() for name in ("na", "operator", "partner", "executor")}
    genesis = GenesisBlock(
        network_name="upgrade-na", network_version="v1", root_public_key=keys["na"].public_key_b64,
        network_authority=NetworkAuthority(public_key=keys["na"].public_key_b64, valid_from=now,
                                           valid_to=now + timedelta(days=365)),
        policy_manifest=PolicyManifestRef(hash="sha256:upgrade", url=None),
    )
    genesis.signatures.append(sign_model(genesis, keys["na"].private_key, "root"))
    state: dict[str, Any] = {
        "written_by": getattr(genesis_mesh, "__version__", "unknown"),
        "seeds": {name: kp.private_key_b64 for name, kp in keys.items()},
        "genesis": genesis.model_dump(mode="json"),
    }
    out_of_band = _has_out_of_band()
    service = _service(state, db_path=db_path, database_url=database_url, out_of_band=out_of_band)
    api = Api(service, state["seeds"]["operator"])

    # Recognition of a partner sovereign, its attestations, and its revocation feed.
    state["treaty"] = api.expect(api.admin("POST", "/admin/recognition-treaties", {
        "subject_sovereign_id": PARTNER, "subject_public_keys": [keys["partner"].public_key_b64],
        "scope": {"allowed_roles": ["role:client"]}, "validity_hours": 24 * 365,
    }), 201)

    def partner_attestation(subject: str) -> dict:
        att = MembershipAttestation(
            attestation_id=str(uuid.uuid4()), issuer_sovereign_id=PARTNER, subject_id=subject,
            roles=["role:client"], status="active", issued_at=now, valid_from=now,
            expires_at=now + timedelta(days=365), issued_by="partner-key", claims={"region": "Zürich ✓"},
            signatures=[],
        )
        att.signatures.append(sign_model(att, keys["partner"].private_key, "partner-key"))
        return att.model_dump(mode="json")

    state["partner_live"] = partner_attestation("alice")
    state["partner_revoked"] = partner_attestation("bob")
    feed = SovereignRevocationFeed(
        feed_id=str(uuid.uuid4()), issuer_sovereign_id=PARTNER, sequence=1, issued_at=now,
        revoked_attestation_ids=[state["partner_revoked"]["attestation_id"]],
        revocation_reasons={state["partner_revoked"]["attestation_id"]: "compromise"}, issued_by="partner-key",
    )
    feed.signatures.append(sign_model(feed, keys["partner"].private_key, "partner-key"))
    state["feed"] = feed.model_dump(mode="json")
    api.expect(api.admin("POST", "/admin/sovereign-revocation-feeds/import", {"feed": state["feed"]}), 200)

    # NA attestations: one in use, one revoked.
    def issue(subject: str) -> dict:
        return api.expect(api.admin("POST", "/admin/attestations", {
            "subject_id": subject, "roles": ["role:client"],
            "claims": {"capabilities": ["secret.rotate"], "apps": ["billing"]}, "validity_hours": 24 * 365,
        }), 201)

    state["vendor"] = issue(VENDOR)
    state["vendor_revoked"] = issue("vendor-gone")
    api.expect(api.admin("POST", f"/admin/attestations/{state['vendor_revoked']['attestation_id']}/revoke",
                         {"reason": "offboarded"}), 200)

    # An active boundary policy, decisions under it, and a resource's execution chain.
    policy = api.expect(api.admin("POST", "/admin/boundary-policies", {
        "policy_id": POLICY_ID, "description": "Upgrade rehearsal — Zürich ✓",
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=365)).isoformat(),
        "selector": {"parent_kinds": ["attestation"], "capabilities": ["secret.*"]},
        "gates": [{"gate_id": "app", "gate_type": "attestation_claim.v1", "order": 0,
                   "config": {"path": "request_parameters.app_id", "claim": "apps"}}],
    }), 201)
    api.expect(api.admin("POST", f"/admin/boundary-policies/{POLICY_ID}/activate", {"version": policy["version"]}), 200)
    state["policy"] = policy
    api.expect(api.admin("POST", "/admin/evidence/executor-keys", {
        "key_id": "ctrl-1", "public_key": keys["executor"].public_key_b64, "executor_sovereign_id": EXECUTOR,
    }), 201)
    state["decisions"], state["executions"] = [], []
    prior = None
    for sequence in (1, 2):
        decision = _decide(api, state["vendor"]["attestation_id"])
        evidence = _execute(state, decision, prior, sequence)
        api.expect(api.client.post("/evidence/execution", json={"evidence": evidence}), 201)
        state["decisions"].append(decision)
        state["executions"].append(evidence)
        prior = evidence

    if out_of_band:
        # A 1.3+ store with its Stage 2 records: an observation judged by the past release.
        observer = _observer_key()
        state["seeds"]["observer"] = _seed(observer)
        api.expect(api.admin("POST", "/admin/evidence/executor-keys", {
            "key_id": "obs-1", "public_key": _pub(observer), "executor_sovereign_id": "cloud-observer",
            "role": "observer"}), 201)
        seen = api.expect(api.client.post("/evidence/observations", json={"observation": _observation(observer)}), 201)
        state["past_judgement"] = (seen.get("judgement") or {}).get("payload")

    state["data_policy"] = api.expect(api.admin("POST", "/admin/data-usage/policy", {
        "licensee_sovereign_id": PARTNER, "allowed_source_ids": ["db-prod"], "allowed_access_types": ["read"],
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=365)).isoformat(),
    }), 201)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    if hasattr(service.db, "close"):  # NADatabase.close arrived after 0.59
        service.db.close()
    print(f"populated by genesis-mesh {state['written_by']}: {db_path or 'PostgreSQL'}")


# ── verify: runs under the current release ───────────────────────────────────


def verify(state: dict, label: str, *, db_path: str | None = None, database_url: str | None = None) -> list[str]:
    from genesis_mesh.models import MembershipAttestation, RecognitionTreaty, SovereignRevocationFeed
    from genesis_mesh.models.boundary_policy import BoundaryPolicy
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.models.evidence_store import EvidenceEvent
    from genesis_mesh.na_service.db import expected_schema_version
    from genesis_mesh.trust.context import verify_boundary_decision
    from genesis_mesh.trust.evidence_store import ExecutorKey, verify_evidence_events
    from genesis_mesh.trust.treaty import verify_recognition_treaty, verify_sovereign_revocation_feed
    from genesis_mesh.workflows.db_migration import verify_database

    failures: list[str] = []

    def check(name: str, ok: bool, detail: Any = "") -> None:
        print(f"  [{label}] {'ok  ' if ok else 'FAIL'} {name}{'' if ok else f': {detail}'}")
        if not ok:
            failures.append(f"{label}: {name}: {detail}")

    service = _service(state, db_path=db_path, database_url=database_url, out_of_band=True, remediation=True,
                       grants=True)
    api = Api(service, state["seeds"]["operator"])
    na_key = _pub(_key(state["seeds"]["na"]))
    partner_key = _pub(_key(state["seeds"]["partner"]))

    check("schema migrated to the current version", service.db.schema_version() == expected_schema_version(),
          service.db.schema_version())
    report = verify_database(service.db, na_key, genesis=state["genesis"])
    check("na verify-db", report.ok, report.failures)

    treaty_id = state["treaty"]["treaty_id"]
    stored = api.client.get(f"/recognition-treaties/{treaty_id}").get_json()
    stored_treaty = stored.get("treaty", stored) if isinstance(stored, dict) else None
    check("treaty stored unchanged", stored_treaty == state["treaty"], stored)
    check("treaty verifies offline", verify_recognition_treaty(
        RecognitionTreaty.model_validate(state["treaty"]), [na_key]).accepted)
    v = api.client.post("/recognition-treaties/verify", json={"treaty": state["treaty"]}).get_json()
    check("treaty verifies on the NA", v.get("accepted") is True, v)

    def with_treaty(att: dict) -> dict:
        return api.client.post("/attestations/verify-with-treaty",
                               json={"attestation": att, "treaty": state["treaty"]}).get_json()

    r = with_treaty(state["partner_live"])
    check("partner attestation accepted under the treaty", r.get("accepted") is True, r)
    r = with_treaty(state["partner_revoked"])
    check("imported revocation still rejects the partner attestation",
          r.get("reason") == "attestation_locally_revoked", r)
    check("revocation feed verifies offline", verify_sovereign_revocation_feed(
        SovereignRevocationFeed.model_validate(state["feed"]), [partner_key]).accepted)
    stale = api.admin("POST", "/admin/sovereign-revocation-feeds/import", {"feed": state["feed"]})
    check("replayed feed rejected as stale", stale.status_code == 409
          and stale.get_json()["error"]["code"] == "stale_sequence", stale.get_json())

    revoked = api.client.get(f"/attestations/{state['vendor_revoked']['attestation_id']}").get_json()
    check("NA revocation kept", revoked.get("status") == "revoked", revoked)
    denied = api.admin("POST", "/admin/boundary/evaluate", {
        "attestation_id": state["vendor_revoked"]["attestation_id"], "requested_capability": "secret.rotate",
        "context": {"request_parameters": {"app_id": "billing"}}})
    check("revoked attestation is denied", denied.status_code == 201
          and denied.get_json()["decision"]["authorized"] is False, denied.get_json())

    active = api.expect(api.admin("GET", "/admin/boundary-policies/active"), 200)
    active_ids = json.dumps(active)
    check("boundary policy still active", POLICY_ID in active_ids, active)
    policy = BoundaryPolicy.model_validate(state["policy"])
    vendor = MembershipAttestation.model_validate(state["vendor"])
    for i, raw in enumerate(state["decisions"]):
        decision = BoundaryDecision.model_validate(raw)
        result = verify_boundary_decision(decision, [na_key], now=decision.decision_made_at,
                                          expected_policies=[policy], expected_attestation=vendor)
        check(f"decision {i + 1} from the old release verifies with its bindings", result.accepted
              and result.authorized, result.reason)

    # The store runs with its out-of-band records on: the policy history starts from the past
    # release's audit log, and a change seen outside the controlled path is judged against it.
    status = api.expect(api.admin("GET", "/admin/evidence/status"), 200)
    check("policy history backfilled from the audit log", status.get("policy_history_started") is not None
          and status.get("registry_healthy") is True, status)
    active = service.out_of_band_service.policy_history().active_at(datetime.now(timezone.utc)) or {}
    check("the past release's active policy is in the policy history", POLICY_ID in active, active)
    if "observer" in state["seeds"]:
        observer = _key(state["seeds"]["observer"])  # registered by the past release
    else:
        observer = _observer_key()
        api.expect(api.admin("POST", "/admin/evidence/executor-keys", {
            "key_id": "obs-1", "public_key": _pub(observer), "executor_sovereign_id": "cloud-observer",
            "role": "observer"}), 201)
    past = state.get("past_judgement")
    if past is not None:
        changes = api.expect(api.admin("GET", f"/admin/evidence/changes/{RESOURCE}"), 200)["changes"]
        check("the past release's judgement is in the resource's changes",
              any(c.get("record_id") == past["subject_id"] for c in changes), changes)
    seen = api.client.post("/evidence/observations", json={"observation": _observation(observer)})
    judged = (seen.get_json() or {}).get("judgement") or {}
    check("an observation is admitted and judged after the upgrade", seen.status_code == 201
          and judged.get("payload", {}).get("subject_kind") == "observation", seen.get_json())

    # 1.4: the judgement arms a remediation (no policy covers an observation here, so it is
    # indeterminate and alerts); the controller records its notice and its remediation.
    queue = api.expect(api.admin("GET", "/admin/evidence/remediations?state=remediation_due"), 200)["remediations"]
    judgement_id = judged.get("payload", {}).get("judgement_id")
    check("the new judgement's remediation is due", [q["subject_id"] for q in queue] == [judgement_id], queue)
    if past is not None:
        check("the past release's judgement is not remediated", all(
            q["subject_id"] != past["judgement_id"] for q in queue), queue)
    if queue:
        api.expect(api.admin("POST", f"/admin/evidence/remediations/{judgement_id}/notified",
                             {"channel": "rehearsal"}), 200)
        done = api.client.post("/evidence/remediations", json={"record": _remediation(state, queue[0])})
        check("a remediation record is admitted after the upgrade", done.status_code == 201
              and done.get_json()["remediation"]["state"] == "remediated", done.get_json())

    store = api.expect(api.admin("GET", "/admin/evidence/verify"), 200)
    check("evidence store verifies", store.get("verified") is True, store)
    lines = api.admin("GET", "/admin/evidence/export").get_data(as_text=True).splitlines()
    events = [EvidenceEvent.model_validate_json(line) for line in lines if line.strip()]
    kinds = {e.entry.entry_kind for e in events}
    check("the export holds the 1.4 remediation records", "remediation" in kinds, sorted(kinds))
    keys = {"ctrl-1": ExecutorKey(key_id="ctrl-1", public_key=_pub(_key(state["seeds"]["executor"])),
                                  executor_sovereign_id=EXECUTOR),
            "obs-1": ExecutorKey(key_id="obs-1", public_key=_pub(observer), executor_sovereign_id="cloud-observer",
                                 role="observer")}
    offline = verify_evidence_events(events, na_public_keys=[na_key], executor_keys=keys)
    check("evidence export verifies offline", offline.verified, offline.failures)

    decision = _decide(api, state["vendor"]["attestation_id"])
    check("new decision under the old policy and attestation", decision["authorized"] is True, decision)
    head = api.admin("GET", f"/admin/evidence/resources/{RESOURCE}").get_json()
    entries = head.get("entries", [])
    last = [e for e in entries if e.get("entry", {}).get("entry_kind") == "execution"][-1]["payload"]
    evidence = _execute(state, decision, last, 3)
    sub = api.client.post("/evidence/execution", json={"evidence": evidence})
    check("resource chain continues after the upgrade", sub.status_code == 201
          and evidence["resource_sequence"] == 3, sub.get_json())
    history = api.admin("GET", f"/admin/evidence/resources/{RESOURCE}").get_json()
    check("resource history verifies", history.get("verification", {}).get("verified") is True,
          history.get("verification"))

    # 1.6: a grant under the past release's attestation and policy, used while the NA is (as far as the
    # holder knows) unreachable; the NA places the use after the past release's records of the resource.
    issued = api.admin("POST", "/admin/grants", {
        "bearer_key_id": "ctrl-1", "capabilities": ["secret.rotate"], "attestation_id": state["vendor"]["attestation_id"],
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "max_uses": 2,
        "parameter_envelope": {"app_id": {"one_of": ["billing"]}},
    })
    check("a grant is issued under the past release's policy and attestation", issued.status_code == 201,
          issued.get_json())
    if issued.status_code == 201:
        use = _grant_use(state, issued.get_json())
        admitted = api.client.post("/evidence/grant-executions", json={"evidence": use})
        check("a grant use continues the resource chain after the upgrade", admitted.status_code == 201
              and admitted.get_json().get("resource_sequence") == 4, admitted.get_json())
        feed = api.client.get("/sovereign-revocation-feed").get_json()
        check("the revocation feed lists revoked grants", feed.get("revoked_grant_ids") == [], feed)
        lines = api.admin("GET", "/admin/evidence/export").get_data(as_text=True).splitlines()
        events = [EvidenceEvent.model_validate_json(line) for line in lines if line.strip()]
        offline = verify_evidence_events(events, na_public_keys=[na_key], executor_keys=keys)
        check("the export with the grant and its use verifies offline", offline.verified
              and offline.grant_executions == 1, offline.failures)

    # 1.5: the genesis key is the first entry of the key history, and an audit pack of the whole
    # store, written by the past release and this one, verifies offline from the root key and the
    # anchors an auditor would hold.
    from genesis_mesh.models.audit_pack import MANIFEST_FILE, AuditPackManifest
    from genesis_mesh.models.evidence_store import StoreAnchor
    from genesis_mesh.workflows.audit_pack import verify_audit_pack

    view = api.client.get("/na/key-history").get_json()
    check("the genesis key is the first entry of the key history", [k["public_key"] for k in view["keys"]]
          == [na_key] and view["keys"][0]["valid_to_enforced"] is False, view.get("keys"))
    api.admin("POST", "/admin/evidence/anchors", {})
    pack = api.admin("POST", "/admin/evidence/audit-pack", {})
    if pack.status_code != 200:
        check("an audit pack of the upgraded store is written", False, pack.get_json())
    else:
        body = pack.get_json()
        files = {path: text.encode("utf-8") for path, text in body["files"].items()}
        files[MANIFEST_FILE] = AuditPackManifest.model_validate(body["manifest"]).file_bytes()
        held = [StoreAnchor.model_validate(a) for a in api.expect(
            api.admin("GET", "/admin/evidence/anchors?limit=1000"), 200)["anchors"]]
        result = verify_audit_pack(files, root_public_key=state["genesis"]["root_public_key"], held_anchors=held)
        check("an audit pack of the upgraded store verifies offline", result.verified, result.failures)
    service.db.close()
    return failures


def _observer_key():
    import nacl.signing

    return nacl.signing.SigningKey.generate()


def _observation(key) -> dict:
    """A signed observation of the rehearsal resource (1.3+)."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.out_of_band import ObservationRecord

    now = datetime.now(timezone.utc)
    record = ObservationRecord(
        observer_sovereign_id="cloud-observer", resource_id=RESOURCE, action="rotate", capability="secret.rotate",
        changed_at=now - timedelta(minutes=1), observed_at=now, source="cloud-activity-log",
        source_event_id=str(uuid.uuid4()), metadata={"secret_version": "v9"},
    )
    return record.model_copy(update={"signature": sign_model(record, key, "obs-1")}).to_wire()


def _grant_use(state: dict, issued: dict) -> dict:
    """The holder's signed use of the grant (1.6+): the first of its chain, on the rehearsal resource."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.grants import CapabilityGrant, GrantExecutionEvidence, TimeToken

    grant = CapabilityGrant.model_validate(issued["grant"])
    record = GrantExecutionEvidence(
        grant_id=grant.grant_id, grant_digest=grant.digest(), use_sequence=1, executor_sovereign_id=EXECUTOR,
        capability="secret.rotate", request_parameters={"app_id": "billing"}, resource_id=RESOURCE,
        resource_action="rotate", executed_at=datetime.now(timezone.utc),
        time_token=TimeToken.model_validate(issued["time_token"]), outcome="success",
        execution_parameters={"secret_version": "v4"},
    )
    return record.model_copy(update={"signature": sign_model(record, _key(state["seeds"]["executor"]), "ctrl-1")}).to_wire()


def _remediation(state: dict, due: dict) -> dict:
    """The controller's signed record of an alert-only remediation (1.4+)."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.remediation import RemediationRecord

    record = RemediationRecord(
        executor_sovereign_id=EXECUTOR, subject_kind="judgement", subject_id=due["subject_id"],
        change_kind=due["change_kind"], change_id=due["change_id"], resource_id=due["resource_id"],
        outcome="alerted", steps="none", remediated_at=datetime.now(timezone.utc),
    )
    return record.model_copy(update={"signature": sign_model(record, _key(state["seeds"]["executor"]), "ctrl-1")}).to_wire()


def _backup(src: str, dst: str) -> None:
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)


def _venv(work: Path) -> Path:
    venv = work / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _populate_with(python: Path, work: Path, env_path: Path | None = None) -> tuple[Path, Path]:
    import os

    db, state_path = work / "na.db", work / "state.json"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if env_path is not None:
        env["PYTHONPATH"] = str(env_path)
    # Run from the temporary directory so the release under test, not this checkout, is imported.
    script = work / "rehearsal.py"
    shutil.copy(Path(__file__).resolve(), script)
    subprocess.run([str(python), str(script), "populate", "--state", str(state_path), "--db", str(db)],
                   check=True, cwd=work, env=env)
    return db, state_path


def installed(wheel: str) -> int:
    """Install a built wheel in a clean virtualenv and run a full NA workload from it."""
    work = Path(tempfile.mkdtemp(prefix="gm-installed-"))
    try:
        python = _venv(work)
        subprocess.run([str(python), "-m", "pip", "install", "-q", str(Path(wheel).resolve())], check=True)
        _, state_path = _populate_with(python, work)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        print(f"PASSED: the installed package ({state['written_by']}) runs a Network Authority")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rehearse(version: str, postgres_url: str | None, keep: bool) -> int:
    work = Path(tempfile.mkdtemp(prefix=f"gm-upgrade-{version}-"))
    try:
        repo = Path(__file__).resolve().parents[1]
        src = work / "src"
        src.mkdir()
        archive = subprocess.run(["git", "-C", str(repo), "archive", f"v{version}"], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(src)], input=archive.stdout, check=True)
        python = _venv(work)
        subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(src / "requirements.txt")], check=True)
        db, state_path = _populate_with(python, work, env_path=src)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["written_by"] != version:
            raise SystemExit(f"populated by {state['written_by']}, expected {version}")
        backup = work / "backup.db"
        _backup(str(db), str(backup))

        print(f"upgrade from {version}:")
        failures = verify(state, "upgraded", db_path=str(db))
        restored = work / "restored.db"
        shutil.copy(backup, restored)
        failures += verify(state, "restored backup", db_path=str(restored))
        if postgres_url:
            from genesis_mesh.na_service.db import NADatabase
            from genesis_mesh.workflows.db_migration import migrate_sqlite_to_postgres

            pg_source = work / "pg-source.db"
            shutil.copy(backup, pg_source)
            NADatabase(str(pg_source)).migrate()
            schema = f"upgrade_{version.replace('.', '_')}_{uuid.uuid4().hex[:6]}"
            url = _with_schema(postgres_url, schema)
            try:
                report = migrate_sqlite_to_postgres(str(pg_source), url, na_public_key=_pub(_key(state["seeds"]["na"])))
                ok = report.get("verification", {}).get("ok", True)
                print(f"  [postgres] {'ok  ' if ok else 'FAIL'} migrate-db to PostgreSQL")
                if not ok:
                    failures.append(f"postgres: migrate-db: {report}")
                failures += verify(state, "postgres", database_url=url)
            finally:
                _drop_schema(postgres_url, schema)
        print(f"{'PASSED' if not failures else 'FAILED'}: upgrade from {version} ({len(failures)} failures)")
        return 0 if not failures else 1
    finally:
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def _with_schema(url: str, schema: str) -> str:
    import psycopg
    from urllib.parse import quote

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote(f'-csearch_path={schema}')}"


def _drop_schema(url: str, schema: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    pop = sub.add_parser("populate")
    pop.add_argument("--state", required=True)
    pop.add_argument("--db", required=True)
    parser.add_argument("--from", dest="version")
    parser.add_argument("--installed", metavar="WHEEL")
    parser.add_argument("--postgres-url")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.command == "populate":
        populate(Path(args.state), args.db)
        return 0
    if args.installed:
        return installed(args.installed)
    if not args.version:
        parser.error("--from VERSION or --installed WHEEL is required")
    return rehearse(args.version, args.postgres_url, args.keep)


if __name__ == "__main__":
    sys.exit(main())
