"""The NA signs only over a store it can vouch for (v1.3.1).

A database writer without the NA key can delete or rewrite entries. The NA
must not then extend its signed history over the result: neither a
retention checkpoint (which would sign the deletion as retention) nor an
anchor (which would tie the cut store to the anchor chain). Also: the
retention floor, unjudged records with the records off, an anchor dated
ahead of an instance's clock, and the anchor files the CLI writes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from genesis_mesh.cli import evidence_store_ops
from genesis_mesh.cli.evidence_store_ops import evidence as evidence_cli
from genesis_mesh.models.evidence_store import RetentionCheckpoint

from .test_evidence_anchors import (  # noqa: F401 -- fixtures
    ANCHORS,
    _activity,
    _held,
    _tamper,
    cli,
    client,
    na_service,
)
from .test_evidence_store import Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _get, _make_service, _post
from .test_out_of_band import Observer, _observe, clock  # noqa: F401 -- fixture

RETENTION = "/admin/evidence/retention/apply"


class _Later(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz) + timedelta(days=400)


def _retention(client, monkeypatch, days: int = 30):
    import genesis_mesh.na_service.services.evidence_store as svc

    monkeypatch.setattr(svc, "datetime", _Later)
    try:
        return _post(client, RETENTION, {"older_than_days": days})
    finally:
        monkeypatch.setattr(svc, "datetime", datetime)


def _resource_history(client) -> tuple[int, int]:
    """Two records of one resource; returns their store sequences."""
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    _decide(client)  # later activity on no resource
    db = client.application.extensions["genesis_mesh_na"].db
    rows = db.conn.execute(
        "SELECT store_sequence FROM evidence_entries WHERE entry_kind = 'execution' ORDER BY store_sequence"
    ).fetchall()
    return int(rows[0]["store_sequence"]), int(rows[1]["store_sequence"])


def _delete(db, *sequences: int) -> None:
    marks = ", ".join("?" for _ in sequences)
    _tamper(db, "evidence_entries_retention_only_delete", "evidence_entries",
            f"DELETE FROM evidence_entries WHERE store_sequence IN ({marks})", tuple(sequences))


def _rewrite_payload(db, sequence: int) -> None:
    row = db.conn.execute("SELECT payload_json FROM evidence_entries WHERE store_sequence = ?",
                          (sequence,)).fetchone()
    payload = json.loads(row["payload_json"])
    payload["tampered"] = True
    _tamper(db, "evidence_entries_no_update", "evidence_entries",
            "UPDATE evidence_entries SET payload_json = ? WHERE store_sequence = ?", (json.dumps(payload), sequence))


# --- retention never signs over deleted entries ---------------------------------


def test_retention_refuses_to_sign_over_entries_deleted_outside_it(client, na_service, monkeypatch):
    """Deleting a resource's latest record and another entry, then a routine retention, launders nothing."""
    first, second = _resource_history(client)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    db = na_service.db
    _delete(db, first, second)
    head_before = db.store_head()
    refused = _retention(client, monkeypatch)
    assert refused.status_code == 409 and _code(refused) == "evidence_retention_refused"
    assert "missing" in refused.get_json()["error"]["message"]
    assert db.latest_retention_checkpoint() is None
    assert db.store_head() == head_before, "a refused retention leaves the store unchanged"
    assert "evidence_retention_refused" in [e["event_type"] for e in db.list_audit_events()]
    assert _get(client, "/admin/evidence/verify").get_json()["verified"] is False


def test_retention_refuses_a_store_rewritten_after_the_latest_anchor(client, na_service, monkeypatch):
    _resource_history(client)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    _decide(client)
    db = na_service.db
    head, _ = db.store_head()
    _rewrite_payload(db, head)
    refused = _retention(client, monkeypatch)
    assert refused.status_code == 409 and _code(refused) == "evidence_retention_refused"
    assert db.latest_retention_checkpoint() is None


def test_retention_still_removes_an_intact_prefix(client, na_service, monkeypatch):
    _resource_history(client)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    applied = _retention(client, monkeypatch)
    assert applied.status_code == 200, applied.get_json()
    checkpoint = applied.get_json()["checkpoint"]
    assert checkpoint["removed_count"] == checkpoint["removed_through_sequence"]
    assert _get(client, "/admin/evidence/verify").get_json()["verified"] is True


def test_a_checkpoint_that_does_not_count_every_removed_entry_is_refused(client, na_service):
    _resource_history(client)
    db = na_service.db
    store = na_service.evidence_store_service
    rows = [r for r in db.retention_candidates() if int(r["store_sequence"]) <= 3]
    checkpoint = RetentionCheckpoint(
        cutoff=datetime.now().astimezone(), removed_through_sequence=3,
        last_removed_entry_digest=rows[-1]["entry_digest"], removed_count=2, issued_by="test-key",
    )
    assert "not all stored" in (store._retention_problem(checkpoint, None, rows) or "")
    whole = checkpoint.model_copy(update={"removed_count": 3})
    assert store._retention_problem(whole, None, rows) is None


