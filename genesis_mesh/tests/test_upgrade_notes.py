"""scripts/upgrade_notes.py: pull requests add upgrade-note fragments, only a release adds a section."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "upgrade_notes.py"

PAGE = """# Upgrade and Rollback

## Procedure

1. Back up first.

## Upgrading to 1.7

1.7 adds migration 019.

- **Old.** Note.

## Rollback

Restore the backup.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(SCRIPT, tmp_path / "scripts" / "upgrade_notes.py")
    (tmp_path / "VERSION").write_text("1.7.0\n", encoding="utf-8")
    (tmp_path / "docs" / "operations").mkdir(parents=True)
    (tmp_path / "docs" / "operations" / "upgrade.md").write_text(PAGE, encoding="utf-8", newline="\n")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "scripts/upgrade_notes.py", *args], cwd=repo, capture_output=True,
                          text=True)


def _fragment(repo: Path, version: str, name: str, text: str | bytes) -> Path:
    path = repo / "upgrade.d" / version / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_the_release_folds_fragments_into_one_section_above_the_newest(repo):
    _fragment(repo, "1.8.0", "b-grants.md", "- **Grants.** Second.\n")
    _fragment(repo, "1.8.0", "a-migration.md", "1.8 adds migration 020.\n\n- **Index.** First.\n")
    _fragment(repo, "1.8.0", "c-detail.md", "### A subsection\n\nWith text.\n")
    assert _run(repo, "check").returncode == 0
    assert _run(repo, "preview", "1.8.0").stdout.startswith("1.8 adds migration 020.")
    done = _run(repo, "release", "1.8.0")
    assert done.returncode == 0, done.stderr
    page = (repo / "docs" / "operations" / "upgrade.md").read_text(encoding="utf-8")
    assert "## Upgrading to 1.8\n\n1.8 adds migration 020.\n\n- **Index.** First.\n- **Grants.** Second.\n\n" \
           "### A subsection\n\nWith text.\n\n## Upgrading to 1.7\n" in page
    assert not (repo / "upgrade.d" / "1.8.0").exists()
    refused = _run(repo, "release", "1.8.0")
    assert refused.returncode != 0 and "already has 'Upgrading to 1.8'" in refused.stderr


def test_a_patch_release_names_its_patch(repo):
    _fragment(repo, "1.7.1", "proxy.md", "- **Proxy.** Set it.\n")
    assert _run(repo, "release", "1.7.1").returncode == 0
    assert "## Upgrading to 1.7.1\n\n- **Proxy.** Set it.\n\n## Upgrading to 1.7\n" in (
        repo / "docs" / "operations" / "upgrade.md").read_text(encoding="utf-8")


def test_a_release_without_fragments_is_refused(repo):
    refused = _run(repo, "release", "1.8.0")
    assert refused.returncode != 0 and "no fragments for 1.8.0" in refused.stderr


@pytest.mark.parametrize(
    ("version", "name", "text", "problem"),
    [
        ("1.7.0", "late.md", "- late\n", "version 1.7.0 is released"),
        ("1.8.0", "Bad.md", "- x\n", "name fragments like"),
        ("1.8.0", "heading.md", "## Upgrading to 1.8\n\n- x\n", "the section heading comes from the release"),
        ("1.8.0", "top.md", "# Title\n", "the section heading comes from the release"),
        ("1.8.0", "nospace.md", "###Sub\n", "a heading needs a space"),
        ("1.8.0", "empty.md", "\n\n", "is empty"),
        ("1.8.0", "fence.md", "```bash\n## not a heading in code\n", "a code block is not closed"),
        ("1.8.0", "bom.md", b"\xef\xbb\xbf- x\n", "byte order mark"),
        ("1.8.0", "latin1.md", b"- caf\xe9\n", "is not UTF-8"),
        ("next", "x.md", "- x\n", "notes go in upgrade.d/<version>/"),
    ],
)
def test_check_refuses_a_malformed_fragment(repo, version, name, text, problem):
    _fragment(repo, version, name, text)
    refused = _run(repo, "check")
    assert refused.returncode == 1 and problem in refused.stdout, refused.stdout


def test_a_code_block_may_hold_heading_lines(repo):
    _fragment(repo, "1.8.0", "code.md", "Run:\n\n```bash\n# a comment\n```\n")
    assert _run(repo, "check").returncode == 0


def test_a_fragment_outside_a_version_folder_is_refused(repo):
    (repo / "upgrade.d").mkdir()
    (repo / "upgrade.d" / "README.md").write_text("how to\n", encoding="utf-8")
    (repo / "upgrade.d" / "loose.md").write_text("- x\n", encoding="utf-8")
    refused = _run(repo, "check")
    assert refused.returncode == 1 and "upgrade.d/loose.md" in refused.stdout and "README" not in refused.stdout


def test_the_page_has_no_section_for_an_unreleased_version(repo):
    page = repo / "docs" / "operations" / "upgrade.md"
    page.write_text(PAGE.replace("## Upgrading to 1.7\n", "## Upgrading to 1.8\n\n- early\n\n## Upgrading to 1.7\n"),
                    encoding="utf-8", newline="\n")
    refused = _run(repo, "check")
    assert refused.returncode == 1 and "'Upgrading to 1.8' is for an unreleased version" in refused.stdout
    (repo / "VERSION").write_text("1.8.0\n", encoding="utf-8")  # the release PR bumps VERSION with the fold
    assert _run(repo, "check").returncode == 0


def test_the_repository_passes_its_own_check():
    done = subprocess.run([sys.executable, str(SCRIPT), "check"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
