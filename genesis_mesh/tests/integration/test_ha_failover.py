"""Integration test: losing an NA instance loses nothing (v0.60).

Two NA instances (gunicorn, two workers each, HA mode) share one PostgreSQL
database behind nginx. Decisions, execution evidence on one secret's chain,
and certificate revocations run continuously through the load balancer;
instance A is killed mid-run (SIGKILL: master and workers). Traffic continues
through B. Afterwards every acknowledged decision, evidence record and
revocation is present exactly once, the CRL sequences are gap-free with one
active list, and the whole evidence store verifies with the NA key.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import nacl.encoding
import nacl.signing
import pytest
import requests

from genesis_mesh.crypto import generate_keypair, sign_data
from genesis_mesh.models import JoinCertificate
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.na_service.db import NADatabase
from genesis_mesh.trust.execution import record_execution
from genesis_mesh.workflows.db_migration import verify_database

from genesis_mesh.tests.pg_support import fresh_postgres_url
from genesis_mesh.tests.integration.ha_cluster import HACluster, get_json

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(shutil.which("nginx") is None, reason="needs nginx"),
]

RUN_SECONDS_BEFORE_KILL = 4.0
RUN_SECONDS_AFTER_KILL = 4.0
SECRET = "kv:ha-vault/api-key"


class Client:
    """Talks to the load balancer like a controller would, retrying transport failures."""

    def __init__(self, cluster: HACluster) -> None:
        self.url = cluster.url
        self.operator = cluster.operator
        self.key_id = cluster.operator_key_id
        self.session = requests.Session()

    def _headers(self, body: dict) -> dict[str, str]:
        ts = datetime.now(timezone.utc).isoformat()
        nonce = str(uuid.uuid4())
        canonical = json.dumps(
            {"body": body, "key_id": self.key_id, "timestamp": ts, "nonce": nonce},
            sort_keys=True, separators=(",", ":"),
        )
        return {
            "X-Admin-Key-Id": self.key_id, "X-Admin-Timestamp": ts, "X-Admin-Nonce": nonce,
            "X-Admin-Signature": sign_data(canonical.encode(), self.operator.private_key),
            "X-Test-Client": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}",
        }

    def post(self, path: str, body: dict, *, admin: bool = True, attempts: int = 8) -> Optional[requests.Response]:
        """POST with fresh admin signatures per attempt; None if every attempt failed in transport."""
        for _ in range(attempts):
            headers = self._headers(body) if admin else {"X-Test-Client": f"10.9.{uuid.uuid4().int % 250}.1"}
            try:
                resp = self.session.post(self.url + path, json=body, headers=headers, timeout=10)
            except requests.RequestException:
                time.sleep(0.1)
                continue
            if resp.status_code in (502, 503, 504):
                time.sleep(0.1)
                continue
            return resp
        return None


def test_killing_an_instance_loses_and_duplicates_nothing(request):
    cluster = HACluster(fresh_postgres_url(request))
    cluster.start()
    request.addfinalizer(cluster.stop)
    client = Client(cluster)

    # Setup through the load balancer.
    att = client.post("/admin/attestations", {
        "subject_id": "vendor-ha", "roles": ["role:client"],
        "claims": {"capabilities": ["secret.manage"], "apps": ["billing"]},
    })
    assert att is not None and att.status_code == 201, att and att.text
    attestation_id = att.json()["attestation_id"]
    controller_key = nacl.signing.SigningKey.generate()
    reg = client.post("/admin/evidence/executor-keys", {
        "key_id": "ctrl", "executor_sovereign_id": "controller",
        "public_key": controller_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode(),
    })
    assert reg is not None and reg.status_code == 201

    db = NADatabase(database_url=cluster.database_url)
    request.addfinalizer(db.close)
    cert_ids = []
    for _ in range(400):
        now = datetime.now(timezone.utc)
        cert = JoinCertificate(
            cert_id=str(uuid.uuid4()), node_public_key=generate_keypair().public_key_b64, network_name="HA-NET",
            roles=["role:client"], issued_at=now, expires_at=now + timedelta(hours=1),
            issued_by=cluster.key_id, signatures=[],
        )
        db.issue_cert(cert, "127.0.0.1")
        cert_ids.append(cert.cert_id)

    stop = threading.Event()
    acked: dict[str, list[Any]] = {"decisions": [], "evidence": [], "revoked": []}
    errors: list[str] = []

    def decide() -> Optional[BoundaryDecision]:
        resp = client.post("/admin/boundary/evaluate", {
            "attestation_id": attestation_id, "requested_capability": "secret.manage",
            "context": {"request_parameters": {"app_id": "billing"}},
        })
        if resp is None:
            return None
        if resp.status_code != 201:
            errors.append(f"evaluate {resp.status_code} {resp.text[:200]}")
            return None
        decision = BoundaryDecision.model_validate(resp.json()["decision"])
        acked["decisions"].append(decision.decision_id)
        return decision

    def decisions_worker() -> None:
        while not stop.is_set():
            decide()

    def evidence_worker() -> None:
        prior = None
        while not stop.is_set():
            decision = decide()
            if decision is None:
                continue
            record = record_execution(
                decision, "controller", "secret.manage", "success", controller_key, issued_by="ctrl",
                execution_parameters={"secret_version": f"v{len(acked['evidence']) + 1}"},
                resource_id=SECRET, resource_action="rotate" if prior else "create",
                prior_resource_record=prior,
            )
            body = {"evidence": record.model_dump(mode="json")}
            resp = client.post("/evidence/execution", body, admin=False)
            if resp is None:
                continue  # never acknowledged; an identical resubmission would be a duplicate-safe retry
            if resp.status_code not in (200, 201):
                errors.append(f"evidence {resp.status_code} {resp.text[:200]}")
                continue
            acked["evidence"].append(record.evidence_id)
            prior = record

    def revocation_worker() -> None:
        for cert_id in cert_ids:
            if stop.is_set():
                return
            resp = client.post("/admin/revoke", {"cert_id": cert_id, "reason": "key_compromise"})
            if resp is None:
                continue
            if resp.status_code != 200:
                errors.append(f"revoke {resp.status_code} {resp.text[:200]}")
                continue
            acked["revoked"].append(cert_id)
            time.sleep(0.01)

    threads = [threading.Thread(target=t) for t in (decisions_worker, decisions_worker, evidence_worker, revocation_worker)]
    for t in threads:
        t.start()
    time.sleep(RUN_SECONDS_BEFORE_KILL)
    before = {k: len(v) for k, v in acked.items()}
    cluster.kill("na-a")
    killed_at = time.monotonic()
    time.sleep(RUN_SECONDS_AFTER_KILL)
    stop.set()
    for t in threads:
        t.join(timeout=60)
    after = {k: len(v) for k, v in acked.items()}
    print(f"\nHA run: acknowledged before kill {before}, total {after}")

    # Traffic kept flowing through B after A died.
    assert all(after[k] > before[k] for k in after), (before, after)
    assert not errors, errors[:5]
    status, body = get_json(cluster.instances[1].url + "/readyz")
    assert status == 200 and body["database"]["writable"]
    assert time.monotonic() - killed_at >= RUN_SECONDS_AFTER_KILL

    # Exactly once: every acknowledged item stored once, nothing duplicated.
    rows = db.conn.execute(
        "SELECT decision_id, COUNT(*) AS n FROM evidence_entries WHERE entry_kind = 'decision' GROUP BY decision_id"
    ).fetchall()
    stored_decisions = {r["decision_id"]: int(r["n"]) for r in rows}
    assert all(n == 1 for n in stored_decisions.values())
    assert set(acked["decisions"]) <= set(stored_decisions)
    evidence_rows = db.conn.execute(
        "SELECT evidence_id, resource_sequence FROM evidence_entries WHERE entry_kind = 'execution' ORDER BY resource_sequence"
    ).fetchall()
    assert [r["evidence_id"] for r in evidence_rows] == acked["evidence"]
    assert [int(r["resource_sequence"]) for r in evidence_rows] == list(range(1, len(evidence_rows) + 1))
    active_crl = db.get_active_crl()
    assert set(acked["revoked"]) <= {rc.certificate_id for rc in active_crl.revoked_certificates}

    # The whole store, the CRL history and the policies verify with the NA key.
    report = verify_database(db, cluster.na_public_key)
    assert report.ok, report.failures
