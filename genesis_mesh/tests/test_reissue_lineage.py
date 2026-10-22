"""Re-issue lineage for attestations and treaties (v1.8.0, migration 020).

At a key succession the NA re-issues the records its old key signed under new
IDs. These tests cover the storage side: the lineage columns, the
compare-and-set re-issue, revocation of a whole lineage (also racing a
re-issue), lists that show only the newest copy, and the routes.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import sign_model
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from genesis_mesh.na_service import db as db_module
from genesis_mesh.na_service.db import NADatabase

from .test_na_boundary_policy import _make_service, _post

SUBJECT = "vendor-acme"


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


def _attestation(na_service, *, issued_at: datetime | None = None) -> MembershipAttestation:
    now = datetime.now(timezone.utc)
    issued = issued_at or now - timedelta(days=2)
    att = MembershipAttestation(
        attestation_id=str(uuid.uuid4()),
        issuer_sovereign_id=na_service.genesis_block.network_name,
        subject_id=SUBJECT,
        roles=["role:client"],
        status="active",
        issued_at=issued,
        valid_from=issued,
        expires_at=now + timedelta(days=30),
        issued_by=na_service.key_id,
    )
    att.signatures.append(sign_model(att, na_service.na_private_key, na_service.key_id))
    return att


def _reissued(na_service, previous: MembershipAttestation) -> MembershipAttestation:
    """A copy of ``previous`` under a new ID, issued now (what the re-issue job signs)."""
    now = datetime.now(timezone.utc)
    att = previous.model_copy(update={
        "attestation_id": str(uuid.uuid4()), "issued_at": now, "valid_from": now, "signatures": []})
    att.signatures.append(sign_model(att, na_service.na_private_key, na_service.key_id))
    return att


def _treaty(na_service, *, treaty_id: str | None = None, issued_at: datetime | None = None) -> RecognitionTreaty:
    now = datetime.now(timezone.utc)
    issued = issued_at or now - timedelta(days=2)
    treaty = RecognitionTreaty(
        treaty_id=treaty_id or str(uuid.uuid4()),
        issuer_sovereign_id=na_service.genesis_block.network_name,
        subject_sovereign_id="partner",
        subject_public_keys=["partner-key"],
        scope=RecognitionTreatyScope(allowed_roles=["role:client"]),
        issued_at=issued,
        valid_from=issued,
        expires_at=now + timedelta(days=30),
        issued_by=na_service.key_id,
    )
    treaty.signatures.append(sign_model(treaty, na_service.na_private_key, na_service.key_id))
    return treaty


def _listed_ids(db, **filters) -> set[str]:
    return {row["attestation"].attestation_id for row in db.list_membership_attestations(**filters)}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_a_new_attestation_starts_its_own_lineage(na_service):
    att = _attestation(na_service)
    na_service.db.save_membership_attestation(att)
    row = na_service.db.get_membership_attestation(att.attestation_id)
    assert row["lineage_id"] == att.attestation_id
    assert row["reissued_from"] is None and row["superseded_by"] is None
    assert na_service.db.membership_attestation_lineage(att.attestation_id) == [att.attestation_id]


def test_a_reissue_supersedes_the_previous_copy_which_stays_active(na_service):
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    new = _reissued(na_service, old)
    assert db.reissue_membership_attestation(old.attestation_id, new) is True

    old_row = db.get_membership_attestation(old.attestation_id)
    new_row = db.get_membership_attestation(new.attestation_id)
    # The previous copy keeps its status (grants and decisions rest on its ID);
    # superseded_by only points at its successor.
    assert old_row["status"] == "active" and old_row["superseded_by"] == new.attestation_id
    assert new_row["status"] == "active" and new_row["reissued_from"] == old.attestation_id
    assert new_row["lineage_id"] == old.attestation_id
    assert db.membership_attestation_lineage(new.attestation_id) == [old.attestation_id, new.attestation_id]
    # Lists show the newest copy; the full lineage on request.
    assert _listed_ids(db) == {new.attestation_id}
    assert _listed_ids(db, status="active") == {new.attestation_id}
    assert _listed_ids(db, include_superseded=True) == {old.attestation_id, new.attestation_id}


def test_a_lineage_can_be_reissued_again(na_service):
    db = na_service.db
    first = _attestation(na_service)
    db.save_membership_attestation(first)
    second = _reissued(na_service, first)
    third = _reissued(na_service, second)
    assert db.reissue_membership_attestation(first.attestation_id, second)
    assert db.reissue_membership_attestation(second.attestation_id, third)
    assert db.get_membership_attestation(third.attestation_id)["lineage_id"] == first.attestation_id
    assert db.membership_attestation_lineage(first.attestation_id) == [
        first.attestation_id, second.attestation_id, third.attestation_id]
    assert _listed_ids(db) == {third.attestation_id}


@pytest.mark.parametrize("state", ["revoked", "superseded", "unknown"])
def test_a_reissue_stores_nothing_unless_the_previous_copy_is_current(na_service, state):
    db = na_service.db
    old = _attestation(na_service)
    if state != "unknown":
        db.save_membership_attestation(old)
    if state == "revoked":
        db.revoke_membership_attestation(old.attestation_id, "offboarded")
    if state == "superseded":
        assert db.reissue_membership_attestation(old.attestation_id, _reissued(na_service, old))
    new = _reissued(na_service, old)
    assert db.reissue_membership_attestation(old.attestation_id, new) is False
    assert db.get_membership_attestation(new.attestation_id) is None


def test_a_reissue_under_an_existing_id_changes_nothing(na_service):
    db = na_service.db
    old, other = _attestation(na_service), _attestation(na_service)
    db.save_membership_attestation(old)
    db.save_membership_attestation(other)
    clash = _reissued(na_service, old).model_copy(update={"attestation_id": other.attestation_id})
    with pytest.raises(Exception):
        db.reissue_membership_attestation(old.attestation_id, clash)
    # The transaction rolled back: the previous copy is not marked superseded.
    assert db.get_membership_attestation(old.attestation_id)["superseded_by"] is None
    assert db.get_membership_attestation(other.attestation_id)["attestation"] == other


@pytest.mark.parametrize("revoke", ["old", "new"])
def test_revoking_any_copy_revokes_the_whole_lineage(na_service, revoke):
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    new = _reissued(na_service, old)
    db.reissue_membership_attestation(old.attestation_id, new)
    target = old if revoke == "old" else new

    assert db.revoke_membership_attestation_lineage(target.attestation_id, "offboarded") == [
        old.attestation_id, new.attestation_id]
    for att in (old, new):
        row = db.get_membership_attestation(att.attestation_id)
        assert row["status"] == "revoked" and row["revocation_reason"] == "offboarded"
    assert db.revoke_membership_attestation_lineage("no-such-id", "x") == []
    assert db.revoke_membership_attestation("no-such-id") is False


def test_saving_an_attestation_again_keeps_its_lineage(na_service):
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    new = _reissued(na_service, old)
    db.reissue_membership_attestation(old.attestation_id, new)
    db.save_membership_attestation(new)
    row = db.get_membership_attestation(new.attestation_id)
    assert row["lineage_id"] == old.attestation_id and row["reissued_from"] == old.attestation_id


def test_treaties_have_the_same_lineage(na_service):
    db = na_service.db
    old = _treaty(na_service)
    db.save_recognition_treaty(old)
    new = _treaty(na_service, issued_at=datetime.now(timezone.utc))
    assert db.reissue_recognition_treaty(old.treaty_id, new) is True
    assert db.reissue_recognition_treaty(old.treaty_id, _treaty(na_service)) is False

    assert db.get_recognition_treaty(old.treaty_id)["superseded_by"] == new.treaty_id
    assert db.get_recognition_treaty(new.treaty_id)["reissued_from"] == old.treaty_id
    assert [r["treaty"].treaty_id for r in db.list_recognition_treaties()] == [new.treaty_id]
    assert {r["treaty"].treaty_id for r in db.list_recognition_treaties(include_superseded=True)} == {
        old.treaty_id, new.treaty_id}
    assert db.recognition_treaty_lineage(new.treaty_id) == [old.treaty_id, new.treaty_id]

    assert db.revoke_recognition_treaty_lineage(new.treaty_id, "ended") == [old.treaty_id, new.treaty_id]
    assert {db.get_recognition_treaty(t)["status"] for t in (old.treaty_id, new.treaty_id)} == {"revoked"}


# ---------------------------------------------------------------------------
# Revocation racing a re-issue (SQLite and PostgreSQL)
# ---------------------------------------------------------------------------


def test_a_revocation_waiting_on_a_reissue_also_revokes_the_new_copy(na_service):
    """The re-issue commits first: the revocation, blocked until then, still reaches the new copy.

    On PostgreSQL the revocation runs on its own connection; its first UPDATE
    waits on the re-issue's row lock and its snapshot does not include the new
    copy, which the following pass revokes.
    """
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    new = _reissued(na_service, old)
    inserted = threading.Event()
    revoked: list[str] = []

    def insert_then_wait(lineage_id: str) -> None:
        db._insert_membership_attestation(
            new, "active", lineage_id=lineage_id, reissued_from=old.attestation_id, upsert=False)
        inserted.set()
        time.sleep(0.5)  # the revocation starts while this transaction is open

    def revoke() -> None:
        inserted.wait(5)
        revoked.extend(db.revoke_membership_attestation_lineage(old.attestation_id, "offboarded"))

    revoker = threading.Thread(target=revoke)
    revoker.start()
    assert db._reissue("membership_attestations", "attestation_id", old.attestation_id,
                       new.attestation_id, insert_then_wait) is True
    revoker.join(10)
    assert not revoker.is_alive()
    assert revoked == [old.attestation_id, new.attestation_id]
    for att in (old, new):
        assert db.get_membership_attestation(att.attestation_id)["status"] == "revoked"


def test_a_reissue_after_a_revocation_brings_nothing_back(na_service):
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    done = threading.Event()

    def revoke() -> None:
        db.revoke_membership_attestation_lineage(old.attestation_id, "offboarded")
        done.set()

    threading.Thread(target=revoke).start()
    assert done.wait(5)
    new = _reissued(na_service, old)
    assert db.reissue_membership_attestation(old.attestation_id, new) is False
    assert db.get_membership_attestation(new.attestation_id) is None
    assert _listed_ids(db, status="active", include_superseded=True) == set()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_routes_show_the_lineage_and_revoke_all_of_it(client, na_service):
    db = na_service.db
    old = _attestation(na_service)
    db.save_membership_attestation(old)
    new = _reissued(na_service, old)
    db.reissue_membership_attestation(old.attestation_id, new)

    # A decision binds the ID it was given: the old ID still reads as itself.
    body = client.get(f"/attestations/{old.attestation_id}").get_json()
    assert body["attestation"]["attestation_id"] == old.attestation_id
    assert body["status"] == "active" and body["superseded_by"] == new.attestation_id
    assert client.get(f"/attestations/{new.attestation_id}").get_json()["reissued_from"] == old.attestation_id
    assert client.get("/attestations").get_json() == {"count": 1}

    resp = _post(client, f"/admin/attestations/{new.attestation_id}/revoke", {"reason": "offboarded"})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["lineage_ids"] == [old.attestation_id, new.attestation_id]

    # The feed lists every copy, since a holder may still present either ID.
    feed = SovereignRevocationFeed.model_validate(client.get("/sovereign-revocation-feed").get_json())
    assert {old.attestation_id, new.attestation_id} <= set(feed.revoked_attestation_ids)
    events = [e for e in db.list_audit_events() if e["event_type"] == "membership_attestation_revoked"]
    assert events[-1]["details"]["lineage_ids"] == [old.attestation_id, new.attestation_id]


def test_the_treaty_routes_show_the_lineage_and_revoke_all_of_it(client, na_service):
    db = na_service.db
    old = _treaty(na_service)
    db.save_recognition_treaty(old)
    new = _treaty(na_service, issued_at=datetime.now(timezone.utc))
    db.reissue_recognition_treaty(old.treaty_id, new)

    assert client.get(f"/recognition-treaties/{old.treaty_id}").get_json()["superseded_by"] == new.treaty_id
    listed = client.get("/recognition-treaties").get_json()
    assert [row["treaty"]["treaty_id"] for row in listed["recognition_treaties"]] == [new.treaty_id]

    resp = _post(client, f"/admin/recognition-treaties/{old.treaty_id}/revoke", {"reason": "ended"})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["lineage_ids"] == [old.treaty_id, new.treaty_id]
    assert client.get(f"/recognition-treaties/{new.treaty_id}").get_json()["status"] == "revoked"
    assert _post(client, "/admin/recognition-treaties/no-such-treaty/revoke", {}).status_code == 404


# ---------------------------------------------------------------------------
# Migration 020
# ---------------------------------------------------------------------------


@pytest.mark.sqlite_only
def test_migration_020_starts_a_lineage_for_every_stored_record(tmp_path, monkeypatch, na_service):
    path = str(tmp_path / "na.db")
    real = db_module.migration_files
    att = _attestation(na_service)
    treaty = _treaty(na_service)
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "migration_files", lambda backend: [m for m in real(backend) if m[0] <= 19])
        old = NADatabase(path)
        old.migrate()
        assert old.schema_version() == 19
        # Rows as 1.7 stored them, without the lineage columns.
        with old.conn:
            old.conn.execute(
                "INSERT INTO membership_attestations (attestation_id, issuer_sovereign_id, subject_id, "
                "roles_json, status, attestation_json, issued_at, valid_from, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (att.attestation_id, att.issuer_sovereign_id, att.subject_id, '["role:client"]', "active",
                 att.model_dump_json(), att.issued_at.isoformat(), att.valid_from.isoformat(),
                 att.expires_at.isoformat()))
            old.conn.execute(
                "INSERT INTO recognition_treaties (treaty_id, issuer_sovereign_id, subject_sovereign_id, status, "
                "treaty_json, issued_at, valid_from, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (treaty.treaty_id, treaty.issuer_sovereign_id, treaty.subject_sovereign_id, "active",
                 treaty.model_dump_json(), treaty.issued_at.isoformat(), treaty.valid_from.isoformat(),
                 treaty.expires_at.isoformat()))
        old.close()

    upgraded = NADatabase(path)
    upgraded.migrate()
    assert upgraded.schema_version() == db_module.expected_schema_version() >= 20
    row = upgraded.get_membership_attestation(att.attestation_id)
    assert row["lineage_id"] == att.attestation_id and row["superseded_by"] is None
    assert upgraded.get_recognition_treaty(treaty.treaty_id)["lineage_id"] == treaty.treaty_id
    assert _listed_ids(upgraded) == {att.attestation_id}
    with sqlite3.connect(path) as raw:
        indexes = {r[1] for r in raw.execute("SELECT type, name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_membership_attestations_lineage", "idx_recognition_treaties_lineage"} <= indexes
    upgraded.close()
