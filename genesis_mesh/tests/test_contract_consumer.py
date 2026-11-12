"""Tests for the consumer commands of scripts/gm_contract.py (sync, verify, receipts, conformance).

A consumer here is a temporary checkout with its own contract-bundle/consumer.json. The bundle
comes from this core checkout: as a path, or as a commit whose files a stub serves from it, so
nothing goes to the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gm_contract_consumer", REPO_ROOT / "scripts" / "gm_contract.py")
assert _spec and _spec.loader
gm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gm)

COMMIT = "a" * 40
MANIFEST = json.loads((REPO_ROOT / "contract" / "MANIFEST.json").read_bytes())
NODE_KINDS: dict[str, int] = MANIFEST["suites"]["node"]["kinds"]
PACK = "conformance/fixtures/audit-pack-1.5.0/"


def _consumer(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": "gm.contract.consumer/1",
        "component": "demo",
        "tiers": ["edge"],
        "tool_path": "scripts/gm_contract.py",
        "files": {"conformance/vectors/node.json": "tests/fixtures/node.json", PACK: "tests/fixtures/pack/"},
        "conformance": [[sys.executable, "write_receipts.py"]],
    }
    data.update(overrides)
    return data


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    consumer = tmp_path / "consumer"
    (consumer / "contract-bundle").mkdir(parents=True)
    (consumer / "contract-bundle" / "consumer.json").write_text(json.dumps(_consumer()), encoding="utf-8")
    monkeypatch.setenv("GM_CONTRACT_CACHE", str(tmp_path / "cache"))
    return consumer


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Serve raw.githubusercontent.com from this checkout at COMMIT, and the compare API."""
    state: dict[str, Any] = {"status": "ahead", "urls": [], "override": {}}

    def fetch(url: str) -> bytes:
        state["urls"].append(url)
        raw = f"https://raw.githubusercontent.com/GenesisMeshLabs/genesismesh/{COMMIT}/"
        if url.startswith(raw):
            rel = url[len(raw):]
            if rel in state["override"]:
                return state["override"][rel]
            return (REPO_ROOT / rel).read_bytes()
        if url == f"https://api.github.com/repos/GenesisMeshLabs/genesismesh/compare/{COMMIT}...main":
            return json.dumps({"status": state["status"]}).encode()
        raise gm.ContractError(f"cannot fetch {url} (unknown in this test)")

    monkeypatch.setattr(gm, "fetch_url", fetch)
    return state


def _write(repo: Path, rel: str, data: Any) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(repo: Path, *args: str) -> int:
    return gm.main(["--repo", str(repo), *args])


def _receipt(run: dict[str, Any], not_run: dict[str, int] | None = None, suite: str = "node",
             file: str = "tests/fixtures/node.json") -> dict[str, Any]:
    return {"schema": "gm.contract.receipt/1", "suite": suite, "file": file, "runner": "test",
            "run": run, "not_run": not_run or {}}


# sync ------------------------------------------------------------------------------------------

def test_sync_from_a_commit_copies_pins_and_vendors_the_tool(repo: Path, github: dict, capsys) -> None:
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    lock = json.loads((repo / "contract-bundle/bundle.lock").read_bytes())
    assert lock["source"] == "commit" and lock["core_commit"] == COMMIT
    assert lock["core_tag"] is None and lock["archive"] is None
    assert lock["bundle_version"] == MANIFEST["bundle_version"]
    assert lock["contract_digest"] == MANIFEST["contract_digest"]
    assert lock["files"]["tests/fixtures/node.json"]["from"] == "conformance/vectors/node.json"
    pack = [d for d in lock["files"] if d.startswith("tests/fixtures/pack/")]
    assert len(pack) == len([f for f in MANIFEST["files"] if f.startswith(PACK)])
    assert (repo / "tests/fixtures/node.json").read_bytes() == (REPO_ROOT / "conformance/vectors/node.json").read_bytes()
    assert (repo / "scripts/gm_contract.py").read_bytes() == (REPO_ROOT / "scripts/gm_contract.py").read_bytes()
    assert (repo / "contract-bundle/MANIFEST.json").read_bytes() == (REPO_ROOT / "contract/MANIFEST.json").read_bytes()
    assert f"+g{COMMIT[:12]}" in capsys.readouterr().out
    assert _run(repo, "verify") == 0
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    assert "nothing changed" in capsys.readouterr().out


