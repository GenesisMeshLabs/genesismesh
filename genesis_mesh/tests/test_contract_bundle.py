"""v1.11.0: the contract bundle (``scripts/gm_contract.py``, ``contract/bundle.json``).

The committed manifest and kind table must match what the tools generate, the
spec must give every suite a tier decision, and the release archive must be
reproducible. The negative paths run against a small synthetic core tree.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import tarfile
import typing
from pathlib import Path
from types import ModuleType

import pytest

from genesis_mesh.models.evidence_store import EntryKind
from genesis_mesh.trust.evidence_store import kind_registry

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gm = _load("gm_contract")


# ── the committed bundle ──────────────────────────────────────────────────────


def test_committed_kind_table_matches_the_registry() -> None:
    render = _load("render_contract_kinds")
    assert (ROOT / "contract" / "kinds.json").read_bytes() == render.rendered(), (
        "run `python scripts/render_contract_kinds.py`")


def test_kind_table_covers_every_entry_kind_and_dates_na_records() -> None:
    kinds = kind_registry()["kinds"]
    assert set(kinds) == set(typing.get_args(EntryKind))
    for name, entry in kinds.items():
        assert entry["signer"] in ("na", "registered_key", "key_succession"), name
        assert (entry["time_field"] is not None) == (entry["signer"] == "na"), name
        assert entry["id_field"], name


def test_committed_manifest_is_current() -> None:
    assert gm.main(["--repo", str(ROOT), "manifest", "--check"]) == 0


def test_every_suite_and_tier_is_in_the_manifest() -> None:
    manifest = json.loads((ROOT / "contract" / "MANIFEST.json").read_bytes())
    on_disk = {p.stem for p in (ROOT / "conformance" / "vectors").glob("*.json")}
    assert set(manifest["suites"]) == on_disk
    assert set(manifest["tiers"]) == {"verifier", "governed", "edge", "gateway"}
    assert manifest["suites"]["grants"]["na_only_kinds"] == ["issuance"]
    assert "issuance" not in manifest["suites"]["grants"]["required"]["governed"]
    # Strict parsing is part of the contract: refusing an unknown signed field is required everywhere.
    for tier in ("verifier", "governed"):
        assert "unknown_fields" in manifest["suites"]["field_registry"]["required"][tier]
    assert manifest["contract_digest"] == "sha256:" + gm.contract_digest(manifest)


def test_archive_is_reproducible_and_holds_exactly_the_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    assert gm.main(["--repo", str(ROOT), "archive", "--out", str(tmp_path / "a")]) == 0
    assert gm.main(["--repo", str(ROOT), "archive", "--out", str(tmp_path / "b")]) == 0
    manifest = json.loads((ROOT / "contract" / "MANIFEST.json").read_bytes())
    name = f"genesis-mesh-contract-{manifest['bundle_version']}.tar"
    first = (tmp_path / "a" / name).read_bytes()
    assert first == (tmp_path / "b" / name).read_bytes()
    assert (tmp_path / "a" / "SHA256SUMS-contract").read_text() == f"{gm.sha256_bytes(first)}  {name}\n"
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as tar:
        members = tar.getmembers()
        top = name.removesuffix(".tar") + "/"
        assert sorted(m.name for m in members) == sorted(top + p for p in [*manifest["files"], gm.MANIFEST_PATH])
        assert {(m.mtime, m.uid, m.gid, m.uname, m.mode) for m in members} == {(1700000000, 0, 0, "", 0o644)}
        for member in members:
            rel = member.name.removeprefix(top)
            data = tar.extractfile(member).read()  # type: ignore[union-attr]
            if rel != gm.MANIFEST_PATH:
                assert gm.sha256_bytes(data) == manifest["files"][rel]["sha256"], rel


# ── negative paths on a synthetic core ────────────────────────────────────────


def _suite(name: str, kinds: list[str | None], **extra: typing.Any) -> dict[str, typing.Any]:
    vectors = [{"name": f"v{i}", **({"kind": k} if k else {})} for i, k in enumerate(kinds)]
    return {"suite": name, "version": "1.0.0", **extra, "vectors": vectors}


@pytest.fixture
def core(tmp_path: Path) -> Path:
    """A minimal core checkout: two suites, a fixture, the contract files and the tool."""
    (tmp_path / "genesis_mesh").mkdir()
    (tmp_path / "VERSION").write_text("1.11.0\n")
    vectors = tmp_path / "conformance" / "vectors"
    vectors.mkdir(parents=True)
    (vectors / "alpha.json").write_text(json.dumps(_suite("alpha", ["x", "y", "na"], na_only_kinds=["na"])))
    (vectors / "beta.json").write_text(json.dumps(_suite("beta", [None, None])))
    pack = tmp_path / "conformance" / "fixtures" / "pack-1" / "trust"
    pack.mkdir(parents=True)
    (pack / "a.json").write_bytes(b"{}\r\n")
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "kinds.json").write_text("{}\n")
    (tmp_path / "contract" / "public-surface.json").write_text("{}\n")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "gm_contract.py", tmp_path / "scripts" / "gm_contract.py")
    _write_spec(tmp_path, {
        "alpha": {"na_only_kinds": ["na"], "required": {"verifier": ["x"], "governed": "all"}},
        "beta": {"required": {}},
    })
    return tmp_path


def _write_spec(root: Path, suites: dict[str, typing.Any], **overrides: typing.Any) -> None:
    spec = {
        "schema": "gm.contract.spec/1",
        "include": ["conformance/vectors/*.json", "conformance/fixtures/pack-1/**", "contract/public-surface.json",
                    "contract/kinds.json", "scripts/gm_contract.py"],
        "tiers": {"verifier": "v", "governed": "g"},
        "suites": suites,
        **overrides,
    }
    (root / "contract" / "bundle.json").write_text(json.dumps(spec))


def _fails(root: Path, message: str) -> None:
    with pytest.raises(gm.ContractError, match=message):
        gm.build_manifest(root)


def test_synthetic_manifest_expands_all_and_counts_unkinded_vectors(core: Path) -> None:
    manifest = gm.build_manifest(core)
    assert manifest["suites"]["alpha"]["required"] == {"governed": ["x", "y"], "verifier": ["x"]}
    assert manifest["suites"]["beta"]["kinds"] == {"*": 2}
    assert manifest["fixtures"] == {"pack-1": {"dir": "conformance/fixtures/pack-1/"}}
    # The fixture's CRLF bytes are hashed as they are: the bundle is byte-exact.
    assert manifest["files"]["conformance/fixtures/pack-1/trust/a.json"]["bytes"] == 4


def test_a_new_kind_in_an_all_suite_becomes_required(core: Path) -> None:
    (core / "conformance/vectors/alpha.json").write_text(
        json.dumps(_suite("alpha", ["x", "y", "z", "na"], na_only_kinds=["na"])))
    assert gm.build_manifest(core)["suites"]["alpha"]["required"]["governed"] == ["x", "y", "z"]


def test_rejects_a_suite_without_a_tier_decision(core: Path) -> None:
    (core / "conformance/vectors/gamma.json").write_text(json.dumps(_suite("gamma", ["k"])))
    _fails(core, "suites without a tier entry: \\['gamma'\\]")


def test_rejects_a_spec_entry_without_its_suite(core: Path) -> None:
    (core / "conformance/vectors/beta.json").unlink()
    _fails(core, "not in the bundle: \\['beta'\\]")


def test_rejects_a_required_kind_the_suite_does_not_have(core: Path) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {"verifier": ["x", "gone"]}},
                       "beta": {"required": {}}})
    _fails(core, "requires kinds the suite does not have: \\['gone'\\]")


def test_rejects_an_unknown_tier(core: Path) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {"edge": "all"}}, "beta": {"required": {}}})
    _fails(core, "unknown tier 'edge'")


def test_rejects_requiring_an_na_only_kind(core: Path) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {"verifier": ["na"]}},
                       "beta": {"required": {}}})
    _fails(core, "requires an NA-only kind")


def test_rejects_na_only_kinds_that_differ_from_the_suite_file(core: Path) -> None:
    _write_spec(core, {"alpha": {"required": {"verifier": ["x"]}}, "beta": {"required": {}}})
    _fails(core, "na_only_kinds \\['na'\\] differ")


def test_spec_may_mark_na_only_kinds_a_suite_file_does_not_declare(core: Path) -> None:
    (core / "conformance/vectors/alpha.json").write_text(json.dumps(_suite("alpha", ["x", "y", "na"])))
    assert gm.build_manifest(core)["suites"]["alpha"]["required"]["governed"] == ["x", "y"]


def test_rejects_a_suite_file_naming_another_suite(core: Path) -> None:
    (core / "conformance/vectors/beta.json").write_text(json.dumps(_suite("other", [None])))
    _fails(core, "names suite 'other'")


def test_rejects_an_include_pattern_that_matches_nothing(core: Path) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {}}, "beta": {"required": {}}},
                include=["conformance/vectors/*.json", "contract/missing.json", "contract/kinds.json",
                         "contract/public-surface.json", "scripts/gm_contract.py"])
    _fails(core, "'contract/missing.json' matches no file")


def test_check_fails_on_a_stale_manifest_and_passes_after_regenerating(core: Path) -> None:
    assert gm.main(["--repo", str(core), "manifest", "--check"]) == 1
    assert gm.main(["--repo", str(core), "manifest"]) == 0
    assert gm.main(["--repo", str(core), "manifest", "--check"]) == 0
    (core / "conformance/fixtures/pack-1/trust/a.json").write_bytes(b"{}\n")
    assert gm.main(["--repo", str(core), "manifest", "--check"]) == 1


def test_check_fails_when_the_tool_imports_outside_the_standard_library(core: Path) -> None:
    tool = core / "scripts" / "gm_contract.py"
    tool.write_text(tool.read_text(encoding="utf-8") + "\nimport nacl.signing\n", encoding="utf-8")
    assert gm.check_stdlib_only(tool.read_text(encoding="utf-8")) == ["nacl.signing"]
    assert gm.main(["--repo", str(core), "manifest", "--check"]) == 1


def test_contract_digest_ignores_the_version_and_the_tool_but_not_the_vectors(core: Path) -> None:
    before = gm.build_manifest(core)["contract_digest"]
    (core / "VERSION").write_text("1.11.1\n")
    tool = core / "scripts" / "gm_contract.py"
    tool.write_text(tool.read_text(encoding="utf-8") + "\n# a tool fix\n", encoding="utf-8")
    after = gm.build_manifest(core)
    assert after["contract_digest"] == before
    assert after["bundle_version"] == "1.11.1"
    (core / "conformance/vectors/beta.json").write_text(json.dumps(_suite("beta", [None, None, None])))
    assert gm.build_manifest(core)["contract_digest"] != before


def test_archive_refuses_a_stale_manifest(core: Path, tmp_path: Path) -> None:
    assert gm.main(["--repo", str(core), "manifest"]) == 0
    (core / "conformance/vectors/beta.json").write_text(json.dumps(_suite("beta", [None])))
    with pytest.raises(gm.ContractError, match="stale"):
        gm.archive_bytes(core, 0)


def test_core_commands_refuse_a_checkout_that_is_not_the_core(tmp_path: Path) -> None:
    assert gm.main(["--repo", str(tmp_path), "manifest", "--check"]) == 1


def test_rejects_unknown_keys_in_the_spec_and_its_suite_entries(core: Path) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {}}, "beta": {"required": {}}}, extra=1)
    _fails(core, re.escape("unknown keys ['extra']"))
    # A misspelt na_only_kinds would silently make the NA-only kinds required.
    _write_spec(core, {"alpha": {"na_only_kind": ["na"], "required": {}}, "beta": {"required": {}}})
    _fails(core, re.escape("suite 'alpha' has unknown keys ['na_only_kind']"))


def test_rejects_a_spec_with_a_repeated_key(core: Path) -> None:
    spec = (core / "contract" / "bundle.json").read_text()
    (core / "contract" / "bundle.json").write_text(spec.replace('"suites": {', '"suites": {"beta": {"required": {}}, ', 1))
    _fails(core, "duplicate key 'beta'")


@pytest.mark.parametrize("pattern", ["", "/etc/*.json", "../x/*.json", "conformance/**/a.json", "a\\b.json", 3])
def test_rejects_an_include_pattern_that_is_not_a_relative_path(core: Path, pattern: typing.Any) -> None:
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {}}, "beta": {"required": {}}},
                include=[pattern, "contract/kinds.json", "contract/public-surface.json", "scripts/gm_contract.py"])
    _fails(core, "is not a relative path pattern")


def test_ignored_files_never_enter_the_bundle(core: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    subprocess.run(["git", "init", "-q", str(core)], check=True)
    (core / ".gitignore").write_text("*.bak\n")
    (core / "conformance" / "fixtures" / "pack-1" / "trust" / "a.json.bak").write_text("scratch")
    files = gm.build_manifest(core)["files"]
    assert "conformance/fixtures/pack-1/trust/a.json" in files
    assert not [name for name in files if name.endswith(".bak")]


def test_rewording_a_tier_keeps_the_contract_digest(core: Path) -> None:
    before = gm.build_manifest(core)["contract_digest"]
    _write_spec(core, {"alpha": {"na_only_kinds": ["na"], "required": {"verifier": ["x"], "governed": "all"}},
                       "beta": {"required": {}}}, tiers={"verifier": "reworded", "governed": "g"})
    assert gm.build_manifest(core)["contract_digest"] == before


def test_the_release_version_bump_keeps_the_manifest_current(core: Path) -> None:
    """``check_version.py --set`` rewrites the version labels in place; no regeneration needed."""
    check_version = _load("check_version")
    assert gm.main(["--repo", str(core), "manifest"]) == 0
    # The manifest and the package's copy of its version (/health contract_bundle).
    for rel, expected in (("contract/MANIFEST.json", 2), (gm.DIGEST_MODULE_PATH, 1)):
        (pattern,) = [p for name, p, _ in check_version.SITES if name == rel]
        path = core / rel
        text = path.read_text(encoding="utf-8")
        bumped, count = re.subn(pattern, lambda m: m.group(0).replace(m.group(1), "1.12.0"), text)
        assert count == expected, rel
        path.write_bytes(bumped.encode("utf-8"))
    (core / "VERSION").write_text("1.12.0\n")
    assert gm.main(["--repo", str(core), "manifest", "--check"]) == 0
    assert 'BUNDLE_VERSION = "1.12.0"' in (core / gm.DIGEST_MODULE_PATH).read_text(encoding="ascii")
