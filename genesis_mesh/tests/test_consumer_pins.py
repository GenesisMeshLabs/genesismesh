"""v1.11.0: the SDK revisions the core's CI runs against (``scripts/consumer_pins.py``).

The Interoperability run checks out each SDK at the commit its
``contract/consumer-pins.json`` pin resolves to, never at a branch picked by
name. These tests stub GitHub; no network access.
"""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("consumer_pins", REPO_ROOT / "scripts" / "consumer_pins.py")
assert _spec and _spec.loader
pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
TAG_SHA = "1111111111111111111111111111111111111111"
TAG_OBJECT = "2222222222222222222222222222222222222222"


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
    assert set(refs) == set(pins.CONSUMERS) == {"sdk-dotnet", "sdk-go", "sdk-rust", "sdk-typescript"}
    assert all(pins.TAG.fullmatch(r) or pins.COMMIT.fullmatch(r) for r in refs.values())


def test_a_tag_or_a_full_commit_is_accepted(tmp_path: Path) -> None:
    refs = pins.load(_write(tmp_path, _valid(sdk_go=COMMIT)))
    assert refs == {"sdk-dotnet": "v1.10.1", "sdk-go": COMMIT, "sdk-rust": "v1.10.1", "sdk-typescript": "v1.10.1"}


@pytest.mark.parametrize("ref", ["main", "feat/x", "1.10.1", "v1.10", "v1.10.1-rc1", COMMIT[:12], COMMIT.upper(), "",
                                 "v1.10.1\n", "v١.10.1"])
def test_a_branch_a_short_commit_or_a_loose_version_is_refused(tmp_path: Path, ref: str) -> None:
    with pytest.raises(pins.PinError, match="neither a release tag"):
        pins.load(_write(tmp_path, _valid(sdk_typescript=ref)))


@pytest.mark.parametrize("change", [
    lambda d: d.pop("sdk-go"),
    lambda d: d.pop("sdk-rust"),
    lambda d: d.update({"sdk-python": {"ref": "v1.10.1"}}),
    lambda d: d.update({"schema": "gm.consumer-pins/2"}),
    lambda d: d.update({"sdk-go": {"ref": "v1.10.1", "note": "x"}}),
    lambda d: d.update({"sdk-go": "v1.10.1"}),
    lambda d: d.update({"sdk-go": {"ref": 1}}),
])
def test_a_missing_extra_or_malformed_entry_is_refused(tmp_path: Path, change: Callable[[dict], object]) -> None:
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


def _github(answers: dict[str, object], asked: list[str]) -> Callable[[str], object]:
    def github(path: str) -> object:
        asked.append(path)
        return answers[path]

    return github


def _raising(error: BaseException) -> Callable[[str], object]:
    def github(path: str) -> object:
        raise error

    return github


def test_a_lightweight_tag_resolves_to_its_commit() -> None:
    asked: list[str] = []
    path = "/repos/GenesisMeshLabs/sdk-go/git/ref/tags/v1.10.1"
    github = _github({path: {"ref": "refs/tags/v1.10.1", "object": {"type": "commit", "sha": TAG_SHA}}}, asked)
    assert pins.resolve("sdk-go", "v1.10.1", github) == TAG_SHA
    assert asked == [path]


def test_an_annotated_tag_is_followed_to_its_commit() -> None:
    asked: list[str] = []
    repo = "/repos/GenesisMeshLabs/sdk-rust"
    github = _github({
        f"{repo}/git/ref/tags/v1.10.1": {"object": {"type": "tag", "sha": TAG_OBJECT}},
        f"{repo}/git/tags/{TAG_OBJECT}": {"object": {"type": "commit", "sha": TAG_SHA}},
    }, asked)
    assert pins.resolve("sdk-rust", "v1.10.1", github) == TAG_SHA
    assert asked == [f"{repo}/git/ref/tags/v1.10.1", f"{repo}/git/tags/{TAG_OBJECT}"]


@pytest.mark.parametrize("answer", [
    {},
    {"object": {"type": "commit"}},
    {"object": {"type": "commit", "sha": "main"}},
    {"object": {"type": "tree", "sha": TAG_SHA}},
    {"object": "x"},
])
def test_a_tag_that_names_no_commit_is_refused(answer: dict[str, object]) -> None:
    with pytest.raises(pins.PinError, match="does not name a commit"):
        pins.resolve("sdk-go", "v1.10.1", lambda path: answer)


def test_an_endless_chain_of_tag_objects_is_refused() -> None:
    asked: list[str] = []

    def github(path: str) -> object:
        asked.append(path)
        return {"object": {"type": "tag", "sha": TAG_OBJECT}}

    with pytest.raises(pins.PinError, match="does not name a commit"):
        pins.resolve("sdk-go", "v1.10.1", github)
    assert len(asked) == 1 + 3  # the ref, then three tag objects followed, then refused


def test_a_missing_tag_is_refused() -> None:
    with pytest.raises(pins.PinError, match="tag v9.9.9 not found on GitHub"):
        pins.resolve("sdk-go", "v9.9.9", _raising(_http_error(404)))


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_github_refusing_the_request_fails_with_its_status(code: int) -> None:
    with pytest.raises(pins.PinError, match=f"GitHub answered {code}"):
        pins.resolve("sdk-go", "v1.10.1", _raising(_http_error(code)))