def test_sync_from_a_core_checkout_pins_a_path_that_verify_refuses(repo: Path, capsys) -> None:
    assert _run(repo, "sync", "--core-path", str(REPO_ROOT)) == 0
    lock = json.loads((repo / "contract-bundle/bundle.lock").read_bytes())
    assert lock["source"] == "path"
    assert _run(repo, "verify") == 1
    assert "source 'path'" in capsys.readouterr().err


def test_sync_without_the_lock_leaves_the_pin_and_the_tool(repo: Path, github: dict) -> None:
    assert _run(repo, "sync", "--core-ref", COMMIT, "--no-lock") == 0
    assert (repo / "tests/fixtures/node.json").is_file() and (repo / "contract-bundle/MANIFEST.json").is_file()
    assert not (repo / "contract-bundle/bundle.lock").exists()
    assert not (repo / "scripts/gm_contract.py").exists()


def test_sync_removes_only_copies_the_previous_pin_made(repo: Path, github: dict, capsys) -> None:
    files = {"conformance/vectors/node.json": "tests/fixtures/node.json",
             "conformance/vectors/treaties.json": "tests/fixtures/treaties.json", PACK: "tests/fixtures/pack/"}
    _write(repo, "contract-bundle/consumer.json", _consumer(files=files))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    _write(repo, "tests/fixtures/pack/own.json", {})
    files.pop("conformance/vectors/treaties.json")
    _write(repo, "contract-bundle/consumer.json", _consumer(files=files))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    assert "tests/fixtures/treaties.json (removed)" in capsys.readouterr().out
    assert not (repo / "tests/fixtures/treaties.json").exists()
    # A file sync never wrote stays; verify names it instead.
    assert (repo / "tests/fixtures/pack/own.json").is_file()
    assert _run(repo, "verify") == 1
    assert "own.json is not in the pinned bundle" in capsys.readouterr().err


@pytest.mark.parametrize("dest, tool", [("scripts/", "scripts/gm_contract.py"),
                                        ("contract-bundle/", "scripts/gm_contract.py"),
                                        ("tools/", "tools/gm_contract.py")])
def test_a_directory_copy_may_not_hold_the_tool_or_the_pin(repo: Path, github: dict, dest: str, tool: str,
                                                           capsys) -> None:
    files = {"conformance/vectors/node.json": "n.json", PACK: dest}
    _write(repo, "contract-bundle/consumer.json", _consumer(files=files, tool_path=tool))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "would hold the tool" in capsys.readouterr().err


def test_sync_runs_the_regenerate_commands_and_fails_with_them(repo: Path, github: dict) -> None:
    marker = "import pathlib; pathlib.Path('regenerated').write_text('ok')"
    _write(repo, "contract-bundle/consumer.json", _consumer(regenerate=[[sys.executable, "-c", marker]]))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    assert (repo / "regenerated").read_text() == "ok"
    _write(repo, "contract-bundle/consumer.json", _consumer(regenerate=[[sys.executable, "-c", "raise SystemExit(3)"]]))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1


def test_sync_refuses_a_file_that_does_not_match_the_manifest(repo: Path, github: dict, capsys) -> None:
    github["override"]["conformance/vectors/node.json"] = b'{"tampered": true}'
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "does not match the bundle manifest" in capsys.readouterr().err
    assert not (repo / "tests/fixtures/node.json").exists()


def test_sync_refuses_a_manifest_whose_digest_does_not_match_its_content(repo: Path, github: dict, capsys) -> None:
    edited = dict(MANIFEST, suites={**MANIFEST["suites"], "node": {**MANIFEST["suites"]["node"], "vectors": 99}})
    github["override"]["contract/MANIFEST.json"] = gm.render(edited)
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "contract_digest does not match" in capsys.readouterr().err


def test_sync_offline_uses_only_the_cache(repo: Path, github: dict, capsys) -> None:
    assert _run(repo, "sync", "--core-ref", COMMIT, "--offline") == 1
    assert "not in the cache" in capsys.readouterr().err
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    github["urls"].clear()
    assert _run(repo, "sync", "--core-ref", COMMIT, "--offline") == 0
    assert github["urls"] == []


@pytest.mark.parametrize("ref", ["main", "a" * 39, "A" * 40, "v1.10.1"])
def test_sync_needs_a_full_commit_hash(repo: Path, ref: str, capsys) -> None:
    assert _run(repo, "sync", "--core-ref", ref) == 2
    assert "40-character commit" in capsys.readouterr().err


