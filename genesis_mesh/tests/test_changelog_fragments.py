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
    assert refused.returncode == 1 and "CHANGELOG.md changes outside a release PR" in refused.stdout
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


# --- 1.3.1 -------------------------------------------------------------------------


def _commit(repo: Path, message: str = "change") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _check(repo: Path, branch: str = "feat/x") -> subprocess.CompletedProcess:
    return _run(repo, "check", "--base", "main", "--branch", branch)


def test_only_a_release_branch_for_a_version_may_change_the_changelog(repo):
    with (repo / "CHANGELOG.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n## v1.3.0 - Next\n")
    _commit(repo)
    for branch in ("release/next", "release/1.3", "release/1.3.0/x", "release/01.3.0", "hotfix/release/1.3.0"):
        assert _check(repo, branch).returncode == 1, branch
    assert _check(repo, "release/1.3.0").returncode == 0


@pytest.mark.parametrize("edit", [
    lambda text: text.replace("- old\n", ""),
    lambda text: text.replace("- old\n", "- old\n++ not counted as an added line\n"),
    lambda text: text.replace("- old", "- rewritten"),
], ids=["deleted history", "a line starting with ++", "rewritten history"])
def test_any_change_to_the_changelog_outside_a_release_is_refused(repo, edit):
    path = repo / "CHANGELOG.md"
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    _commit(repo)
    refused = _check(repo)
    assert refused.returncode == 1 and "CHANGELOG.md changes outside a release PR" in refused.stdout


@pytest.mark.parametrize("place", ["loose.md", "01.4.0/a.md", "1.4/a.md", "1.4.0/sub/a.md", "v1.4.0/a.md"])
def test_a_fragment_the_release_would_never_fold_is_refused(repo, place):
    path = repo / "changelog.d" / place
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("### Added\n\n- lost\n", encoding="utf-8", newline="\n")
    (repo / "changelog.d" / "README.md").write_text("# Fragments\n", encoding="utf-8")
    refused = _run(repo, "check")
    assert refused.returncode == 1 and "changelog.d/<version>/" in refused.stdout, refused.stdout


def test_a_release_refuses_a_version_the_changelog_already_has(repo):
    _fragment(repo, "1.2.0", "again.md", "### Fixed\n\n- again\n")
    refused = _run(repo, "release", "1.2.0", "--heading", "## [1.2.0] - 2026-10-12")
    assert refused.returncode != 0 and "already has 1.2.0" in refused.stderr
    _fragment(repo, "1.3.0", "a.md", "### Fixed\n\n- a fix\n")
    wrong = _run(repo, "release", "1.3.0", "--heading", "## v1.2.0 - Twice")
    assert wrong.returncode != 0 and "must name version 1.3.0" in wrong.stderr
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8").count("1.2.0") == 1


def test_sections_are_released_in_a_fixed_order(repo):
    _fragment(repo, "1.3.0", "a.md", "### Upgrading\n\nDo this.\n\n### Fixed\n\n- a fix\n")
    _fragment(repo, "1.3.0", "b.md", "### Added\n\n- new\n\n### Documentation\n\n- docs\n\n### Security\n\n- safer\n")
    out = _run(repo, "preview", "1.3.0").stdout
    headings = [line for line in out.splitlines() if line.startswith("### ")]
    assert headings == ["### Security", "### Added", "### Fixed", "### Documentation", "### Upgrading"]


def test_wrapped_bullets_from_two_fragments_stay_one_tight_list(repo):
    _fragment(repo, "1.3.0", "a.md", "### Fixed\n\n- **One.** A long entry that\n  wraps onto a second line.\n")
    _fragment(repo, "1.3.0", "b.md", "### Fixed\n\n- **Two.** Another entry that\n  wraps as well.\n")
    out = _run(repo, "preview", "1.3.0").stdout
    assert "wraps onto a second line.\n- **Two.**" in out


@pytest.mark.parametrize("text, message", [
    ("\ufeff### Added\n\n- x\n", "byte order mark"),
    ("###Added\n\n- x\n", "needs a space"),
    ("### Added\n\n- x\n###Fixed\n- y\n", "needs a space"),
    ("### Added\n\n- x\n\n  ## Not a section\n", "only '### Section' headings"),
    ("### Added\n\n- x\n\n```markdown\n## Ends the release notes\n```\n", "would end the version's release notes"),
    ("### Added\n\n- x\n\n```bash\nunclosed\n", "not closed"),
])
def test_a_malformed_fragment_is_named_for_what_is_wrong(repo, text, message):
    (repo / "changelog.d" / "1.3.0").mkdir(parents=True)
    (repo / "changelog.d" / "1.3.0" / "a.md").write_bytes(text.encode("utf-8"))
    refused = _run(repo, "check")
    assert refused.returncode == 1 and message in refused.stdout, refused.stdout