# --- the NA's own verification and anchoring start at entry 1 ---------------------


def test_deleting_the_start_through_an_anchored_entry_fails_verification_and_anchoring(client, na_service):
    """Anchors at A1 and A2, entries 1..A1 deleted: the rest continues from A1, but the store starts late."""
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    _activity(client, 2)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    _activity(client, 2)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    first_anchored = _held(client)[0].store_sequence
    db = na_service.db
    _delete(db, *range(1, first_anchored + 1))
    result = _get(client, "/admin/evidence/verify").get_json()
    assert result["verified"] is False
    assert "store_sequence_gap" in {f["reason"] for f in result["failures"]}
    _decide(client)
    refused = _post(client, ANCHORS, {}, standard=True)
    assert refused.status_code == 409 and _code(refused) == "evidence_anchor_refused"
    assert "starts at entry" in refused.get_json()["error"]["message"]


def test_anchoring_refuses_a_store_missing_an_entry_below_the_latest_anchor(client, na_service):
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    _activity(client, 2)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    _delete(na_service.db, 2)
    _decide(client)
    refused = _post(client, ANCHORS, {}, standard=True)
    assert refused.status_code == 409 and _code(refused) == "evidence_anchor_refused"


@pytest.mark.parametrize("column", ["payload_json", "entry_json"])
def test_anchoring_refuses_a_rewritten_head_that_is_the_latest_anchored_entry(client, na_service, column):
    """The head is unchanged in sequence and digest column, but its stored JSON was rewritten."""
    _activity(client, 1)
    assert _post(client, ANCHORS, {}, standard=True).status_code in (200, 201)
    db = na_service.db
    head, _ = db.store_head()
    assert db.latest_store_anchor().store_sequence == head
    row = db.conn.execute(f"SELECT {column} FROM evidence_entries WHERE store_sequence = ?", (head,)).fetchone()
    value = json.loads(row[column])
    value["outcome"] = "failure"
    _tamper(db, "evidence_entries_no_update", "evidence_entries",
            f"UPDATE evidence_entries SET {column} = ? WHERE store_sequence = ?", (json.dumps(value), head))
    refused = _post(client, ANCHORS, {}, standard=True)
    assert refused.status_code == 409 and _code(refused) == "evidence_anchor_refused"


# --- retention floor ------------------------------------------------------------------


def test_the_retention_floor_is_the_backlog_plus_twice_the_skew(clock):
    """With 13 hours of skew a change may be dated 26 hours after it was recorded: 8 days is too short."""
    service = _make_service(evidence_store="on", evidence_out_of_band="on",
                            observation_clock_skew_seconds=13 * 3600)
    client = _client(service)
    refused = _post(client, RETENTION, {"older_than_days": 8})
    assert refused.status_code == 400 and _code(refused) == "invalid_retention"
    assert "at least 9" in refused.get_json()["error"]["message"]
    assert _post(client, RETENTION, {"older_than_days": 9}).status_code == 200