def test_sync_pins_only_a_commit_on_core_main_and_checks_before_writing(repo: Path, github: dict, capsys) -> None:
    github["status"] = "diverged"
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "not on core main" in capsys.readouterr().err
    assert not (repo / "tests").exists() and not (repo / "contract-bundle/bundle.lock").exists()
    # A canary (--no-lock) may test any commit; it pins nothing.
    assert _run(repo, "sync", "--core-ref", COMMIT, "--no-lock") == 0


def _hostile(github: dict, extra: str) -> None:
    """A manifest that agrees with itself and lists ``extra`` under the audit pack."""
    data = (REPO_ROOT / "conformance/vectors/node.json").read_bytes()
    edited = json.loads(json.dumps(MANIFEST))
    edited["files"][extra] = {"bytes": len(data), "sha256": gm.sha256_bytes(data)}
    edited["contract_digest"] = "sha256:" + gm.contract_digest(edited)
    github["override"]["contract/MANIFEST.json"] = gm.render(edited)
    github["override"][extra] = data


@pytest.mark.parametrize("extra", [PACK + "../../../../escaped.json", PACK + "a\\..\\x.json",
                                   PACK + "C:/x.json", PACK + "./x.json", PACK + "a//x.json"])
def test_sync_refuses_a_manifest_with_an_unsafe_path(repo: Path, github: dict, extra: str, capsys) -> None:
    _hostile(github, extra)
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "unsafe path" in capsys.readouterr().err
    assert not (repo.parent / "escaped.json").exists() and not (repo / "tests").exists()


