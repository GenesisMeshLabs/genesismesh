"""The ``audit`` conformance suite (v1.5.0): key history, key windows, exports across a succession,
packs and the completeness check.

``audit_vectors()`` builds every vector from the deterministic world
(``audit_world``) and fills ``expected`` with ``evaluate``, the Python
reference's verdict; the runner calls ``evaluate`` again on each vector's
input and compares. Reason codes are the contract: every verifier must name
the same ones for the same input.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from audit_world import (
    KEYS,
    RESOURCE,
    SOVEREIGN,
    SUCCESSION_AT,
    T0,
    build_pack,
    build_world,
    canonical,
    frozen_pack,
    pub,
    sha256,
    uid,
)


def _history(inp: dict[str, Any]) -> Any:
    from genesis_mesh.trust.key_succession import verify_key_history

    result = verify_key_history(inp["genesis"], inp["successions"], inp["root_public_key"])
    assert result.history is not None, result.failures
    return result.history


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evaluate(vector: dict[str, Any]) -> dict[str, Any]:
    """What the Python reference makes of one vector's input (the runner compares it with ``expected``)."""
    from genesis_mesh.models.canonical_registry import received_canonical
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.models.evidence_store import EvidenceEvent, StoreAnchor
    from genesis_mesh.trust.context import verify_boundary_decision
    from genesis_mesh.trust.evidence_store import (
        ExecutorKey,
        parse_export_lines,
        verify_evidence_events,
        verify_store_anchors,
    )
    from genesis_mesh.trust.key_succession import verify_key_history
    from genesis_mesh.workflows.audit_pack import Change, check_completeness, verify_audit_pack

    kind, inp = vector["kind"], vector.get("input", {})

    def executor_keys(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {r["key_id"]: ExecutorKey(key_id=r["key_id"], public_key=r["public_key"],
                                         executor_sovereign_id=r["executor_sovereign_id"], role=r["role"],
                                         resource_prefix=r.get("resource_prefix")) for r in rows}

    def changes_of(rows: list[dict[str, Any]]) -> list[Any]:
        return [Change(index=i, resource_id=c["resource_id"], action=c["action"], changed_at=_when(c["changed_at"]),
                       source=c.get("source"), source_event_id=c.get("source_event_id"), actor=c.get("actor"))
                for i, c in enumerate(rows, start=1)]

    if kind == "canonical_form":
        body = received_canonical(vector["model"], vector["record"])
        return {"canonical": body, "digest": hashlib.sha256(body.encode()).hexdigest()}
    if kind == "key_history":
        result = verify_key_history(inp["genesis"], inp["successions"], inp["root_public_key"])
        return {"verified": result.verified,
                "failures": [{"key_sequence": f["key_sequence"], "reason": f["reason"]} for f in result.failures],
                "keys": [k.to_dict() for k in result.history.keys] if result.history else []}
    if kind == "key_at":
        return {"keys": _history(inp).keys_at(_when(inp["at"]))}
    if kind == "verify_export":
        events = parse_export_lines(inp["lines"].split("\n"))
        result = verify_evidence_events(events, na_public_keys=_history(inp),
                                        executor_keys=executor_keys(inp["executor_keys"]))
        return {"failures": [{"store_sequence": f["store_sequence"], "reason": f["reason"]} for f in result.failures]}
    if kind == "verify_anchors":
        anchors = [StoreAnchor.model_validate(a) for a in inp["anchors"]]
        result = verify_store_anchors(anchors, na_public_keys=_history(inp), sovereign_id=inp["genesis"]["network_name"])
        return {"failures": [{"anchor_sequence": f["anchor_sequence"], "reason": f["reason"]} for f in result.failures]}
    if kind == "decision_at_record_time":
        decision = BoundaryDecision.model_validate(inp["decision"])
        history = _history(inp)
        return {"at_record_time": verify_boundary_decision(decision, history, at_record_time=True).reason,
                "now": verify_boundary_decision(decision, history, now=_when(inp["now"])).reason}
    if kind == "pack":
        files = {path: text.encode("utf-8") for path, text in inp["files"].items()}
        held = [StoreAnchor.model_validate(a) for a in inp["held_anchors"]] if inp["held_anchors"] is not None else None
        changes = changes_of(inp["changes"]) if inp.get("changes") is not None else None
        result = verify_audit_pack(files, root_public_key=inp["root_public_key"], held_anchors=held, changes=changes)
        out: dict[str, Any] = {"verified": result.verified, "reasons": result.reasons(),
                               "warnings": sorted({w["reason"] for w in result.warnings})}
        if result.completeness is not None:
            out["unmatched_changes"] = [c["index"] for c in result.completeness["unmatched_changes"]]
        return out
    if kind == "completeness":
        events = [EvidenceEvent.received(json.loads(line)) for line in inp["lines"].split("\n") if line]
        report = check_completeness(changes_of(inp["changes"]), events,
                                    period=(_when(inp["period"][0]), _when(inp["period"][1])),
                                    tolerance=timedelta(seconds=inp["tolerance_seconds"]))
        return {"pairs": [[p["change"], p["record_id"], p["matched_by"]] for p in report["pairs"]],
                "unmatched_changes": [c["index"] for c in report["unmatched_changes"]],
                "outside_period": [c["index"] for c in report["outside_period"]],
                "unmatched_records": [rec["record_id"] for rec in report["unmatched_records"]]}
    raise ValueError(f"unknown vector kind {kind!r}")


def _lines(events: list[Any]) -> str:
    return "".join(e.to_json_line() + "\n" for e in events)


def _relink(events: list[Any]) -> list[Any]:
    """Events re-chained after a payload changed (as a database writer would), positions kept."""
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest

    out: list[Any] = []
    prev: str | None = None
    for event in events:
        entry = event.entry.model_copy(update={"payload_digest": payload_digest(event.payload),
                                               "prev_entry_digest": prev})
        out.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=event.payload))
        prev = entry.digest()
    return out


