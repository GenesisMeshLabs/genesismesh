"""Exactly-once guarantees under concurrency (v0.60).

Each test opens several independent connections to one database -- separate
``NADatabase`` objects, as separate gunicorn workers or NA instances would
have -- and races them. The guarantees must come from the database, so they
hold on SQLite (one file) and on PostgreSQL (run with
``GENESIS_MESH_TEST_DATABASE_URL``; see ``pg_support``).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models import JoinCertificate, SovereignRevocationFeed
from genesis_mesh.models.boundary_policy import BoundaryPolicy, PolicySelector
from genesis_mesh.models.evidence_store import EvidenceStoreEntry
from genesis_mesh.na_service.db import NADatabase
from genesis_mesh.na_service.errors import ConflictError
from genesis_mesh.na_service.rate_limit import DatabaseRateLimiter
from genesis_mesh.na_service.server import NetworkAuthorityService

WORKERS = 8


def _race(n: int, fn: Callable[[int], Any]) -> list[Any]:
    """Run ``fn(i)`` for i in range(n) as simultaneously as possible."""
    barrier = threading.Barrier(n)

    def run(i: int) -> Any:
        barrier.wait()
        try:
            return fn(i)
        except Exception as exc:  # noqa: BLE001 - the outcome is what the test checks
            return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "shared.db")
    NADatabase(path).migrate()
    return path


@pytest.fixture
def instances(db_path):
    """WORKERS independent connections to one database."""
    dbs = [NADatabase(db_path) for _ in range(WORKERS)]
    for db in dbs:
        db.migrate()
    yield dbs
    for db in dbs:
        db.close()


def test_a_nonce_is_claimed_exactly_once(instances):
    now = datetime.now(timezone.utc)
    results = _race(WORKERS, lambda i: instances[i].claim_nonce("admin:ops", "n-1", now))
    assert results.count(True) == 1
    assert results.count(False) == WORKERS - 1


def test_an_invite_token_is_used_exactly_once(instances):
    token = instances[0].create_invite_token(["role:client"], 24, 1)
    results = _race(WORKERS, lambda i: instances[i].use_invite_token(token.token_id, f"node-{i}"))
    assert sum(1 for r in results if r is not None and not isinstance(r, Exception)) == 1


def test_a_job_lease_has_one_holder(instances):
    results = _race(WORKERS, lambda i: instances[i].claim_lease("retention", f"instance-{i}", 60))
    assert results.count(True) == 1
    holder = instances[0].get_lease("retention")["holder"]
    winner = results.index(True)
    assert holder == f"instance-{winner}"
    # The holder renews; a different instance cannot take it before expiry.
    assert instances[winner].claim_lease("retention", holder, 60)
    other = (winner + 1) % WORKERS
    assert not instances[other].claim_lease("retention", f"instance-{other}", 60)
    # After expiry anyone may take it.
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    assert instances[other].claim_lease("retention", f"instance-{other}", 60, now=later)


def test_a_revocation_feed_sequence_is_imported_once(instances):
    issuer = "peer-sovereign"

    def save(i: int) -> Any:
        feed = SovereignRevocationFeed(
            feed_id=str(uuid.uuid4()), issuer_sovereign_id=issuer, sequence=1,
            issued_at=datetime.now(timezone.utc), revoked_attestation_ids=[f"att-{i}"],
            revocation_reasons={}, issued_by="k", signatures=[],
        )
        instances[i].save_sovereign_revocation_feed(feed)
        return True

    results = _race(WORKERS, save)
    assert results.count(True) == 1
    assert len(instances[0].list_sovereign_revocation_feeds(issuer)) == 1


def test_rate_limit_is_shared_across_instances(instances):
    limiters = [DatabaseRateLimiter(db, clock=lambda: 1_000_000.0) for db in instances]
    per_instance = 10
    results = _race(
        WORKERS,
        lambda i: [limiters[i].allow("admin:10.0.0.1", 25, 60) for _ in range(per_instance)],
    )
    allowed = sum(sum(1 for ok in r if ok) for r in results)
    assert allowed == 25  # not 25 per instance


def _policy(policy_id: str, version: int) -> BoundaryPolicy:
    now = datetime.now(timezone.utc)
    return BoundaryPolicy(
        policy_id=policy_id, version=version, valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=1), selector=PolicySelector(), gates=[],
        issued_at=now, issued_by="na", issuer_sovereign_id="TEST",
    )


def test_a_policy_version_number_is_taken_once(instances):
    results = _race(WORKERS, lambda i: instances[i].save_boundary_policy(_policy("p", 1)) or True)
    assert results.count(True) == 1
    assert len(instances[0].list_boundary_policy_rows("p")) == 1


def test_only_one_policy_version_ends_up_active(instances):
    for version in range(1, WORKERS + 1):
        instances[0].save_boundary_policy(_policy("p", version))
    results = _race(WORKERS, lambda i: instances[i].activate_boundary_policy("p", i + 1))
    assert any(not isinstance(r, Exception) for r in results)
    active = [r for r in instances[0].list_boundary_policy_rows("p") if r["active"]]
    assert len(active) == 1


def test_evidence_appends_form_one_gap_free_chain(instances):
    def append(i: int) -> Any:
        def build(seq: int, prev: str | None) -> EvidenceStoreEntry:
            return EvidenceStoreEntry(
                store_sequence=seq, entry_kind="decision", recorded_at=datetime.now(timezone.utc),
                payload_digest="0" * 64, prev_entry_digest=prev, decision_id=f"d-{i}",
            )
        return instances[i].append_evidence_entries([(build, {"i": i})])

    results = _race(WORKERS, append)
    assert not [r for r in results if isinstance(r, Exception)]
    rows = instances[0].search_evidence({}, limit=100)
    sequences = [r["entry"].store_sequence for r in rows]
    assert sequences == list(range(1, WORKERS + 1))
    for prev, cur in zip(rows, rows[1:]):
        assert cur["entry"].prev_entry_digest == prev["entry"].digest()


def test_concurrent_revocations_all_land_in_distinct_crl_sequences(na_service, db_path):
    """N instances revoke N different certificates at once: none is lost."""
    services = [
        NetworkAuthorityService(
            genesis_block=na_service.genesis_block, na_private_key=na_service.signer,
            key_id=na_service.key_id, db_path=db_path,
            operator_public_keys=na_service.operator_public_keys,
            operator_key_tiers=na_service.operator_key_tiers,
        )
        for _ in range(WORKERS)
    ]
    services[0]._get_or_create_active_crl()
    cert_ids = []
    for _ in range(WORKERS):
        node = generate_keypair()
        now = datetime.now(timezone.utc)
        cert = JoinCertificate(
            cert_id=str(uuid.uuid4()), node_public_key=node.public_key_b64, network_name="TEST",
            roles=["role:client"], issued_at=now, expires_at=now + timedelta(hours=1),
            issued_by=na_service.key_id, signatures=[],
        )
        services[0].db.issue_cert(cert, "127.0.0.1")
        cert_ids.append(cert.cert_id)

    def revoke(i: int) -> Any:
        svc = services[i]
        return svc.publish_crl(lambda: svc.db.revoke_cert(cert_ids[i], "key_compromise", svc.key_id))

    results = _race(WORKERS, revoke)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors or all(isinstance(e, ConflictError) for e in errors)
    final = services[0].db.get_active_crl()
    revoked = {rc.certificate_id for rc in final.revoked_certificates}
    landed = [cid for cid, r in zip(cert_ids, results) if not isinstance(r, Exception)]
    assert set(landed) <= revoked
    rows = services[0].db.conn.execute("SELECT sequence, active FROM crl_versions ORDER BY sequence").fetchall()
    sequences = [int(r["sequence"]) for r in rows]
    assert sequences == list(range(0, len(sequences)))
    assert [int(r["active"]) for r in rows].count(1) == 1 and int(rows[-1]["active"]) == 1
    for svc in services:
        svc.db.close()


def test_identical_evidence_raced_on_several_instances_is_stored_once(tmp_path):
    """Controllers retry; a retry can land on another instance at the same moment."""
    from .test_evidence_store import Controller, _client, _decide
    from .test_na_boundary_policy import _make_service

    shared = str(tmp_path / "evidence.db")
    first = _make_service(evidence_store="on", db_path=shared)
    client = _client(first)
    record = Controller(client).record(_decide(client))
    services = [first] + [
        NetworkAuthorityService(
            genesis_block=first.genesis_block, na_private_key=first.signer, key_id=first.key_id,
            db_path=shared, operator_public_keys=first.operator_public_keys,
            operator_key_tiers=first.operator_key_tiers, evidence_store="on",
        )
        for _ in range(WORKERS - 1)
    ]
    raw = record.model_dump(mode="json")
    results = _race(WORKERS, lambda i: services[i].evidence_store_service.submit_execution(raw))
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors[:3]
    created = [created for _, created in results]
    assert created.count(True) == 1 and created.count(False) == WORKERS - 1
    assert first.db.evidence_stats()["entries"] == 3  # decision, justification, one execution
    for svc in services[1:]:
        svc.db.close()