def test_sync_from_a_core_checkout_checks_its_manifest_paths_too(repo: Path, tmp_path: Path, capsys,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    edited = json.loads(json.dumps(MANIFEST))
    edited["files"][PACK + "../../x.json"] = {"bytes": 1, "sha256": "0" * 64}
    edited["contract_digest"] = "sha256:" + gm.contract_digest(edited)
    monkeypatch.setattr(gm.PathSource, "manifest_bytes", lambda self: gm.render(edited))
    assert _run(repo, "sync", "--core-path", str(REPO_ROOT)) == 1
    assert "unsafe path" in capsys.readouterr().err


def test_a_corrupt_cache_object_is_fetched_again(repo: Path, github: dict, tmp_path: Path) -> None:
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    node_sha = MANIFEST["files"]["conformance/vectors/node.json"]["sha256"]
    cached = tmp_path / "cache" / "objects" / node_sha
    cached.write_bytes(b"corrupt")
    assert _run(repo, "sync", "--core-ref", COMMIT, "--offline") == 1
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    assert gm.sha256_bytes(cached.read_bytes()) == node_sha


def test_an_online_sync_does_not_trust_a_cached_manifest(repo: Path, github: dict, tmp_path: Path) -> None:
    planted = tmp_path / "cache" / "commits" / COMMIT / "MANIFEST.json"
    planted.parent.mkdir(parents=True)
    planted.write_bytes(b"{}")
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    assert planted.read_bytes() == (REPO_ROOT / "contract/MANIFEST.json").read_bytes()


def test_a_failed_regenerate_leaves_no_lock(repo: Path, github: dict) -> None:
    _write(repo, "contract-bundle/consumer.json", _consumer(regenerate=[[sys.executable, "-c", "raise SystemExit(3)"]]))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert not (repo / "contract-bundle/bundle.lock").exists()


def test_sync_refuses_tiers_whose_suites_are_not_copied(repo: Path, github: dict, capsys) -> None:
    _write(repo, "contract-bundle/consumer.json", _consumer(tiers=["edge", "verifier"]))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "are not copied" in capsys.readouterr().err
    _write(repo, "contract-bundle/consumer.json", _consumer(tiers=["edge", "no-such-tier"]))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert "not in bundle" in capsys.readouterr().err


@pytest.mark.parametrize("files, message", [
    ({"conformance/vectors/node.json": "../node.json"}, "not a relative path"),
    ({"conformance/vectors/node.json": "/abs/node.json"}, "not a relative path"),
    ({"conformance/vectors/node.json": "C:/node.json"}, "not a relative path"),
    ({"conformance/vectors/node.json": "tests\\node.json"}, "not a relative path"),
    ({"conformance/vectors/node.json": "tests/"}, "must be a relative file path"),
    ({PACK: "tests/pack"}, "directory ending in /"),
    ({"conformance/vectors/node.json": "a.json", "conformance/vectors/audit.json": "a.json"}, "two bundle files"),
    ({"conformance/vectors/node.json": "contract-bundle/bundle.lock"}, "reserved"),
    ({"conformance/vectors/node.json": "scripts/gm_contract.py"}, "reserved"),
    ({"conformance/vectors/node.json": "n.json", "scripts/gm_contract.py": "tool.py"}, "copied to tool_path"),
    ({"conformance/vectors/node.json": "n.json", "conformance/vectors/nope.json": "x.json"}, "names no file"),
])
def test_sync_refuses_a_bad_mapping(repo: Path, github: dict, files: dict, message: str, capsys) -> None:
    _write(repo, "contract-bundle/consumer.json", _consumer(files=files))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("change, message", [
    ({"schema": "gm.contract.consumer/2"}, "schema must be"),
    ({"extra": 1}, "unknown keys ['extra']"),
    ({"tiers": []}, "'tiers' a non-empty list"),
    ({"tiers": ["edge", "edge"]}, "without repeats"),
    ({"conformance": [[]]}, "non-empty list of strings"),
    ({"regenerate": "make"}, "'regenerate' must be a list"),
    ({"files": {}}, "'files' maps"),
])
def test_consumer_file_is_checked_for_shape(repo: Path, change: dict, message: str, capsys) -> None:
    _write(repo, "contract-bundle/consumer.json", _consumer(**change))
    assert _run(repo, "verify") == 1
    assert message in capsys.readouterr().err


def test_consumer_commands_need_a_consumer_file(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, "verify") == 1
    assert "has no contract-bundle/consumer.json" in capsys.readouterr().err


def test_usage_errors_exit_2(repo: Path) -> None:
    assert _run(repo, "sync") == 2
    assert _run(repo, "sync", "--core-ref", COMMIT, "--core-path", ".") == 2
    assert _run(repo, "sync", "--core-path", str(REPO_ROOT), "--offline") == 2


# verify ----------------------------------------------------------------------------------------

@pytest.fixture
def synced(repo: Path, github: dict) -> Path:
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    return repo


@pytest.mark.parametrize("damage, message", [
    (lambda r: (r / "tests/fixtures/node.json").write_bytes(b"{}"), "differs from conformance/vectors/node.json"),
    (lambda r: (r / "tests/fixtures/node.json").write_bytes(
        (r / "tests/fixtures/node.json").read_bytes().replace(b"\n", b"\r\n")), "line endings"),
    (lambda r: (r / "tests/fixtures/node.json").unlink(), "tests/fixtures/node.json is missing"),
    (lambda r: (r / "tests/fixtures/pack/extra.txt").write_text("x"), "extra.txt is not in the pinned bundle"),
    (lambda r: (r / "scripts/gm_contract.py").write_text("# edited\n"), "not the tool of the pinned bundle"),
    (lambda r: (r / "contract-bundle/MANIFEST.json").write_bytes(
        (r / "contract-bundle/MANIFEST.json").read_bytes() + b"\n"), "is not the manifest"),
])
def test_verify_names_every_drift_from_the_pin(synced: Path, damage, message: str, capsys) -> None:
    damage(synced)
    assert _run(synced, "verify") == 1
    assert message in capsys.readouterr().err


def test_verify_refuses_a_lock_edited_by_hand(synced: Path, capsys) -> None:
    lock = json.loads((synced / "contract-bundle/bundle.lock").read_bytes())
    lock["files"].pop("tests/fixtures/node.json")
    (synced / "contract-bundle/bundle.lock").write_bytes(gm.render(lock))
    assert _run(synced, "verify") == 1
    assert "files differ" in capsys.readouterr().err
    lock["extra"] = True
    (synced / "contract-bundle/bundle.lock").write_bytes(gm.render(lock))
    assert _run(synced, "verify") == 1
    assert "exactly the keys" in capsys.readouterr().err


def test_verify_refuses_a_mapping_changed_since_the_sync(synced: Path, capsys) -> None:
    _write(synced, "contract-bundle/consumer.json",
           _consumer(files={"conformance/vectors/node.json": "tests/fixtures/node.json"}))
    assert _run(synced, "verify") == 1
    assert "files differ" in capsys.readouterr().err


def test_verify_online_checks_the_commit_is_on_main_and_pins_its_manifest(synced: Path, github: dict, capsys) -> None:
    assert _run(synced, "verify", "--online") == 0
    assert "verified online" in capsys.readouterr().out
    github["status"] = "diverged"
    assert _run(synced, "verify", "--online") == 1
    assert "not on core main" in capsys.readouterr().err
    github["status"] = "identical"
    github["override"]["contract/MANIFEST.json"] = b"{}"
    assert _run(synced, "verify", "--online") == 1
    assert "is not the one" in capsys.readouterr().err


def test_a_commit_pin_carries_no_tag_or_archive(synced: Path, capsys) -> None:
    lock = json.loads((synced / "contract-bundle/bundle.lock").read_bytes())
    lock["core_tag"] = "v1.10.1"
    (synced / "contract-bundle/bundle.lock").write_bytes(gm.render(lock))
    assert _run(synced, "verify") == 1
    assert "no core_tag or archive" in capsys.readouterr().err


def test_core_ref_prints_the_pinned_commit(synced: Path, capsys) -> None:
    capsys.readouterr()
    assert _run(synced, "core-ref") == 0
    assert capsys.readouterr().out.strip() == COMMIT


def test_a_token_goes_only_to_the_github_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    seen: list[tuple[str, dict, dict]] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            return b"{}"

    def urlopen(request, timeout):
        seen.append((request.full_url, dict(request.header_items()), dict(request.headers)))
        return Response()

    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    gm.fetch_url("https://raw.githubusercontent.com/GenesisMeshLabs/genesismesh/x/contract/MANIFEST.json")
    gm.fetch_url("https://api.github.com/repos/GenesisMeshLabs/genesismesh/compare/x...main")
    assert "secret-token" not in json.dumps(seen[0][1])
    assert seen[1][1]["Authorization"] == "Bearer secret-token"
    # Not among the headers urllib copies onto a redirect to another host.
    assert "Authorization" not in seen[1][2]


# receipts --------------------------------------------------------------------------------------

def _receipts(tmp_path: Path, *receipts: dict[str, Any]) -> Path:
    out = tmp_path / "receipts"
    out.mkdir(exist_ok=True)
    for i, receipt in enumerate(receipts):
        (out / f"{receipt['suite']}.r{i}.json").write_text(json.dumps(receipt), encoding="utf-8")
    return out


def test_receipts_that_run_every_required_vector_pass(synced: Path, tmp_path: Path, capsys) -> None:
    out = _receipts(tmp_path, _receipt(dict(NODE_KINDS)))
    assert _run(synced, "receipt-check", "--receipts", str(out), "--json-out", str(tmp_path / "s.json")) == 0
    summary = json.loads((tmp_path / "s.json").read_bytes())
    assert summary["component"] == "demo" and summary["suites"]["node"]["run"] == NODE_KINDS


def test_a_suite_split_across_runners_counts_each_vector_once(synced: Path, tmp_path: Path) -> None:
    kinds = sorted(NODE_KINDS)
    first = {k: NODE_KINDS[k] for k in kinds[:2]}
    second = {k: NODE_KINDS[k] for k in kinds[2:]}
    assert _run(synced, "receipt-check", "--receipts", str(_receipts(tmp_path, _receipt(first), _receipt(second)))) == 0


@pytest.mark.parametrize("receipts, message", [
    ([], "no runner wrote a receipt"),
    ([_receipt({**NODE_KINDS, "crl": 0}, {"crl": NODE_KINDS["crl"]})], "kind crl: required, 0 of"),
    ([_receipt({k: n for k, n in NODE_KINDS.items() if k != "crl"})], "kind crl: 0 vectors accounted for"),
    ([_receipt(dict(NODE_KINDS)), _receipt(dict(NODE_KINDS))], "accounted for"),
    ([_receipt({**NODE_KINDS, "invented": 1})], "kind 'invented' is not in suite node"),
    ([_receipt(dict(NODE_KINDS), file="tests/elsewhere/node.json")], "is not where"),
    ([_receipt(dict(NODE_KINDS), suite="no_such_suite")], "is not in bundle"),
    ([{**_receipt(dict(NODE_KINDS)), "schema": "gm.contract.receipt/2"}], "not a gm.contract.receipt/1"),
    ([_receipt({"crl": -1})], "0 or more"),
    ([_receipt({"crl": 2.0})], "whole numbers"),
    ([{**_receipt(dict(NODE_KINDS)), "suite": ["node"]}], "must be strings"),
    ([{**_receipt(dict(NODE_KINDS)), "runner": 7}], "must be strings"),
])
def test_receipt_check_failures(synced: Path, tmp_path: Path, receipts: list, message: str, capsys) -> None:
    assert _run(synced, "receipt-check", "--receipts", str(_receipts(tmp_path, *receipts))) == 1
    assert message in capsys.readouterr().err


def test_an_absent_receipts_directory_is_named(synced: Path, tmp_path: Path, capsys) -> None:
    assert _run(synced, "receipt-check", "--receipts", str(tmp_path / "nowhere")) == 1
    assert "does not exist" in capsys.readouterr().err


def test_a_receipt_for_a_copy_that_drifted_fails(synced: Path, tmp_path: Path, capsys) -> None:
    (synced / "tests/fixtures/node.json").write_bytes(b"{}")
    assert _run(synced, "receipt-check", "--receipts", str(_receipts(tmp_path, _receipt(dict(NODE_KINDS))))) == 1
    assert "is not the bundle's conformance/vectors/node.json" in capsys.readouterr().err


def test_a_suite_no_tier_requires_is_still_checked_when_receipted(repo: Path, github: dict, tmp_path: Path, capsys) -> None:
    files = {"conformance/vectors/node.json": "tests/fixtures/node.json",
             "conformance/vectors/treaties.json": "tests/fixtures/treaties.json"}
    _write(repo, "contract-bundle/consumer.json", _consumer(files=files))
    assert _run(repo, "sync", "--core-ref", COMMIT) == 0
    short = _receipt({}, suite="treaties", file="tests/fixtures/treaties.json")
    assert _run(repo, "receipt-check", "--receipts", str(_receipts(tmp_path, _receipt(dict(NODE_KINDS)), short))) == 1
    assert "suite treaties kind" in capsys.readouterr().err


# conformance -----------------------------------------------------------------------------------

WRITER = """import json, os, sys
kinds = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {kinds}
receipt = {{"schema": "gm.contract.receipt/1", "suite": "node", "file": "tests/fixtures/node.json",
           "runner": "write_receipts.py", "run": kinds, "not_run": {{}}}}
with open(os.path.join(os.environ["GM_CONFORMANCE_RECEIPTS"], "node.writer.json"), "w") as f:
    json.dump(receipt, f)
"""


def test_conformance_runs_the_tests_with_receipts(synced: Path, tmp_path: Path, capsys) -> None:
    (synced / "write_receipts.py").write_text(WRITER.format(kinds=json.dumps(NODE_KINDS)), encoding="utf-8")
    assert _run(synced, "conformance", "--json-out", str(tmp_path / "c.json")) == 0
    assert json.loads((tmp_path / "c.json").read_bytes())["suites"]["node"]["runners"] == ["write_receipts.py"]
    assert "receipts match" in capsys.readouterr().out


def test_conformance_fails_when_a_test_command_fails(synced: Path, capsys) -> None:
    (synced / "write_receipts.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    assert _run(synced, "conformance") == 1
    assert "conformance command failed" in capsys.readouterr().err


def test_conformance_refuses_a_receipts_directory_with_old_receipts(synced: Path, tmp_path: Path, capsys) -> None:
    out = _receipts(tmp_path, _receipt(dict(NODE_KINDS)))
    assert _run(synced, "conformance", "--receipts", str(out)) == 1
    assert "already holds receipts" in capsys.readouterr().err


def test_conformance_checks_the_pin_unless_told_not_to(repo: Path, github: dict, capsys) -> None:
    (repo / "write_receipts.py").write_text(WRITER.format(kinds=json.dumps(NODE_KINDS)), encoding="utf-8")
    assert _run(repo, "sync", "--core-ref", COMMIT, "--no-lock") == 0
    assert _run(repo, "conformance") == 1
    assert "no contract-bundle/bundle.lock" in capsys.readouterr().err
    assert _run(repo, "conformance", "--no-lock-check") == 0


# the core ---------------------------------------------------------------------------------------

def test_the_tool_stays_standard_library_only() -> None:
    assert gm.check_stdlib_only((REPO_ROOT / "scripts" / "gm_contract.py").read_text(encoding="utf-8")) == []


def test_core_commands_still_refuse_a_consumer_checkout(synced: Path, capsys) -> None:
    assert _run(synced, "manifest", "--check") == 1
    assert "not a Genesis Mesh core checkout" in capsys.readouterr().err
