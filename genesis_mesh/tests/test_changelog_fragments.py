"""scripts/changelog.py: pull requests add fragments, only a release edits CHANGELOG.md."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changelog.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false",
                    *args], cwd=repo, check=True, capture_output=True)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "scripts/changelog.py", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(SCRIPT, tmp_path / "scripts" / "changelog.py")
    (tmp_path / "VERSION").write_text("1.2.0\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## v1.2.0 - Earlier\n\n### Added\n\n- old\n",
                                           encoding="utf-8", newline="\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat/x")
    return tmp_path


def _fragment(repo: Path, version: str, name: str, text: str) -> None:
    (repo / "changelog.d" / version).mkdir(parents=True, exist_ok=True)
    (repo / "changelog.d" / version / name).write_text(text, encoding="utf-8", newline="\n")


def test_a_feature_pr_adds_fragments_and_never_changelog_lines(repo):
    _fragment(repo, "1.3.0", "a.md", "### Added\n\n- **New.** Explained.\n\n```bash\n# a comment\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fragment")
    assert _run(repo, "check", "--base", "main", "--branch", "feat/x").returncode == 0
    with (repo / "CHANGELOG.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n## v1.3.0 - Next\n")
    _git(repo, "commit", "-qam", "edit")
    refused = _run(repo, "check", "--base", "main", "--branch", "feat/x")
    assert refused.returncode == 1 and "CHANGELOG.md gains lines" in refused.stdout
    assert _run(repo, "check", "--base", "main", "--branch", "release/1.3.0").returncode == 0


def test_fragments_must_be_well_formed_and_for_an_unreleased_version(repo):
    _fragment(repo, "1.2.0", "late.md", "### Added\n\n- late\n")
    _fragment(repo, "1.3.0", "Bad.md", "### Added\n\n- x\n")
    _fragment(repo, "1.3.0", "loose.md", "Text before a section.\n\n### Added\n\n- x\n")
    _fragment(repo, "1.3.0", "deep.md", "## A version heading\n")
    out = _run(repo, "check").stdout
    assert "1.2.0 is released" in out and "lower case" in out
    assert "text before the first" in out and "only '### Section' headings" in out


def test_a_release_folds_the_fragments_in_and_removes_them(repo):
    _fragment(repo, "1.3.0", "a.md", "### Added\n\n- one\n\n### Fixed\n\n- a fix\n")
    _fragment(repo, "1.3.0", "b.md", "### Fixed\n\n- another fix\n\n### Upgrading\n\nDo this.\n")
    done = _run(repo, "release", "1.3.0", "--heading", "## v1.3.0 - Next")
    assert done.returncode == 0, done.stderr
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text == ("# Changelog\n\n## v1.3.0 - Next\n\n### Added\n\n- one\n\n### Fixed\n\n- a fix\n- another fix\n\n"
                    "### Upgrading\n\nDo this.\n\n## v1.2.0 - Earlier\n\n### Added\n\n- old\n")
    assert not (repo / "changelog.d" / "1.3.0").exists()


def test_the_repository_fragments_are_valid():
    done = subprocess.run([sys.executable, str(SCRIPT), "check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
