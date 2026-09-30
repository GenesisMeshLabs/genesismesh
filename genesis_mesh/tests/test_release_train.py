"""Tests for scripts/check_release_train.py, the cross-repository version gate.

The v0.57 clash (the Rust gateway tagged v0.57.x before the core reached v0.57)
must be rejected. These tests stub the remote tag listing; no network access.
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


def test_component_release_ahead_of_core_is_rejected() -> None:
    released = {"genesismesh": [(0, 56, 0)], "gateway": [(0, 56, 3), (0, 57, 2)]}
    assert train.conflicts((0, 57, 0), released) == ["gateway already released v0.57.2"]


def test_version_at_or_above_every_release_is_accepted() -> None:
    released = {"genesismesh": [(0, 56, 0)], "gateway": [(0, 57, 2)], "sdk-rust": []}
    assert train.conflicts((0, 58, 0), released) == []
    # A component that already tagged the same coordinated version is in the same train.
    assert train.conflicts((0, 58, 0), {"sdk-go": [(0, 58, 0)]}) == []


def test_versions_compare_numerically_not_lexically() -> None:
    assert train.conflicts((0, 9, 0), {"sdk-go": [(0, 10, 0)]}) == ["sdk-go already released v0.10.0"]


def test_remote_tags_are_parsed_ignoring_non_release_refs() -> None:
    listing = "\n".join([
        "abc\trefs/tags/v0.57.2",
        "def\trefs/tags/v0.56.0",
        "123\trefs/tags/nightly",
        "456\trefs/tags/v0.58.0-rc1",
    ])
    with patch.object(train.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, listing, "")):
        assert sorted(train.released_versions("gateway")) == [(0, 56, 0), (0, 57, 2)]


def test_main_fails_with_guidance(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(train, "released_versions", side_effect=lambda c: [(0, 57, 2)] if c == "gateway" else []):
        with pytest.raises(SystemExit, match="behind the release train"):
            train.main(["--version", "0.57.0"])
        assert "gateway already released v0.57.2" in capsys.readouterr().out
        assert train.main(["--version", "0.58.0"]) == 0


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
    assert "extraheader" not in " ".join(calls[0])
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
    assert len(calls) == 1 and "extraheader" not in " ".join(calls[0])
