"""Tests for scripts/check_release_train.py.

The default run is the core's own monotonic check: it reads only the core's
tags, so a component release never turns core CI red. ``--audit-ceiling`` is
the nightly cross-component ceiling: the v0.57 clash (the Rust gateway tagged
v0.57.x before the core reached v0.57) is still caught there. These tests stub
the remote tag listing; no network access.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_release_train", REPO_ROOT / "scripts" / "check_release_train.py")
assert _spec and _spec.loader
train = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train)


def test_version_behind_a_core_release_is_rejected() -> None:
    assert train.behind((1, 10, 0), [(1, 9, 2), (1, 10, 1)]) == "genesismesh already released v1.10.1"


def test_version_at_or_above_the_latest_core_release_is_accepted() -> None:
    # main after a release carries the released version until the next one is chosen.
    assert train.behind((1, 10, 1), [(1, 10, 0), (1, 10, 1)]) is None
    assert train.behind((1, 11, 0), [(1, 10, 1)]) is None
    assert train.behind((0, 1, 0), []) is None


def test_versions_compare_numerically_not_lexically() -> None:
    assert train.behind((0, 9, 0), [(0, 10, 0)]) == "genesismesh already released v0.10.0"
    assert train.ceiling_breaches([(0, 9, 0)], {"sdk-go": [(0, 10, 0)]}) == [
        "sdk-go released v0.10.0, above the core's latest release v0.9.0"
    ]


def test_the_core_check_reads_only_the_core_tags(capsys: pytest.CaptureFixture[str]) -> None:
    read: list[str] = []

    def released(component: str) -> list[tuple[int, int, int]]:
        read.append(component)
        return [(1, 10, 1)] if component == "genesismesh" else [(9, 9, 9)]

    with patch.object(train, "released_versions", side_effect=released):
        assert train.main(["--version", "1.11.0"]) == 0
        with pytest.raises(SystemExit, match="behind the core's own releases"):
            train.main(["--version", "1.10.0"])
    assert set(read) == {"genesismesh"}
    assert "genesismesh already released v1.10.1" in capsys.readouterr().out


def test_the_core_check_reads_the_version_file_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "VERSION").write_text("1.10.1\n", encoding="utf-8")
    monkeypatch.setattr(train, "ROOT", tmp_path)
    with patch.object(train, "released_versions", return_value=[(1, 10, 1)]):
        assert train.main([]) == 0
    (tmp_path / "VERSION").write_text("1.9.2\n", encoding="utf-8")
    with patch.object(train, "released_versions", return_value=[(1, 10, 1)]):
        with pytest.raises(SystemExit, match="VERSION 1.9.2 is behind"):
            train.main([])


def test_the_ceiling_audit_rejects_a_component_minor_above_the_core() -> None:
    # The v0.57 clash: the gateway tagged v0.57.x while the core's latest release was v0.56.0.
    released = {"gateway": [(0, 56, 3), (0, 57, 2)], "sdk-go": [(0, 56, 0)]}
    assert train.ceiling_breaches([(0, 56, 0)], released) == [
        "gateway released v0.57.2, above the core's latest release v0.56.0"
    ]
    assert train.ceiling_breaches([(1, 10, 1)], {"sdk-rust": [(2, 0, 0)]}) == [
        "sdk-rust released v2.0.0, above the core's latest release v1.10.1"
    ]


def test_the_ceiling_audit_allows_a_component_patch_of_its_own() -> None:
    # A component patch under a released core minor (a 1.11.0+gateway.1.11.1 set) is within the ceiling.
    released = {"gateway": [(1, 11, 1)], "sdk-go": [(1, 10, 1)], "sdk-dotnet": []}
    assert train.ceiling_breaches([(1, 11, 0)], released) == []


def test_the_ceiling_audit_needs_a_core_release() -> None:
    with pytest.raises(SystemExit, match="no release tags"):
        train.ceiling_breaches([], {"gateway": [(1, 0, 0)]})


def test_the_ceiling_audit_reads_every_component(capsys: pytest.CaptureFixture[str]) -> None:
    read: list[str] = []
    tags = {"genesismesh": [(1, 10, 1)], "gateway": [(1, 11, 0)]}

    def released(component: str) -> list[tuple[int, int, int]]:
        read.append(component)
        return tags.get(component, [(1, 10, 1)])

    with patch.object(train, "released_versions", side_effect=released):
        with pytest.raises(SystemExit, match="above the core's latest release v1.10.1"):
            train.main(["--audit-ceiling"])
        assert "gateway released v1.11.0" in capsys.readouterr().out
        tags["gateway"] = [(1, 10, 2)]
        assert train.main(["--audit-ceiling"]) == 0
    assert set(read) == {"genesismesh", *train.COMPONENTS}
    assert "genesismesh" not in train.COMPONENTS


def test_the_two_modes_are_exclusive() -> None:
    with pytest.raises(SystemExit):
        train.main(["--audit-ceiling", "--version", "1.10.1"])


def test_remote_tags_are_parsed_ignoring_non_release_refs() -> None:
    listing = "\n".join([
        "abc\trefs/tags/v0.57.2",
        "def\trefs/tags/v0.56.0",
        "123\trefs/tags/nightly",
        "456\trefs/tags/v0.58.0-rc1",
        "789\trefs/tags/genesis-mesh-verify-v1.11.0",
    ])
    with patch.object(train.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, listing, "")):
        assert sorted(train.released_versions("gateway")) == [(0, 56, 0), (0, 57, 2)]


def test_malformed_version_is_rejected() -> None:
    with pytest.raises(SystemExit, match="not a release version"):
        train.parse("0.58")


def test_token_is_sent_as_a_header_not_in_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "abc\trefs/tags/v0.59.0", "")

    calls: list = []

    def private_then_token(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:  # anonymous attempt: private repository
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: repository not found")
        return fake_run(cmd, **kwargs)

    monkeypatch.setenv("RELEASE_TRAIN_TOKEN", "secret-token")
    monkeypatch.setattr(train.subprocess, "run", private_then_token)
    assert train.released_versions("sdk-go") == [(0, 59, 0)]
    assert "Authorization" not in " ".join(calls[0])
    joined = " ".join(seen["cmd"])
    assert "secret-token" not in joined
    assert "extraheader=Authorization: Basic" in joined
    assert seen["cmd"][-1] == "https://github.com/GenesisMeshLabs/sdk-go.git"


def test_private_repository_error_explains_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELEASE_TRAIN_TOKEN", raising=False)
    monkeypatch.setattr(
        train.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", "fatal: could not read Username"),
    )
    with pytest.raises(SystemExit, match="RELEASE_TRAIN_TOKEN"):
        train.released_versions("sdk-go")


def test_public_repository_is_read_without_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def anonymous_ok(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "abc\trefs/tags/v0.59.0", "")

    monkeypatch.setenv("RELEASE_TRAIN_TOKEN", "token-without-access-to-public-repos")
    monkeypatch.setattr(train.subprocess, "run", anonymous_ok)
    assert train.released_versions("genesismesh") == [(0, 59, 0)]
    assert len(calls) == 1 and "Authorization" not in " ".join(calls[0])


WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_the_ceiling_audit_runs_nightly_never_on_pull_requests() -> None:
    text = (WORKFLOWS / "release-train-audit.yml").read_text(encoding="utf-8")
    triggers = text[text.index("\non:\n"):text.index("\npermissions:")]
    assert "schedule:" in triggers and "workflow_dispatch:" in triggers
    assert "pull_request" not in triggers and "merge_group" not in triggers and "push:" not in triggers
    audit = text[text.index("- name: Audit the ceiling"):text.index("- name: Open or update the issue")]
    # GitHub runs a step without "shell:" as "bash -e", so "| tee" would hide the failure.
    assert "--audit-ceiling" in audit and "| tee" in audit
    assert "set -o pipefail" in audit or "shell: bash" in audit
    issue = text[text.index("- name: Open or update the issue"):]
    assert "if: failure() && github.event_name == 'schedule'" in issue
    assert "gh issue create" in issue and "gh issue comment" in issue
    assert "issues: write" in text


def test_pull_requests_and_publishing_run_only_the_core_check() -> None:
    for name in ("ci.yml", "publish-pypi.yml", "publish-image.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "python scripts/check_release_train.py\n" in text, name
        assert "--audit-ceiling" not in text, name
        assert "RELEASE_TRAIN_TOKEN" not in text, name