@pytest.mark.parametrize("error", [
    urllib.error.URLError("no route"),
    http.client.RemoteDisconnected("closed"),
    TimeoutError("timed out"),
    ValueError("not JSON"),
])
def test_github_unreachable_or_garbled_fails_instead_of_passing(error: Exception) -> None:
    with pytest.raises(pins.PinError, match="could not check"):
        pins.resolve("sdk-go", COMMIT, _raising(error))


def test_an_answer_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(pins.PinError, match="unexpected answer"):
        pins.resolve("sdk-go", "v1.10.1", lambda path: [])


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_a_commit_on_main_resolves_to_itself(status: str) -> None:
    asked: list[str] = []
    path = f"/repos/GenesisMeshLabs/sdk-dotnet/compare/{COMMIT}...main?per_page=1"
    assert pins.resolve("sdk-dotnet", COMMIT, _github({path: {"status": status}}, asked)) == COMMIT
    assert asked == [path]


@pytest.mark.parametrize("status", ["behind", "diverged", None])
def test_a_commit_off_main_is_refused(status: str | None) -> None:
    # "diverged": a branch commit not merged to main; "behind": main is older than it.
    with pytest.raises(pins.PinError, match="is not on main"):
        pins.resolve("sdk-dotnet", COMMIT, lambda path: {"status": status})


def _resolving(asked: list[str]) -> Callable[[str], object]:
    """Each SDK's tag resolves to a commit derived from its position."""
    def github(path: str) -> object:
        asked.append(path)
        name = path.split("/")[3]
        return {"object": {"type": "commit", "sha": f"{sorted(pins.CONSUMERS).index(name) + 1:040x}"}}

    return github


def test_env_prints_each_pin_as_its_commit(capsys: pytest.CaptureFixture[str]) -> None:
    asked: list[str] = []
    assert pins.main(["env"], github=_resolving(asked)) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [f"{pins.CONSUMERS[name]}={i + 1:040x}" for i, name in enumerate(sorted(pins.CONSUMERS))]
    assert f"sdk-go: v1.10.1 is {2:040x}" in err
    assert len(asked) == len(pins.CONSUMERS)


def test_one_unresolvable_pin_prints_no_line_at_all(capsys: pytest.CaptureFixture[str]) -> None:
    # $GITHUB_ENV must not get a partial set of refs.
    def github(path: str) -> object:
        if "/sdk-rust/" in path:
            raise _http_error(404)
        return {"object": {"type": "commit", "sha": TAG_SHA}}

    assert pins.main(["env"], github=github) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "sdk-rust: tag v1.10.1 not found on GitHub" in err


def test_check_is_offline(capsys: pytest.CaptureFixture[str]) -> None:
    assert pins.main(["check"], github=_raising(AssertionError("check must not call GitHub"))) == 0
    assert "sdk-rust v1.10.1" in capsys.readouterr().out


def test_a_bad_pin_fails_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(pins, "PINS", _write(tmp_path, _valid(sdk_go="main")))
    assert pins.main(["env"], github=_resolving([])) == 1
    assert "neither a release tag" in capsys.readouterr().err


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.mark.parametrize("token", ["placeholder-token", None])
def test_the_token_goes_to_the_api_request_only_never_onto_a_redirect(
        monkeypatch: pytest.MonkeyPatch, token: str | None) -> None:
    sent: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        sent.append(request)
        return _Response(b'{"status": "identical"}')

    if token:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    else:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(pins.urllib.request, "urlopen", urlopen)
    assert pins.github_api("/repos/GenesisMeshLabs/sdk-go") == {"status": "identical"}
    (request,) = sent
    assert request.full_url == "https://api.github.com/repos/GenesisMeshLabs/sdk-go"
    # urllib copies request.headers onto a redirect, never the unredirected ones.
    assert "Authorization" not in request.headers
    if token:
        assert request.unredirected_hdrs == {"Authorization": f"Bearer {token}"}
    else:
        assert "Authorization" not in request.unredirected_hdrs


def _job(name: str) -> str:
    text = (REPO_ROOT / ".github" / "workflows" / "interop.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text)
    assert match
    return match.group(1)


def test_interoperability_checks_out_each_sdk_at_its_pinned_commit_and_no_branch_by_name() -> None:
    job = _job("interop")
    # The pins are resolved on GitHub before any SDK checkout; a failure fails the step.
    read = job.index('python3 scripts/consumer_pins.py env | tee -a "$GITHUB_ENV"')
    step = job[job.rindex("- name:", 0, read):read]
    assert "set -euo pipefail" in step
    assert "GITHUB_TOKEN: ${{ github.token }}" in step
    for name, variable in pins.CONSUMERS.items():
        checkout = job.index(f"repository: GenesisMeshLabs/{name}\n")
        assert read < checkout
        assert job[checkout:].split("\n")[1].strip() == f"ref: ${{{{ env.{variable} }}}}"
    # No ref chosen from the branch or the run: only the committed pins.
    for gone in ("head_ref", "ref_name", "ls-remote", "env.SDK_REF ", "env.SDK_REF }"):
        assert gone not in job
    assert job.count("repository: GenesisMeshLabs/") == len(pins.CONSUMERS)
