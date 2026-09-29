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
