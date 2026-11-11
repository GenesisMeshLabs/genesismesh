"""v1.11.0: the SDK releases the core's CI runs against (``scripts/consumer_pins.py``).

The Interoperability run checks out each SDK at the ref ``contract/consumer-pins.json``
pins, never at a branch picked by name. These tests stub GitHub; no network access.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("consumer_pins", REPO_ROOT / "scripts" / "consumer_pins.py")
assert _spec and _spec.loader
pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins)

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "consumer-pins.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _valid(**refs: str) -> dict[str, object]:
    data: dict[str, object] = {"schema": pins.SCHEMA}
    for name in pins.CONSUMERS:
        data[name] = {"ref": refs.get(name.replace("-", "_"), "v1.10.1")}
    return data


def test_the_committed_pins_are_well_formed_release_tags_or_commits() -> None:
    refs = pins.load()
    assert set(refs) == set(pins.CONSUMERS) == {"sdk-go", "sdk-typescript", "sdk-dotnet"}
    assert all(pins.TAG.fullmatch(r) or pins.COMMIT.fullmatch(r) for r in refs.values())


def test_a_tag_or_a_full_commit_is_accepted(tmp_path: Path) -> None:
    refs = pins.load(_write(tmp_path, _valid(sdk_go=COMMIT)))
    assert refs == {"sdk-dotnet": "v1.10.1", "sdk-go": COMMIT, "sdk-typescript": "v1.10.1"}


@pytest.mark.parametrize("ref", ["main", "feat/x", "1.10.1", "v1.10", "v1.10.1-rc1", COMMIT[:12], COMMIT.upper(), ""])
def test_a_branch_a_short_commit_or_a_loose_version_is_refused(tmp_path: Path, ref: str) -> None:
    with pytest.raises(pins.PinError, match="neither a release tag"):
        pins.load(_write(tmp_path, _valid(sdk_typescript=ref)))


@pytest.mark.parametrize("change", [
    lambda d: d.pop("sdk-go"),
    lambda d: d.update({"sdk-rust": {"ref": "v1.10.1"}}),
    lambda d: d.update({"schema": "gm.consumer-pins/2"}),
    lambda d: d.update({"sdk-go": {"ref": "v1.10.1", "note": "x"}}),
    lambda d: d.update({"sdk-go": "v1.10.1"}),
    lambda d: d.update({"sdk-go": {"ref": 1}}),
])
def test_a_missing_extra_or_malformed_entry_is_refused(tmp_path: Path, change) -> None:
    data = _valid()
    change(data)
    with pytest.raises(pins.PinError):
        pins.load(_write(tmp_path, data))


def test_a_duplicate_key_or_bad_json_is_refused(tmp_path: Path) -> None:
    text = json.dumps(_valid())[:-1] + ', "sdk-go": {"ref": "main"}}'
    with pytest.raises(pins.PinError, match="duplicate key"):
        pins.load(_write(tmp_path, text))
    with pytest.raises(pins.PinError):
        pins.load(_write(tmp_path, "{"))


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.github.com/x", code, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def test_a_tag_must_exist() -> None:
    asked = []

    def github(path: str) -> object:
        asked.append(path)
        return {"ref": "refs/tags/v1.10.1"}

    pins.verify("sdk-go", "v1.10.1", github=github)
    assert asked == ["/repos/GenesisMeshLabs/sdk-go/git/ref/tags/v1.10.1"]

    def missing(path: str) -> object:
        raise _http_error(404)

    with pytest.raises(pins.PinError, match="not found on GitHub"):
        pins.verify("sdk-go", "v9.9.9", github=missing)


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_a_commit_on_main_is_accepted(status: str) -> None:
    asked = []

    def github(path: str) -> object:
        asked.append(path)
        return {"status": status}

    pins.verify("sdk-dotnet", COMMIT, github=github)
    assert asked == [f"/repos/GenesisMeshLabs/sdk-dotnet/compare/{COMMIT}...main"]


@pytest.mark.parametrize("status", ["behind", "diverged", None])
def test_a_commit_off_main_is_refused(status: str | None) -> None:
    # "diverged": a branch commit not merged to main; "behind": main is older than it.
    with pytest.raises(pins.PinError, match="is not on main"):
        pins.verify("sdk-dotnet", COMMIT, github=lambda path: {"status": status})


def test_github_unreachable_fails_instead_of_passing() -> None:
    def down(path: str) -> object:
        raise urllib.error.URLError("no route")

    with pytest.raises(pins.PinError, match="could not check"):
        pins.verify("sdk-go", COMMIT, github=down)


def test_env_prints_one_variable_per_consumer(capsys: pytest.CaptureFixture[str]) -> None:
    assert pins.main(["env"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert sorted(line.split("=")[0] for line in lines) == sorted(pins.CONSUMERS.values())


def test_a_bad_pin_fails_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(pins, "PINS", _write(tmp_path, _valid(sdk_go="main")))
    assert pins.main(["env"]) == 1
    assert "neither a release tag" in capsys.readouterr().err


def _job(name: str) -> str:
    text = (REPO_ROOT / ".github" / "workflows" / "interop.yml").read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text)
    assert match
    return match.group(1)


def test_interoperability_checks_out_each_sdk_at_its_pin_and_no_branch_by_name() -> None:
    job = _job("interop")
    # The pins are read (and checked on GitHub) before any SDK checkout; a failure fails the step.
    read = job.index("python3 scripts/consumer_pins.py env --verify")
    assert "set -euo pipefail" in job[job.rindex("run: |", 0, read):read]
    for name, variable in pins.CONSUMERS.items():
        checkout = job.index(f"repository: GenesisMeshLabs/{name}\n")
        assert read < checkout
        assert job[checkout:].split("\n")[1].strip() == f"ref: ${{{{ env.{variable} }}}}"
    # No ref chosen from the branch or the run: only the committed pins.
    for gone in ("head_ref", "ref_name", "ls-remote", "env.SDK_REF ", "sdk-rust"):
        assert gone not in job
    assert job.count("repository: GenesisMeshLabs/") == len(pins.CONSUMERS)
