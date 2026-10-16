"""scripts/regression_test_check.py: a bug fix that changes source must change a test."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "regression_test_check.py"
_spec = importlib.util.spec_from_file_location("regression_test_check", SCRIPT)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.mark.parametrize("title", ["fix: refuse x", "fix(db): refuse x", "fix!: refuse x", "Fix(db): x"])
def test_a_fix_changing_source_without_a_test_fails(title):
    assert check.problems(title, False, ["genesis_mesh/na_service/db.py", "changelog.d/1.7.1/x.md"])


@pytest.mark.parametrize("test_file", [
    "genesis_mesh/tests/test_db_migration.py",
    "genesis_mesh/tests/integration/test_ha_failover.py",
    "interop/python/verify.py",
])
def test_a_fix_with_a_test_change_passes(test_file):
    assert check.problems("fix(db): x", False, ["genesis_mesh/na_service/db.py", test_file]) == []


def test_the_no_test_needed_label_passes():
    assert check.problems("fix: x", True, ["genesis_mesh/na_service/db.py"]) == []


@pytest.mark.parametrize("title", ["feat: x", "docs: fix typo", "chore(ci): fix the workflow", "fixup: x", "prefix: x"])
def test_other_pull_requests_pass(title):
    assert check.problems(title, False, ["genesis_mesh/na_service/db.py"]) == []


@pytest.mark.parametrize("files", [
    ["docs/operations/upgrade.md"],
    [".github/workflows/ci.yml"],
    ["conformance/vectors/grants.json", "changelog.d/1.7.1/x.md"],
    ["contract/public-surface.json", "ops/plan-v1.7.1.md", "README.md", "CODEOWNERS"],
])
def test_a_fix_to_docs_ci_or_vectors_only_needs_no_test(files):
    assert check.problems("fix: x", False, files) == []


@pytest.mark.parametrize("path", [
    "genesis_mesh/trust/grants.py", "scripts/changelog.py", "conformance/runner.py", "requirements.txt",
    "Dockerfile", "deploy/compose/docker-compose.yml", "genesis_mesh/na_service/migrations/019_edge_nodes.sql",
])
def test_source_files(path):
    assert check.is_source(path)


def _env(monkeypatch, **values: str) -> None:
    for name in ("EVENT_NAME", "PR_TITLE", "NO_TEST_NEEDED", "BASE_SHA", "HEAD_SHA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_merge_groups_pass(monkeypatch):
    _env(monkeypatch, EVENT_NAME="merge_group")
    assert check.main() == 0


def test_a_fix_pull_request_without_shas_fails(monkeypatch):
    _env(monkeypatch, EVENT_NAME="pull_request", PR_TITLE="fix: x", NO_TEST_NEEDED="false")
    assert check.main() == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_reads_the_changed_files_from_git(tmp_path, monkeypatch):
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args],
            cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")
    git("commit", "-qam", "fix")
    head = git("rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    _env(monkeypatch, EVENT_NAME="pull_request", PR_TITLE="fix: x", NO_TEST_NEEDED="false",
         BASE_SHA=base, HEAD_SHA=head)
    assert check.main() == 1
    monkeypatch.setenv("NO_TEST_NEEDED", "true")
    assert check.main() == 0
    (tmp_path / "test_app.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "test")
    monkeypatch.setenv("NO_TEST_NEEDED", "false")
    monkeypatch.setenv("HEAD_SHA", git("rev-parse", "HEAD"))
    assert check.main() == 0
