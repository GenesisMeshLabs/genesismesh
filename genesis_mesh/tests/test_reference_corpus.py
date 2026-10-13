"""The verification corpus for a second verifier (v1.5.0): complete, runnable and deterministic.

``scripts/export_reference_corpus.py --suite verification`` writes every
entry kind (valid, tampered, an unknown field signed and unsigned, a
timestamp re-canonicalized, an NA key not valid at the record's time),
exports and key histories across a succession and every pack case, each
with the Python reference's verdict. A second verifier passes the corpus when
it reaches every verdict; the reference runs it the same way here.
"""

from __future__ import annotations

import importlib.util
import json
import typing
from pathlib import Path

from genesis_mesh.models.evidence_store import EntryKind

ROOT = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location("export_reference_corpus",
                                                  ROOT / "scripts" / "export_reference_corpus.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def test_the_verification_corpus_covers_every_kind_runs_and_is_deterministic(tmp_path):
    script = _script()
    first = script.export_verification(tmp_path / "one")
    script.export_verification(tmp_path / "two")
    assert _tree(tmp_path / "one" / "verification") == _tree(tmp_path / "two" / "verification")
    assert script.check_verification(tmp_path / "one" / "verification") == []

    ids = {case["id"] for case in first["cases"]}
    for kind in typing.get_args(EntryKind):
        for variant in ("valid", "tampered", "unknown-field-signed", "unknown-field-unsigned"):
            assert f"record-{kind}-{variant}" in ids, (kind, variant)
    assert {"pack-frozen-1.5.0", "pack-tampered-file", "pack-removed-record", "pack-rewritten-re-anchored",
            "export-across-succession", "history-root-signature"} <= ids
    valid = [c for c in first["cases"] if c["id"].endswith("-valid")]
    assert valid and all(c["expected"]["verified"] for c in valid)
    copied = json.loads((tmp_path / "one" / "verification" / "vectors" / "audit.json").read_text(encoding="utf-8"))
    assert copied["suite"] == "audit"
