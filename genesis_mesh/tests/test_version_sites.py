"""Tests for scripts/check_version.py: every statement of the current release names VERSION.

A release writes the version everywhere with ``--set``; the check fails on a
site that lags, and on a site whose statements were added or removed without
updating ``SITES``. Historical mentions of a version never change.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_version", REPO_ROOT / "scripts" / "check_version.py")
assert _spec and _spec.loader
check_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_version)

FILES = ["VERSION", *dict.fromkeys(site[0] for site in check_version.SITES)]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of VERSION and every site file."""
    for name in FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, tmp_path / name)
    return tmp_path


def test_the_repository_names_one_version_everywhere() -> None:
    assert check_version.problems(REPO_ROOT) == []


def test_set_writes_every_site_and_keeps_history(tree: Path) -> None:
    upgrade = tree / "docs" / "installation.md"
    upgrade.write_text(upgrade.read_text(encoding="utf-8") + "\nThe edge agent arrived in 1.7.0.\n", encoding="utf-8")

    check_version.set_version(tree, "9.8.7")

    assert check_version.problems(tree) == []
    assert (tree / "VERSION").read_text(encoding="utf-8") == "9.8.7\n"
    text = upgrade.read_text(encoding="utf-8")
    assert "ghcr.io/genesismeshlabs/genesis-mesh:9.8.7" in text
    assert "arrived in 1.7.0" in text


def test_set_keeps_line_endings(tree: Path) -> None:
    readme = tree / "README.md"
    readme.write_bytes(readme.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    check_version.set_version(tree, "9.8.7")

    data = readme.read_bytes()
    assert b"(9.8.7 today)" in data
    assert data.count(b"\n") == data.count(b"\r\n")


def test_a_lagging_site_is_reported(tree: Path) -> None:
    compose = tree / "deploy" / "kubernetes" / "na-deployment.yaml"
    version = check_version.release_version(tree)
    compose.write_text(compose.read_text(encoding="utf-8").replace(version, "0.1.0"), encoding="utf-8")

    assert check_version.problems(tree) == [f"deploy/kubernetes/na-deployment.yaml: 0.1.0 where VERSION is {version}"]


def test_a_removed_statement_is_reported(tree: Path) -> None:
    readme = tree / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("today)", "now)"), encoding="utf-8")

    [problem] = check_version.problems(tree)
    assert problem.startswith("README.md: expected 1 statement(s) of the release, found 0")


def test_set_refuses_a_non_release_version(tree: Path) -> None:
    with pytest.raises(SystemExit):
        check_version.set_version(tree, "1.9")
    assert check_version.problems(tree) == []
