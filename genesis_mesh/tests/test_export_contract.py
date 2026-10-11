"""The export verifier's contract with the SDKs (v1.3.1).

Every implementation that verifies an evidence export reads it as received
and names the same reason for the same input. The cases the SDKs share are
the conformance suites ``canonical`` and ``out_of_band``; these tests run the
reference against a Network Authority's own exports: a record checked as
received even when it carries a field outside its signature, an envelope
hashed as received, exports that start mid-store, an export since a held
anchor, retention over a store with entries deleted, replayed records and
judgement links.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
from click.testing import CliRunner

from genesis_mesh import strict_json
from genesis_mesh.models.canonical_registry import decision_refusal, intent_refusal_detail
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.evidence_store import EvidenceEvent, RetentionCheckpoint, canonical_json, payload_digest
from genesis_mesh.models.out_of_band import JudgementRecord
from genesis_mesh.trust.evidence_store import (
    EvidenceVerification,
    export_checkpoint,
    parse_export_lines,
    sign_retention_checkpoint,
    verify_evidence_events,
)
from genesis_mesh.trust.context.decisions import verify_boundary_decision
from genesis_mesh.trust.out_of_band import sign_na_record

from .test_evidence_anchors import (  # noqa: F401 -- fixtures
    ANCHORS,
    _activity,
    _held,
    _tamper,
    _verify,
    cli,
    client,
    na_service,
)
from .test_evidence_anchors import evidence_cli
from .test_evidence_store import Controller, _client, _decide, _submit
from .test_na_boundary_policy import _get, _make_service, _post
from .test_out_of_band import Observer, _observe, clock  # noqa: F401 -- fixture

SUITES = Path(__file__).resolve().parents[2] / "conformance" / "vectors"


def _lines(client, since: int = 0) -> list[str]:
    query = f"?since_sequence={since}" if since else ""
    return _get(client, f"/admin/evidence/export{query}").get_data(as_text=True).splitlines()


def _check(service, events: list[EvidenceEvent], **kw: Any) -> EvidenceVerification:
    return verify_evidence_events(events, na_public_keys=[service.signer.public_key_b64],
                                  executor_keys=service.evidence_store_service.executor_keys(), **kw)


def _reasons(result: EvidenceVerification) -> set[tuple[int | None, str]]:
    return {(f["store_sequence"], f["reason"]) for f in result.failures}


def _relinked(events: list[EvidenceEvent], change: Callable[[dict[str, Any]], None]) -> list[EvidenceEvent]:
    """What a database writer can do: change stored lines as JSON, then recompute every digest and link."""
    out: list[EvidenceEvent] = []
    prev: str | None = None
    for event in events:
        data = json.loads(event.to_json_line())
        change(data)
        data["entry"]["payload_digest"] = payload_digest(data["payload"])
        if out:
            data["entry"]["prev_entry_digest"] = prev
        data["entry_digest"] = hashlib.sha256(canonical_json(data["entry"]).encode()).hexdigest()
        out.append(EvidenceEvent.received(data))
        prev = data["entry_digest"]
    return out


# ---------------------------------------------------------------------------
# Strict input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, reason", [
    ("[-0.]", "invalid_json"),
    ("[-0e]", "invalid_json"),
    ("[-0.e1]", "invalid_json"),
    ("[100000000000000000000.]", "invalid_json"),
    ("[1E+]", "invalid_json"),
    ("[-01]", "negative_zero"),
    ("[1e400.]", "non_finite_number"),
])
def test_a_number_is_read_by_the_grammar_before_its_value_is_checked(text, reason):
    with pytest.raises(strict_json.StrictJSONError) as caught:
        strict_json.loads(text)
    assert caught.value.reason == reason


def test_a_license_policy_is_checked_whole_not_only_its_timestamps():
    interop = json.loads((SUITES / "interop.json").read_text(encoding="utf-8"))
    case = next(v["input"] for v in interop["vectors"] if v["id"] == "int-001")
    assert intent_refusal_detail(case["intent"], case["policy"], case["agent_public_keys"]) is None
    policy = copy.deepcopy(case["policy"])
    del policy["max_volume_bytes_per_session"]  # a field the reference always writes
    assert intent_refusal_detail(case["intent"], policy, case["agent_public_keys"]) == "Not in canonical form: policy"


def test_a_decision_valid_until_without_an_offset_is_read_as_utc_not_raised_on():
    """1.3.0 raised TypeError comparing it with an aware clock; every SDK reads it as UTC."""
    canonical = json.loads((SUITES / "canonical.json").read_text(encoding="utf-8"))
    case = next(v["input"] for v in canonical["vectors"] if v["id"] == "verify-decision-naive-valid-until")
    decision = BoundaryDecision.model_validate(case["decision"])
    assert decision.decision_valid_until.tzinfo is None
    keys = case["operator_public_keys"]
    at = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    assert verify_boundary_decision(decision, keys, now=at).reason == "authorized"
    assert verify_boundary_decision(decision, keys, now=at + timedelta(hours=1)).reason == "decision_expired"
    assert verify_boundary_decision(decision, keys, now=at.replace(tzinfo=None)).reason == "authorized"
    assert decision_refusal(case["decision"], keys, at + timedelta(hours=1)) == "decision_expired"


# ---------------------------------------------------------------------------
# Records and envelopes as received
# ---------------------------------------------------------------------------


def test_a_record_with_a_field_outside_its_signature_is_still_checked_as_received(client, na_service):
    _activity(client, 1)
    events = parse_export_lines(_lines(client))

    def respell(data: dict[str, Any], note: bool) -> None:
        if data["entry"]["entry_kind"] == "decision":
            decision = data["payload"]["decision"]
            decision["decision_made_at"] = decision["decision_made_at"].replace("Z", "+00:00")
            if note:
                data["payload"]["note"] = "added after signing"

    plain = _check(na_service, _relinked(events, lambda d: respell(d, False)))
    noted = _check(na_service, _relinked(events, lambda d: respell(d, True)))
    assert (1, "invalid_signature") in _reasons(plain)
    # 1.3.0 skipped the check for a record carrying a field outside its signature.
    assert (1, "invalid_signature") in _reasons(noted)
    assert [w["reason"] for w in noted.warnings] == ["unsigned_field"]


def test_an_envelope_is_hashed_as_received(client, na_service):
    _activity(client, 2)
    lines = _lines(client)
    assert _check(na_service, parse_export_lines(lines)).verified

    def edit(index: int, change: Callable[[dict[str, Any]], None]) -> list[str]:
        data = json.loads(lines[index])
        change(data["entry"])
        return [*lines[:index], json.dumps(data, separators=(",", ":")), *lines[index + 1:]]

    respelled = edit(1, lambda e: e.update(recorded_at=e["recorded_at"].replace("Z", "+00:00")))
    assert respelled != lines
    result = _check(na_service, parse_export_lines(respelled))
    assert _reasons(result) == {(2, "entry_digest_mismatch"), (3, "store_chain_break")}
    # The envelope fields added in 1.3.0 read the same absent or null.
    assert _check(na_service, parse_export_lines(edit(1, lambda e: e.update(record_id=None)))).verified
    # An envelope every SDK refuses to read is refused as it is read.
    for change in (lambda e: e.update(store_sequence="2"), lambda e: e.pop("decision_id"),
                   lambda e: e.update(recorded_at=e["recorded_at"].replace("T", " ")),
                   lambda e: e.update(exec_sequence_no=True)):
        with pytest.raises(ValueError, match="invalid evidence event envelope"):
            parse_export_lines(edit(1, change))


def test_an_execution_time_without_an_offset_is_checked_not_raised_on(client, na_service):
    _activity(client, 1)
    events = parse_export_lines(_lines(client))

    def naive(data: dict[str, Any]) -> None:
        if data["entry"]["entry_kind"] == "execution":
            data["payload"]["executed_at"] = data["payload"]["executed_at"].removesuffix("Z")

    forged = _relinked(events, naive)
    at = next(e.entry.store_sequence for e in forged if e.entry.entry_kind == "execution")
    assert _reasons(_check(na_service, forged)) == {(at, "invalid_signature")}  # 1.3.0: TypeError


def test_a_respelled_envelope_no_longer_matches_its_anchor(client, na_service):
    _activity(client, 1)
    assert _post(client, ANCHORS, {}, standard=True).status_code in (200, 201)
    held = _held(client)
    lines = _lines(client)
    anchored = held[-1].store_sequence
    data = json.loads(lines[anchored - 1])
    data["entry"]["recorded_at"] = data["entry"]["recorded_at"].replace("Z", "+00:00")
    lines[anchored - 1] = json.dumps(data)  # its entry_digest still the anchored one
    result = _verify(parse_export_lines(lines), held)
    assert (anchored, "anchor_mismatch") in _reasons(result)  # 1.3.0: the parsed envelope matched


# ---------------------------------------------------------------------------
# Where an export starts
# ---------------------------------------------------------------------------


def test_an_export_since_a_position_verifies_a_chain_that_spans_its_start(client, na_service):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    since = na_service.db.store_head()[0]
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    later = parse_export_lines(_lines(client, since))
    assert later[0].entry.store_sequence == since + 1
    result = _check(na_service, later)
    assert result.verified, result.failures  # 1.2 and 1.3.0: resource_chain_break
    # From entry 1 the chain is still held from its start.
    without_first = [e for e in parse_export_lines(_lines(client)) if e.entry.evidence_id != first.evidence_id]
    assert "resource_chain_break" in {r for _, r in _reasons(_check(na_service, without_first, contiguous=False))}


def test_verify_export_ties_an_export_since_a_held_anchor_only_with_from_anchor(client, cli, tmp_path):
    run, base, tmp = cli
    _activity(client, 1)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    since = _held(client)[-1].store_sequence
    _activity(client, 1)
    out = tmp / "held"
    assert run("anchors", "fetch", *base, "--out", str(out), "--anchor-now").exit_code == 0
    export = tmp_path / "since.jsonl"
    export.write_text("\n".join(_lines(client, since)) + "\n", encoding="utf-8")
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(_get(client, "/admin/evidence/executor-keys").get_json()), encoding="utf-8")
    args = ["verify-export", "--file", str(export), "--na-public-key", str(tmp / "na.pub"),
            "--executor-keys", str(keys), "--known-anchors", str(out), "--format", "json"]
    refused = CliRunner().invoke(evidence_cli, args)
    assert refused.exit_code == 1
    assert [f["reason"] for f in json.loads(refused.output)["failures"]] == ["export_not_linked_to_anchors"]
    accepted = CliRunner().invoke(evidence_cli, [*args, "--from-anchor"])
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["anchors"]["linked_start"] is True


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _retain(client, monkeypatch) -> dict:
    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.now(tz) + timedelta(days=400)

    monkeypatch.setattr(svc, "datetime", Later)
    applied = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    monkeypatch.undo()
    return applied


def _resource_history(client) -> None:
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    _decide(client)  # later activity, so retention has entries to keep


def test_an_export_after_retention_verifies_from_its_checkpoint(client, na_service, monkeypatch):
    _resource_history(client)
    applied = _retain(client, monkeypatch)
    assert applied["removed_count"] > 0
    events = parse_export_lines(_lines(client))
    result = _check(na_service, events, checkpoint=export_checkpoint(events))
    assert result.verified, result.failures
    # Without the checkpoint's entry, the export says nothing of what was removed before it.
    held = _held(client)
    without = [e for e in events if e.entry.entry_kind != "retention_checkpoint"]
    [failure] = [f for f in _verify(without, held).failures if f["reason"] == "export_not_linked_to_anchors"]
    assert "include that checkpoint's entry" in failure["detail"]


def test_a_checkpoint_signed_over_a_store_with_deleted_entries_fails_offline(client, na_service, monkeypatch):
    """A checkpoint the NA key signed while entries it says it removed were already gone (1.2 and 1.3.0 passed)."""
    _resource_history(client)
    _retain(client, monkeypatch)
    events = parse_export_lines(_lines(client))
    honest = export_checkpoint(events)
    assert honest is not None and honest.previous_checkpoint_id is None
    at = next(e.entry.store_sequence for e in events if e.entry.entry_kind == "retention_checkpoint")

    def launder(data: dict[str, Any]) -> None:
        if data["entry"]["store_sequence"] == at:
            fewer = honest.model_copy(update={"removed_count": honest.removed_count - 1, "signature": None})
            signed = sign_retention_checkpoint(fewer, na_service.signer, na_service.key_id)
            data["payload"] = json.loads(signed.model_dump_json())

    laundered = _relinked(events, launder)
    signed = export_checkpoint(laundered)
    assert isinstance(signed, RetentionCheckpoint) and signed.removed_count == honest.removed_count - 1
    result = _check(na_service, laundered, checkpoint=signed)
    assert _reasons(result) == {(at, "retention_count_mismatch")}


def test_a_checkpoint_passed_in_must_carry_the_na_signature(client, na_service, monkeypatch):
    _resource_history(client)
    _retain(client, monkeypatch)
    events = parse_export_lines(_lines(client))
    checkpoint = export_checkpoint(events)
    assert checkpoint is not None
    forged = checkpoint.model_copy(update={"removed_count": checkpoint.removed_count + 1})
    result = _check(na_service, events, checkpoint=forged)
    assert result.failures == [{"store_sequence": None, "reason": "invalid_signature",
                                "detail": "retention_checkpoint"}]


# ---------------------------------------------------------------------------
# Replays and judgement links
# ---------------------------------------------------------------------------


def test_the_envelope_fields_checked_are_those_the_na_writes():
    from genesis_mesh.models import out_of_band as oob_models
    from genesis_mesh.trust.evidence_store import _ENVELOPE_FIELDS
    from genesis_mesh.trust.out_of_band import entry_index

    suite = json.loads((SUITES / "out_of_band.json").read_text(encoding="utf-8"))
    kinds = {"ObservationRecord": "observation", "BreakGlassRecord": "break_glass", "JudgementRecord": "judgement",
             "QuarantineRecord": "quarantine", "RegistryRecord": "registry"}
    seen = set()
    for vector in suite["vectors"]:
        if vector["kind"] != "canonical_form":
            continue
        record = getattr(oob_models, vector["model"]).model_validate(vector["record"])
        kind = kinds[vector["model"]]
        seen.add(kind)
        expected = {f: getattr(record, source) for f, source in _ENVELOPE_FIELDS[kind].items()}
        assert entry_index(kind, record) == expected, kind
    assert seen == set(_ENVELOPE_FIELDS)


@pytest.fixture
def oob(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    return service, _client(service)


def test_a_replayed_record_is_refused(oob, clock):
    service, client = oob
    observer = Observer(client)
    assert _observe(client, observer.observe(clock)).status_code == 201
    events = parse_export_lines(_lines(client))
    assert _check(service, events).verified
    last = events[-1].entry.store_sequence
    for kind in ("registry", "observation", "judgement"):
        copied = next(e for e in events if e.entry.entry_kind == kind)
        replayed = [*events, copied.model_copy(update={"entry": copied.entry.model_copy(
            update={"store_sequence": last + 1})})]
        result = _check(service, _relinked(replayed, lambda data: None))
        assert (last + 1, "duplicate_record") in _reasons(result), kind


def test_a_judgements_envelope_and_matched_record_are_checked(oob, clock):
    service, client = oob
    controller = Controller(client)
    evidence = controller.record(_decide(client), params={"version_id": "v7"})
    assert _submit(client, evidence).status_code == 201
    clock.at = evidence.executed_at + timedelta(minutes=1)  # the observer reports the change made then
    observer = Observer(client)
    judged = _observe(client, observer.observe(clock, action="create", version_id="v7")).get_json()
    assert judged["judgement"]["payload"]["matched_evidence_id"] == evidence.evidence_id
    events = parse_export_lines(_lines(client))
    assert _check(service, events).verified
    at = next(e.entry.store_sequence for e in events if e.entry.entry_kind == "judgement")

    def envelope(data: dict[str, Any]) -> None:
        if data["entry"]["store_sequence"] == at:
            data["entry"]["matched_evidence_id"] = "another-record"

    assert _reasons(_check(service, _relinked(events, envelope))) == {(at, "envelope_mismatch")}

    def phantom(data: dict[str, Any]) -> None:
        if data["entry"]["store_sequence"] == at:
            record = JudgementRecord.model_validate({**data["payload"], "matched_evidence_id": "no-such-record"})
            resigned = sign_na_record(record.model_copy(update={"signature": None}), service.signer, service.key_id)
            data["payload"] = resigned.to_wire()
            data["entry"]["matched_evidence_id"] = "no-such-record"

    forged = _relinked(events, phantom)
    assert _reasons(_check(service, forged)) == {(at, "judgement_match_missing")}
    # An export that starts after entry 1 need not hold the matched record.
    assert _check(service, forged[1:]).verified