def test_the_retention_floor_holds_with_the_records_off_while_the_store_keeps_them(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    client = _client(service)
    assert _observe(client, Observer(client).observe(clock)).status_code == 201
    service.evidence_out_of_band = "off"
    refused = _post(client, RETENTION, {"older_than_days": 7})
    assert refused.status_code == 400 and _code(refused) == "invalid_retention"


def test_a_store_without_out_of_band_records_keeps_short_retention():
    client = _client(_make_service(evidence_store="on"))
    _decide(client)
    assert _post(client, RETENTION, {"older_than_days": 1}).status_code == 200


# --- unjudged records with the records off ---------------------------------------------


def test_unjudged_records_are_reported_and_explain_retention_with_the_records_off(clock, monkeypatch):
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    observation = Observer(client).observe(clock)
    assert _observe(client, observation).status_code == 201
    assert _submit(client, Controller(client).record(_decide(client))).status_code == 201
    service.evidence_out_of_band = "off"
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 1
    result = _retention(client, monkeypatch)
    assert result.status_code == 200
    held = result.get_json()["held_back"]
    assert held["reason"] == "unjudged_records" and held["record_id"] == observation.observation_id
    assert "EVIDENCE_OUT_OF_BAND is off" in held["message"]
    kinds = {e["entry"]["entry_kind"] for e in _get(client, "/admin/evidence?limit=1000").get_json()["entries"]}
    assert "observation" in kinds, "an unjudged record is kept, never removed unjudged"


def test_status_reports_no_unjudged_records_for_a_store_without_them():
    client = _client(_make_service(evidence_store="on"))
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 0


# --- an anchor dated ahead of this instance's clock -------------------------------------


def test_an_anchor_signed_by_an_instance_whose_clock_runs_ahead_is_reported(client, cli, monkeypatch):
    import genesis_mesh.na_service.services.evidence_store as svc

    class Ahead(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=6)

    run, base, tmp = cli
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    _decide(client)
    monkeypatch.setattr(svc, "datetime", Ahead)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    monkeypatch.setattr(svc, "datetime", datetime)
    _decide(client)
    status = _get(client, "/admin/evidence/status").get_json()
    assert "ahead of this instance's clock" in status["anchoring_blocked"]
    out = tmp / "held"
    result = CliRunner().invoke(evidence_cli, ["anchors", "fetch", *base, "--out", str(out), "--anchor-now"])
    assert result.exit_code != 0
    assert "refused to anchor" in result.output and "ahead of this instance's clock" in result.output
    assert len(list(out.glob("anchor-*.json"))) == 1, "the anchors the NA serves are still copied"


# --- anchor files ------------------------------------------------------------------------


def test_an_anchor_file_is_never_left_truncated_without_hard_links(tmp_path, client, monkeypatch):
    _decide(client)
    anchor = _held(client)[0]
    real_open = open

    class _DiskFull:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, data):
            self.f.write(data[: len(data) // 2])
            self.f.flush()
            raise OSError("no space left on device")

    def failing_open(path, mode="r", *args, **kwargs):
        f = real_open(path, mode, *args, **kwargs)
        return _DiskFull(f) if "w" in mode or "x" in mode else f

    def no_links(src, dst):
        raise OSError("hard links are not supported")

    monkeypatch.setattr(evidence_store_ops.os, "link", no_links)
    monkeypatch.setattr(evidence_store_ops, "open", failing_open, raising=False)
    with pytest.raises(OSError):
        evidence_store_ops._write_anchor(tmp_path, anchor)
    path = evidence_store_ops._anchor_path(tmp_path, anchor)
    assert not path.exists() or path.stat().st_size == 0, "no truncated anchor at its final name"
    monkeypatch.setattr(evidence_store_ops, "open", real_open, raising=False)
    evidence_store_ops._write_anchor(tmp_path, anchor)
    evidence_store_ops._write_anchor(tmp_path, anchor)
    assert evidence_store_ops.load_anchors(str(tmp_path)) == [anchor]
    with pytest.raises(Exception, match="different anchor"):
        evidence_store_ops._write_anchor(tmp_path, anchor.model_copy(update={"entry_digest": "e" * 64}))
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="the name is claimed first only where a rename may replace")
def test_an_empty_anchor_file_left_by_an_interrupted_write_is_taken_over(tmp_path, client, monkeypatch):
    _decide(client)
    anchor = _held(client)[0]
    monkeypatch.setattr(evidence_store_ops.os, "link", lambda src, dst: (_ for _ in ()).throw(OSError("no links")))
    evidence_store_ops._anchor_path(tmp_path, anchor).write_text("", encoding="utf-8")
    assert evidence_store_ops.load_anchors(str(tmp_path)) == []
    evidence_store_ops._write_anchor(tmp_path, anchor)
    assert evidence_store_ops.load_anchors(str(tmp_path)) == [anchor]


# --- JSON Lines split on LF only ------------------------------------------------------------


def test_a_lone_cr_is_not_a_line_break_in_an_export_or_anchor_file(client, cli, tmp_path):
    run, base, tmp = cli
    _activity(client, 1)
    _post(client, ANCHORS, {}, standard=True)
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).strip("\n").split("\n")
    assert len(lines) >= 2
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(_get(client, "/admin/evidence/executor-keys").get_json()), encoding="utf-8")
    export = tmp_path / "export.jsonl"
    # Two records separated by a lone CR are one line, which is not one JSON value.
    export.write_bytes(("\r".join(lines[:2]) + "\n" + "\n".join(lines[2:]) + "\n").encode("utf-8"))
    joined = CliRunner().invoke(evidence_cli, ["verify-export", "--file", str(export), "--na-public-key",
                                               str(tmp / "na.pub"), "--executor-keys", str(keys)])
    assert joined.exit_code != 0 and "malformed" in joined.output
    # A CR inside a line, between JSON tokens, is whitespace: the record still reads.
    spaced = [lines[0].replace('{"entry":', '{\r"entry":', 1), *lines[1:]]
    export.write_bytes(("\r\n".join(spaced) + "\r\n").encode("utf-8"))
    ok = CliRunner().invoke(evidence_cli, ["verify-export", "--file", str(export), "--na-public-key",
                                           str(tmp / "na.pub"), "--executor-keys", str(keys)])
    assert ok.exit_code == 0, ok.output
    anchors = [json.dumps(a.to_wire()) for a in _held(client)]
    held = tmp_path / "anchors.jsonl"
    held.write_bytes(("\r".join(anchors * 2) + "\n").encode("utf-8"))
    with pytest.raises(Exception, match="Cannot read anchors"):
        evidence_store_ops.load_anchors(str(held))
