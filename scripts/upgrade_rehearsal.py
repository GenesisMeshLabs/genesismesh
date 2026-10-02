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
3. Start the current release on the database (``verify``): migrations run,
   and every record and decision is checked through the current HTTP routes
   and offline verifiers, then the resource chain is extended.
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


def _service(state: dict, *, db_path: str | None = None, database_url: str | None = None):
    from genesis_mesh.models import GenesisBlock
    from genesis_mesh.na_service.server import NetworkAuthorityService

    kwargs: dict[str, Any] = {}
    if database_url:
        kwargs["database_url"] = database_url
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

    def admin(self, method: str, path: str, body: dict | None = None):
        from genesis_mesh.crypto import sign_data

        body = body or {}
        ts = datetime.now(timezone.utc).isoformat()
        nonce = str(uuid.uuid4())
        canonical = json.dumps({"body": body, "key_id": "ops", "timestamp": ts, "nonce": nonce},
                               sort_keys=True, separators=(",", ":"))
        headers = {"X-Admin-Key-Id": "ops", "X-Admin-Timestamp": ts, "X-Admin-Nonce": nonce,
                   "X-Admin-Signature": sign_data(canonical.encode("utf-8"), self.key)}
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


def populate(state_path: Path, db_path: str) -> None:
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
    api = Api(_service(state, db_path=db_path), state["seeds"]["operator"])

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

    state["data_policy"] = api.expect(api.admin("POST", "/admin/data-usage/policy", {
        "licensee_sovereign_id": PARTNER, "allowed_source_ids": ["db-prod"], "allowed_access_types": ["read"],
        "valid_from": (now - timedelta(hours=1)).isoformat(), "valid_until": (now + timedelta(days=365)).isoformat(),
    }), 201)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"populated by genesis-mesh {state['written_by']}: {db_path}")


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

    service = _service(state, db_path=db_path, database_url=database_url)
    api = Api(service, state["seeds"]["operator"])
    na_key = _pub(_key(state["seeds"]["na"]))
    partner_key = _pub(_key(state["seeds"]["partner"]))

    check("schema migrated to the current version", service.db.schema_version() == expected_schema_version(),
          service.db.schema_version())
    report = verify_database(service.db, na_key)
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
    check("NA revocation kept", (revoked.get("attestation", revoked) or {}).get("status") == "revoked"
          or revoked.get("status") == "revoked", revoked)
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

    store = api.expect(api.admin("GET", "/admin/evidence/verify"), 200)
    check("evidence store verifies", store.get("verified") is True, store)
    lines = api.admin("GET", "/admin/evidence/export").get_data(as_text=True).splitlines()
    events = [EvidenceEvent.model_validate_json(line) for line in lines if line.strip()]
    keys = {"ctrl-1": ExecutorKey(key_id="ctrl-1", public_key=_pub(_key(state["seeds"]["executor"])),
                                  executor_sovereign_id=EXECUTOR)}
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
    service.db.close()
    return failures


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
