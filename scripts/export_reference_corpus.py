"""Export the reference corpus a second implementation runs against the Python reference.

    python scripts/export_reference_corpus.py --suite verification [--out build/reference-corpus]

``--suite verification`` (v1.5.0, the independent verifier ``genesis-mesh-verify``)
writes ``<out>/verification/``:

``corpus.json``
    The index: every case with its command, its files and the Python
    reference's verdict (``expected``), and the fixed public keys.
``records/<case>/``
    One signed record of every entry kind, wrapped as a one-entry export
    (``export.jsonl``) and bare (``record.json``), with the key history
    (``key-history.json``: the genesis block and the successions),
    ``root.pub`` and ``executor-keys.json``. For each kind: valid, tampered
    (a signed value changed), an unknown field signed and unsigned, a
    timestamp re-canonicalized with and without a new signature, and for an
    NA-signed kind a signature by an NA key not valid at the record's time.
``exports/<case>/``
    Whole exports across an NA key succession, valid and refused.
``key-history/<case>/``
    Genesis blocks and successions, each refusal by name.
``packs/<case>/``
    Audit packs (``pack/``) with ``root.pub``, the held ``anchors.json`` and,
    for the completeness check, ``changes.json``: the frozen 1.5.0 pack,
    valid packs and every refusal the conformance suite holds.
``vectors/``
    The conformance suites a verifier runs as well (``canonical``,
    ``field_registry``, ``interop``, ``out_of_band``, ``remediation``,
    ``audit``), copied unchanged.

Everything is deterministic: fixed seeds, times and identifiers, and
Ed25519 signatures, so two runs write the same bytes. A difference between a
verifier and ``expected`` is a bug in one of them, resolved against the
specification (``docs/reference/audit-pack-format.md``).
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
COPIED_SUITES = ("canonical", "field_registry", "interop", "out_of_band", "remediation", "audit")


def _dump(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _record_cases() -> list[dict[str, Any]]:
    """One case per entry kind and variant: (id, kind, payload, envelope index, expected verdict)."""
    sys.path.insert(0, str(CONFORMANCE))
    import audit_world as world_module  # noqa: E402
    import generate_vectors as gv  # noqa: E402

    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.canonical_registry import received_canonical
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest
    from genesis_mesh.trust.evidence_store import (
        ExecutorKey,
        build_entry,
        decision_index,
        execution_index,
        verify_evidence_events,
    )
    from genesis_mesh.trust.key_succession import verify_key_history
    from genesis_mesh.trust.out_of_band import entry_index

    world = world_module.build_world()
    history = verify_key_history(world.genesis, world.successions, world_module.pub("f")).history
    assert history is not None
    keys = {
        "executor-b": ExecutorKey("executor-b", gv.pub_b64("b"), gv.SOV_B, role="executor"),
        "observer-b": ExecutorKey("observer-b", gv.pub_b64("b"), gv.SOV_B, role="observer"),
    }
    samples = gv._registry_samples()
    recorded_at = world_module.T0 + timedelta(hours=1)
    na = ("c", "na-key")
    executor = ("b", "executor-b")
    kinds: dict[str, tuple[str, dict[str, Any], tuple[str, str]]] = {
        "registry": ("RegistryRecord", samples["RegistryRecord"], na),
        "judgement": ("JudgementRecord", samples["JudgementRecord"], na),
        "quarantine": ("QuarantineRecord", samples["QuarantineRecord"], na),
        "observation": ("ObservationRecord", samples["ObservationRecord"], ("b", "observer-b")),
        "break_glass": ("BreakGlassRecord", samples["BreakGlassRecord"], executor),
        "remediation": ("RemediationRecord", samples["RemediationRecord"], executor),
        "review": ("ReviewRecord", samples["ReviewRecord"], na),
        "retention_checkpoint": ("RetentionCheckpoint", samples["RetentionCheckpoint"], na),
        "justification": ("JustificationProof", samples["JustificationProof"], na),
        "execution": ("ExecutionEvidence", samples["ExecutionEvidence"], executor),
        "archive": ("ArchiveRecord", samples["ArchiveRecord"], na),
        "decision": ("BoundaryDecision", world.records["first_decision"].model_dump(mode="json"), na),
        "key_succession": ("KeySuccessionRecord", world.successions[0], ("f", "root")),
    }
    quarantined = copy.deepcopy(kinds["quarantine"][1])
    quarantined["record_digest"] = payload_digest(quarantined["record"])
    kinds["quarantine"] = ("QuarantineRecord", quarantined, na)
    decision_event = next(e for e in world.events if e.entry.entry_kind == "decision")

    def sign(model: str, record: dict[str, Any], signer: tuple[str, str]) -> dict[str, Any]:
        """The record signed as received by ``signer`` (a key succession by the root and the outgoing key)."""
        out = {k: v for k, v in record.items() if k not in ("signature", "signatures")}
        body = received_canonical(model, out).encode("utf-8")
        if model == "KeySuccessionRecord":
            out["signatures"] = [{"key_id": "root", "sig": sign_data(body, world_module.KEYS["f"])},
                                 {"key_id": "na-1", "sig": sign_data(body, world_module.KEYS["c"])}]
        else:
            seed = signer[0]
            key = world_module.KEYS[seed] if seed in world_module.KEYS else gv.KEYS[seed]
            out["signature"] = {"key_id": signer[1], "sig": sign_data(body, key)}
        return out

    def timestamp_field(model: str, record: dict[str, Any]) -> str | None:
        from genesis_mesh.models.canonical_registry import build_registry

        fields = build_registry()["models"][model]["fields"]
        return next((f for f in sorted(fields) if fields[f] == "timestamp" and isinstance(record.get(f), str)
                     and record[f].endswith("Z")), None)

    def string_field(model: str, record: dict[str, Any]) -> str:
        preferred = ("resource_id", "reason", "justification", "location", "holder", "key_id", "new_key_id",
                     "denial_reason", "operator_sovereign_id", "issued_by", "proof_id", "outcome")
        return next(f for f in preferred if isinstance(record.get(f), str))

    cases: list[dict[str, Any]] = []
    for kind, (model, sample, signer) in sorted(kinds.items()):
        valid = sign(model, sample, signer)
        stamp = timestamp_field(model, valid)
        field = string_field(model, valid)
        variants: list[tuple[str, dict[str, Any]]] = [("valid", valid)]
        variants.append(("tampered", {**valid, field: str(valid[field]) + "-changed"}))
        variants.append(("unknown-field-signed", sign(model, {**valid, "x_added_field": 1}, signer)))
        variants.append(("unknown-field-unsigned", {**valid, "x_added_field": 1}))
        if stamp is not None:
            respelled = {**valid, stamp: valid[stamp][:-1] + "+00:00"}
            variants.append(("recanonicalized-unsigned", respelled))
            variants.append(("recanonicalized-signed", sign(model, respelled, signer)))
        if signer[0] == "c":
            variants.append(("na-key-not-valid-at-time", sign(model, valid, ("g", "na-2"))))
        for variant, record in variants:
            if kind == "decision":
                payload = {"decision": record, "context": decision_event.payload["context"]}
                from genesis_mesh.models.context import BoundaryDecision, ContextRecord

                try:
                    index = decision_index(BoundaryDecision.model_validate(record),
                                           ContextRecord.model_validate(payload["context"]))
                except ValueError:
                    index = dict(decision_event.entry.model_dump(include={"decision_id", "context_id"}))
            else:
                payload = record
                index = _index(kind, model, record, entry_index, execution_index)
            entry = build_entry(store_sequence=1000, entry_kind=kind, recorded_at=recorded_at, payload=payload,
                                prev_entry_digest="0" * 64, index=index)
            event = EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=payload)
            result = verify_evidence_events([event], na_public_keys=history, executor_keys=keys)
            cases.append({
                "id": f"record-{kind}-{variant}", "kind": kind, "model": model, "record": record,
                "line": event.to_json_line(),
                "expected": {"verified": result.verified,
                             "failures": [{"store_sequence": f["store_sequence"], "reason": f["reason"]}
                                          for f in result.failures]},
            })
    return cases


def _index(kind: str, model: str, record: dict[str, Any], entry_index: Any, execution_index: Any) -> dict[str, Any]:
    """The envelope fields the NA writes for a record (as written when it is admitted)."""
    from genesis_mesh.models import audit_pack, key_succession, out_of_band, remediation
    from genesis_mesh.models.execution import ExecutionEvidence

    classes = {
        "ObservationRecord": out_of_band.ObservationRecord, "BreakGlassRecord": out_of_band.BreakGlassRecord,
        "JudgementRecord": out_of_band.JudgementRecord, "QuarantineRecord": out_of_band.QuarantineRecord,
        "RegistryRecord": out_of_band.RegistryRecord, "RemediationRecord": remediation.RemediationRecord,
        "ReviewRecord": remediation.ReviewRecord, "ArchiveRecord": audit_pack.ArchiveRecord,
        "KeySuccessionRecord": key_succession.KeySuccessionRecord,
    }
    clean = {k: v for k, v in record.items() if k != "x_added_field"}
    try:
        if model in classes:
            return dict(entry_index(kind, classes[model].model_validate(clean)))
        if model == "ExecutionEvidence":
            return dict(execution_index(ExecutionEvidence.model_validate(clean), {}))
    except ValueError:
        pass
    return {}


def export_verification(out: Path) -> dict[str, Any]:
    """Write the verification corpus under ``out`` and return its index."""
    sys.path.insert(0, str(CONFORMANCE))
    import audit_vectors  # noqa: E402
    import audit_world  # noqa: E402

    target = out / "verification"
    if target.exists():
        shutil.rmtree(target)
    world = audit_world.build_world()
    keys_file = world.keys_file()
    root = audit_world.pub("f")
    history_file = {"genesis": world.genesis, "successions": world.successions}
    cases: list[dict[str, Any]] = []

    for case in _record_cases():
        directory = target / "records" / case["id"]
        _write(directory / "export.jsonl", (case["line"] + "\n").encode("utf-8"))
        _write(directory / "record.json", _dump({"kind": case["kind"], "model": case["model"],
                                                 "record": case["record"]}))
        _write(directory / "key-history.json", _dump(history_file))
        _write(directory / "root.pub", (root + "\n").encode())
        _write(directory / "executor-keys.json", _dump({"executor_keys": [
            {"key_id": "executor-b", "public_key": audit_world.pub("b"), "executor_sovereign_id": "sovereign-b",
             "role": "executor"},
            {"key_id": "observer-b", "public_key": audit_world.pub("b"), "executor_sovereign_id": "sovereign-b",
             "role": "observer"}]}))
        cases.append({"id": case["id"], "command": "export", "kind": case["kind"],
                      "path": f"records/{case['id']}", "expected": case["expected"]})

    for vector in audit_vectors.audit_vectors():
        kind, inp = vector["kind"], vector.get("input", {})
        if kind == "verify_export":
            directory = target / "exports" / vector["id"]
            _write(directory / "export.jsonl", inp["lines"].encode("utf-8"))
            _write(directory / "key-history.json", _dump({"genesis": inp["genesis"],
                                                         "successions": inp["successions"]}))
            _write(directory / "root.pub", (inp["root_public_key"] + "\n").encode())
            _write(directory / "executor-keys.json", _dump({"executor_keys": inp["executor_keys"]}))
            cases.append({"id": vector["id"], "command": "export", "kind": "export",
                          "path": f"exports/{vector['id']}", "expected": vector["expected"]})
        elif kind == "key_history":
            directory = target / "key-history" / vector["id"]
            _write(directory / "key-history.json", _dump({"genesis": inp["genesis"],
                                                         "successions": inp["successions"]}))
            _write(directory / "root.pub", (inp["root_public_key"] + "\n").encode())
            cases.append({"id": vector["id"], "command": "key-history", "kind": "key_history",
                          "path": f"key-history/{vector['id']}", "expected": vector["expected"]})
        elif kind == "pack":
            directory = target / "packs" / vector["id"]
            for path, text in inp["files"].items():
                _write(directory / "pack" / path, text.encode("utf-8"))
            _write(directory / "root.pub", (inp["root_public_key"] + "\n").encode())
            if inp["held_anchors"] is not None:
                _write(directory / "anchors.json", _dump(inp["held_anchors"]))
            if inp.get("changes") is not None:
                _write(directory / "changes.json", _dump({"changes": inp["changes"]}))
            cases.append({"id": vector["id"], "command": "pack", "kind": "pack", "path": f"packs/{vector['id']}",
                          "expected": vector["expected"]})

    for name in COPIED_SUITES:
        _write(target / "vectors" / f"{name}.json", (CONFORMANCE / "vectors" / f"{name}.json").read_bytes())

    index = {
        "suite": "verification", "version": "1.5.0",
        "keys": {"root": root, "na": [audit_world.pub("c"), audit_world.pub("g")],
                 "executor": audit_world.pub("b"), "observer": audit_world.pub("a")},
        "commands": {
            "export": "verify export.jsonl with the key history from root.pub and executor-keys.json; "
                      "expected: verified and failures (store_sequence, reason)",
            "key-history": "verify key-history.json from root.pub; expected: verified, failures, keys",
            "pack": "verify pack/ from root.pub and anchors.json (none: no held anchors), with changes.json "
                    "when present; expected: verified, sorted failure reasons, warnings",
        },
        "cases": sorted(cases, key=lambda c: c["id"]),
    }
    _write(target / "corpus.json", _dump(index))
    return index


def check_verification(directory: Path) -> list[str]:
    """Run every case of a written corpus with the Python reference, as a second verifier would run it,
    and return the cases whose verdict differs from ``expected``."""
    from genesis_mesh.models.evidence_store import StoreAnchor
    from genesis_mesh.trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
    from genesis_mesh.trust.key_succession import verify_key_history
    from genesis_mesh.workflows.audit_pack import parse_changes, read_pack_dir, verify_audit_pack

    index = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
    differences: list[str] = []
    for case in index["cases"]:
        path = directory / case["path"]
        root = (path / "root.pub").read_text(encoding="utf-8").strip()
        got: dict[str, Any]
        if case["command"] == "key-history":
            data = json.loads((path / "key-history.json").read_text(encoding="utf-8"))
            result = verify_key_history(data["genesis"], data["successions"], root)
            got = {"verified": result.verified,
                   "failures": [{"key_sequence": f["key_sequence"], "reason": f["reason"]} for f in result.failures],
                   "keys": [k.to_dict() for k in result.history.keys] if result.history else []}
        elif case["command"] == "export":
            data = json.loads((path / "key-history.json").read_text(encoding="utf-8"))
            history = verify_key_history(data["genesis"], data["successions"], root).history
            rows = json.loads((path / "executor-keys.json").read_text(encoding="utf-8"))["executor_keys"]
            keys = {r["key_id"]: ExecutorKey(r["key_id"], r["public_key"], r["executor_sovereign_id"],
                                             role=r["role"], resource_prefix=r.get("resource_prefix")) for r in rows}
            events = parse_export_lines((path / "export.jsonl").read_bytes().decode("utf-8").split("\n"))
            verified = verify_evidence_events(events, na_public_keys=history, executor_keys=keys)
            failures = [{"store_sequence": f["store_sequence"], "reason": f["reason"]} for f in verified.failures]
            got = {"verified": verified.verified, "failures": failures} if "verified" in case["expected"] \
                else {"failures": failures}
        else:
            held = None
            if (path / "anchors.json").exists():
                held = [StoreAnchor.model_validate(a)
                        for a in json.loads((path / "anchors.json").read_text(encoding="utf-8"))]
            changes = None
            if (path / "changes.json").exists():
                changes = parse_changes((path / "changes.json").read_text(encoding="utf-8"), csv_format=False)
            pack = verify_audit_pack(read_pack_dir(path / "pack"), root_public_key=root, held_anchors=held,
                                     changes=changes)
            got = {"verified": pack.verified, "reasons": pack.reasons(),
                   "warnings": sorted({w["reason"] for w in pack.warnings})}
            if pack.completeness is not None:
                got["unmatched_changes"] = [c["index"] for c in pack.completeness["unmatched_changes"]]
        if got != case["expected"]:
            differences.append(f"{case['id']}: got {got}, want {case['expected']}")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--suite", required=True, choices=["verification"])
    parser.add_argument("--out", default=str(ROOT / "build" / "reference-corpus"))
    parser.add_argument("--check", action="store_true",
                        help="Run every case of the corpus written at --out with the Python reference.")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    if args.check:
        differences = check_verification(Path(args.out) / "verification")
        for line in differences:
            print(line)
        print("corpus verdicts " + ("differ" if differences else "match the reference"))
        return 1 if differences else 0
    index = export_verification(Path(args.out))
    print(f"wrote {len(index['cases'])} cases to {Path(args.out) / 'verification'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