def _text(files: dict[str, bytes]) -> dict[str, str]:
    return {path: body.decode("utf-8") for path, body in sorted(files.items())}


def resigned(files: dict[str, bytes], changed: dict[str, bytes | None], *, key: str = "g", key_id: str = "na-2",
             **manifest_changes: Any) -> dict[str, bytes]:
    """Files changed (or removed, ``None``) and a new manifest signed with an NA key: what its holder can do."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.audit_pack import MANIFEST_FILE, AuditPackManifest, PackFile

    out = {**files}
    for path, body in changed.items():
        if body is None:
            out.pop(path, None)
        else:
            out[path] = body
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    manifest = manifest.model_copy(update={**manifest_changes, "signature": None, "files": [
        PackFile(path=p, sha256=sha256(b), bytes=len(b)) for p, b in sorted(out.items()) if p != MANIFEST_FILE]})
    manifest = manifest.model_copy(update={"signature": sign_model(manifest, KEYS[key], key_id)})
    out[MANIFEST_FILE] = manifest.file_bytes()
    return out


def pack_variants(world: Any, frozen: dict[str, bytes]) -> list[tuple[str, str, dict[str, Any]]]:
    """(id, description, input) of every pack case: the frozen pack, valid and refused variants."""
    from genesis_mesh.models.audit_pack import ANCHORS_FILE, CITED_FILE, ENTRIES_FILE
    from genesis_mesh.models.evidence_store import EvidenceEvent
    from genesis_mesh.trust.evidence_store import sign_store_anchor

    root = pub("f")
    held = [a.to_wire() for a in world.anchors]
    base = {"root_public_key": root, "held_anchors": held}
    whole = build_pack(world, start=1, through=world.anchors[-1].store_sequence, pack_id=uid(803),
                       created_at=SUCCESSION_AT + timedelta(days=5), cited_sequences=[])
    cases: list[tuple[str, str, dict[str, Any]]] = [
        ("pack-whole-store", "A pack of the whole store, from entry 1", {**base, "files": _text(whole)}),
        ("pack-frozen-1.5.0", "The frozen 1.5.0 pack: after anchor 1, across the succession",
         {**base, "files": _text(frozen)}),
    ]
    entries = bytearray(frozen[ENTRIES_FILE])
    entries[entries.index(b"rotate")] = ord("R")
    cases += [
        ("pack-tampered-file", "A file changed after the manifest was signed",
         {**base, "files": _text({**frozen, ENTRIES_FILE: bytes(entries)})}),
        ("pack-unlisted-file", "A file the manifest does not list",
         {**base, "files": _text({**frozen, "extra.txt": b"x\n"})}),
        ("pack-root-mismatch", "Another root key: the pack's keys prove nothing alone",
         {**base, "root_public_key": pub("c"), "files": _text(frozen)}),
        ("pack-end-anchor-not-held", "The auditor does not hold the anchor that ends the range",
         {**base, "held_anchors": held[:-1], "files": _text(frozen)}),
        ("pack-no-held-anchors", "Without held anchors: the integrity of what is present only",
         {**base, "held_anchors": None, "files": _text(frozen)}),
    ]
    lines = frozen[ENTRIES_FILE].decode().splitlines(keepends=True)
    executions = [i for i, line in enumerate(lines) if '"entry_kind":"execution"' in line]
    removed = "".join(line for i, line in enumerate(lines) if i != executions[-1]).encode()
    cases.append(("pack-removed-record", "A record removed by someone holding the NA key, the manifest signed again",
                  {**base, "files": _text(resigned(frozen, {ENTRIES_FILE: removed}))}))
    cited_lines = frozen[CITED_FILE].decode().splitlines(keepends=True)
    no_head = "".join(line for line in cited_lines if '"entry_kind":"execution"' not in line).encode()
    cases.append(("pack-head-missing", "A pack without the record its resource chain continues from",
                  {**base, "files": _text(resigned(frozen, {CITED_FILE: no_head}))}))
    # A rewritten range: the last execution removed, the chain re-linked and re-anchored with the NA key.
    events = [EvidenceEvent.received(json.loads(line)) for line in lines]
    kept = [e for i, e in enumerate(events) if i != executions[-1]]
    rebuilt, prev = [], events[0].entry.prev_entry_digest
    for i, e in enumerate(kept):
        entry = e.entry.model_copy(update={"store_sequence": events[0].entry.store_sequence + i,
                                           "prev_entry_digest": prev})
        rebuilt.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=e.payload))
        prev = entry.digest()
    anchors = [a for a in world.anchors if a.store_sequence >= events[0].entry.store_sequence - 1]
    forged_end = sign_store_anchor(anchors[-1].model_copy(update={
        "store_sequence": rebuilt[-1].entry.store_sequence, "entry_digest": prev, "signature": None}),
        KEYS["g"], "na-2")
    rewritten = resigned(frozen, {ENTRIES_FILE: _lines(rebuilt).encode(),
                                  ANCHORS_FILE: "".join(canonical(a.to_wire()) + "\n"
                                                        for a in [*anchors[:-1], forged_end]).encode()},
                         through_sequence=rebuilt[-1].entry.store_sequence)
    cases.append(("pack-rewritten-re-anchored", "A range rewritten without a record, re-linked and re-anchored "
                  "with the NA key", {**base, "files": _text(rewritten)}))
    second = world.records["second"]
    changes = [
        {"source": "cloud-activity-log", "source_event_id": "event-0002", "resource_id": RESOURCE, "action": "rotate",
         "changed_at": second.executed_at.isoformat()},
        {"resource_id": RESOURCE, "action": "update", "changed_at": second.executed_at.isoformat()},
    ]
    cases.append(("pack-unmatched-change", "A change from an outside log that no record of the pack matches",
                  {**base, "files": _text(frozen), "changes": changes}))
    return cases


def audit_vectors() -> list[dict[str, Any]]:
    """Every vector of the ``audit`` suite, ``expected`` filled in by the reference."""
    from genesis_mesh.crypto import sign_data, sign_model
    from genesis_mesh.models.audit_pack import MANIFEST_FILE
    from genesis_mesh.models.evidence_store import EvidenceEvent
    from genesis_mesh.models.key_succession import KeySuccessionRecord
    from genesis_mesh.trust.evidence_store import sign_store_anchor
    from genesis_mesh.trust.key_succession import sign_succession

    world = build_world()
    r = world.records
    root = pub("f")
    base = {"genesis": world.genesis, "successions": world.successions, "root_public_key": root}
    vectors: list[dict[str, Any]] = []

    def add(vid: str, kind: str, description: str, **fields: Any) -> None:
        vector = {"id": vid, "kind": kind, "description": description, **fields}
        vector["expected"] = evaluate(vector)
        vectors.append(vector)

    # Canonical forms of the new signed records.
    frozen = frozen_pack(world)
    for model, record in (("KeySuccessionRecord", r["succession"].to_wire()), ("ArchiveRecord", r["archive"].to_wire()),
                          ("AuditPackManifest", json.loads(frozen[MANIFEST_FILE]))):
        add(f"canonical-{model}", "canonical_form", f"The signed form of a {model}", model=model, record=record)

    # The key history.
    succession = r["succession"]
    unsigned = succession.model_copy(update={"signatures": []})

    def both(record: Any) -> dict[str, Any]:
        return sign_succession(sign_succession(record.model_copy(update={"signatures": []}), KEYS["f"], "root"),
                               KEYS["c"], "na-1").to_wire()

    def signed_raw(body: dict[str, Any]) -> dict[str, Any]:
        data = canonical(body).encode()
        return {**body, "signatures": [{"key_id": "root", "sig": sign_data(data, KEYS["f"])},
                                       {"key_id": "na-1", "sig": sign_data(data, KEYS["c"])}]}

    third = KeySuccessionRecord(
        succession_id=uid(402), sovereign_id=SOVEREIGN, key_sequence=3, previous_key_id="na-2",
        previous_public_key=pub("g"), previous_succession_digest=succession.digest(), new_key_id="na-3",
        new_public_key=pub("a"), effective_at=succession.new_valid_to + timedelta(days=1),
        new_valid_to=succession.new_valid_to + timedelta(days=400), issued_at=succession.new_valid_to,
    )
    late = sign_succession(sign_succession(third, KEYS["f"], "root"), KEYS["g"], "na-2").to_wire()
    body = {k: v for k, v in succession.to_wire().items() if k != "signatures"}
    history_cases = [
        ("genesis-only", "The genesis key alone", [], root),
        ("one-succession", "The genesis key and one succession", world.successions, root),
        ("root-mismatch", "A root key the genesis block does not name", world.successions, pub("c")),
        ("root-signature", "A succession the root key did not sign",
         [sign_succession(unsigned, KEYS["c"], "na-1").to_wire()], root),
        ("previous-signature", "A succession the outgoing key did not sign",
         [sign_succession(unsigned, KEYS["f"], "root").to_wire()], root),
        ("chain-break", "A succession that does not continue the history (wrong position)",
         [both(succession.model_copy(update={"key_sequence": 3}))], root),
        ("key-reused", "A succession naming a key the history already held",
         [both(succession.model_copy(update={"new_public_key": pub("c")}))], root),
        ("not-increasing", "A succession whose new key ends before it starts",
         [both(succession.model_copy(update={"new_valid_to": succession.effective_at}))], root),
        ("sovereign-mismatch", "A succession of another sovereign",
         [both(succession.model_copy(update={"sovereign_id": "sovereign-x"}))], root),
        ("after-expiry", "A succession taking effect after the previous key's enforced end",
         [*world.successions, late], root),
        ("unknown-field", "A succession signed over a field this release does not know",
         [signed_raw({**body, "x_added_field": 1})], root),
        ("unsigned-field", "A succession with a field outside its signatures",
         [{**succession.to_wire(), "x_added_field": 1}], root),
        ("payload-invalid", "A succession missing a field",
         [{k: v for k, v in succession.to_wire().items() if k != "new_valid_to"}], root),
    ]
    for vid, description, successions, anchor_key in history_cases:
        add(f"history-{vid}", "key_history", description,
            input={"genesis": world.genesis, "successions": successions, "root_public_key": anchor_key})
    add("history-genesis-tampered", "key_history", "A genesis block changed after the root key signed it",
        input={"genesis": {**world.genesis, "network_version": "v9"}, "successions": [], "root_public_key": root})

    # Which key a record dated at a time may be signed with.
    for vid, at, description in (
        ("long-before", T0 - timedelta(days=365), "Long before the genesis block: the genesis key's start is not "
         "enforced"),
        ("genesis-window", T0 + timedelta(days=9), "Within the genesis key's window"),
        ("before-succession", SUCCESSION_AT - timedelta(seconds=1), "Just before the succession takes effect"),
        ("at-succession", SUCCESSION_AT, "When the succession takes effect: both keys (hand-over)"),
        ("handover-end", SUCCESSION_AT + timedelta(seconds=299), "The last second of the hand-over"),
        ("after-handover", SUCCESSION_AT + timedelta(seconds=300), "After the hand-over: the new key only"),
        ("after-new-valid-to", succession.new_valid_to, "At the new key's enforced end: no key"),
    ):
        add(f"key-at-{vid}", "key_at", description, input={**base, "at": at.isoformat().replace("+00:00", "Z")})
    add("key-at-genesis-valid-to-not-enforced", "key_at",
        "Without a succession, long after the genesis block's valid_to: the genesis key's end is not enforced",
        input={**base, "successions": [], "at": (T0 + timedelta(days=400)).isoformat().replace("+00:00", "Z")})

    # Exports across the succession.
    keys_file = world.keys_file()
    add("export-across-succession", "verify_export", "The whole store, signed by both keys, with the key history",
        input={**base, "lines": _lines(world.events), "executor_keys": keys_file})
    judgement_event = next(e for e in world.events if e.entry.entry_kind == "judgement")
    forged = r["judgement"].model_copy(update={"signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, KEYS["c"], "na-1")}).to_wire()
    swapped = _relink([EvidenceEvent(entry=e.entry, entry_digest=e.entry_digest,
                                     payload=forged if e is judgement_event else e.payload) for e in world.events])
    add("export-outgoing-key-after-handover", "verify_export",
        "A judgement recorded after the hand-over but signed by the outgoing key",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})
    decision_event = next(e for e in world.events if e.entry.entry_kind == "decision")
    early = r["first_decision"].model_copy(update={"signature": None})
    early = early.model_copy(update={"signature": sign_model(early, KEYS["g"], "na-2")})
    swapped = _relink([EvidenceEvent(entry=e.entry, entry_digest=e.entry_digest,
                                     payload={**e.payload, "decision": early.model_dump(mode="json")}
                                     if e is decision_event else e.payload) for e in world.events])
    add("export-new-key-before-succession", "verify_export",
        "A decision recorded before the succession but signed by the new key",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})
    stray = both(succession.model_copy(update={"succession_id": uid(499), "new_key_id": "na-x",
                                               "new_public_key": pub("a")}))
    swapped = _relink([EvidenceEvent(entry=e.entry.model_copy(update={"record_id": uid(499)})
                                     if e.entry.entry_kind == "key_succession" else e.entry,
                                     entry_digest=e.entry_digest,
                                     payload=stray if e.entry.entry_kind == "key_succession" else e.payload)
                       for e in world.events])
    add("export-succession-not-in-history", "verify_export",
        "A succession entry signed by the root and outgoing keys that the key history does not hold",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})

    # Anchors across the succession.
    add("anchors-across-succession", "verify_anchors", "Anchors signed by both keys, each at its time",
        input={**base, "anchors": [a.to_wire() for a in world.anchors]})
    resigned_anchor = sign_store_anchor(world.anchors[-1].model_copy(update={"signature": None}), KEYS["c"], "na-1")
    add("anchors-outgoing-key", "verify_anchors", "An anchor after the hand-over signed by the outgoing key",
        input={**base, "anchors": [a.to_wire() for a in world.anchors[:-1]] + [resigned_anchor.to_wire()]})

    # A decision judged as of its own time, not now.
    add("decision-at-record-time", "decision_at_record_time",
        "An archived decision: valid when it was made, expired since",
        input={**base, "decision": r["first_decision"].model_dump(mode="json"), "now": "2030-01-01T00:00:00Z"})

    # Packs.
    for vid, description, inp in pack_variants(world, frozen):
        add(vid, "pack", description, input=inp)

    # The completeness check alone.
    stored = [e for e in world.events if e.entry.entry_kind in ("execution", "observation", "judgement")]
    second = r["second"]
    add("completeness-matching", "completeness",
        "By source event, then by resource, action and time; an observation and the execution it matched are one "
        "change; a change outside the period is not missing", input={
            "lines": _lines(stored), "tolerance_seconds": 300,
            "period": [T0.isoformat(), (SUCCESSION_AT + timedelta(days=5)).isoformat()],
            "changes": [
                {"source": "cloud-activity-log", "source_event_id": "event-0002", "resource_id": RESOURCE,
                 "action": "rotate", "changed_at": second.executed_at.isoformat()},
                {"resource_id": RESOURCE, "action": "create", "changed_at": r["first"].executed_at.isoformat()},
                {"resource_id": RESOURCE, "action": "delete",
                 "changed_at": (SUCCESSION_AT + timedelta(days=2)).isoformat()},
                {"resource_id": RESOURCE, "action": "delete", "changed_at": (T0 - timedelta(days=30)).isoformat()},
            ]})
    return vectors
