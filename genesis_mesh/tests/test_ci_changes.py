"""v1.11.0: which pull requests skip the heavy CI jobs (``scripts/ci_changes.py``).

The rules may only ever make CI run more: an unknown path, a change to the
detection itself, or no diff to judge runs every job.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_changes", ROOT / "scripts" / "ci_changes.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load()
GROUPS = sorted(cc.GROUPS)


def _run(group: str, *paths: str) -> bool:
    return cc.runs(group, list(paths))


def test_every_tracked_file_has_a_category() -> None:
    """A new top-level file or directory needs a rule; until it has one it runs every job."""
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    unknown = [p for p in listed.decode().split("\0") if p and cc.category(p) == "unknown"]
    assert unknown == [], "add these paths to RULES in scripts/ci_changes.py"


@pytest.mark.parametrize("group", GROUPS)
def test_a_documentation_change_runs_no_heavy_job(group: str) -> None:
    assert not _run(group, "docs/operations/upgrade.md", "ops/plan-v1.11.0-release-model.md",
                    "changelog.d/1.11.0/x.md", "upgrade.d/1.11.0/x.md", "CONTRIBUTING.md")


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("path", ["genesis_mesh/na_service/server.py", "pyproject.toml",
                                  "requirements.txt", "VERSION", ".gitattributes"])
def test_a_package_or_build_change_runs_every_heavy_job(group: str, path: str) -> None:
    assert _run(group, "docs/index.md", path)


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("path", ["scripts/ci_changes.py", ".github/workflows/changes.yml",
                                  "a-new-top-level-file", "newdir/thing.py"])
def test_the_detection_itself_and_unknown_paths_run_every_job(group: str, path: str) -> None:
    assert _run(group, path)


def test_each_group_runs_for_its_own_workflow_and_scripts() -> None:
    assert _run("upgrade", ".github/workflows/upgrade.yml")
    assert _run("upgrade", "scripts/upgrade_rehearsal.py")
    assert _run("pilot", "scripts/recovery_drill.py")
    # The recovery drill imports the upgrade rehearsal.
    assert _run("pilot", "scripts/upgrade_rehearsal.py")
    assert _run("interop", "interop/run_all.sh")
    assert _run("interop", "conformance/vectors/canonical.json")
    assert _run("container", "Dockerfile")
    assert _run("container", "deploy/compose/docker-compose.images.yml")
    assert _run("container", "README.md")  # the image copies it
    assert _run("container", "scripts/container_smoke.py")
    assert _run("postgres", "genesis_mesh/tests/test_grants.py")
    assert _run("postgres", "scripts/gm_contract.py")  # the suite tests the scripts


def test_unrelated_workflows_and_tests_do_not_run_other_groups() -> None:
    assert not _run("upgrade", ".github/workflows/interop.yml")
    assert not _run("container", "genesis_mesh/tests/test_grants.py")
    assert not _run("upgrade", "conformance/vectors/canonical.json", "contract/MANIFEST.json")
    assert not _run("interop", "scripts/gm_contract.py", "contract/bundle.json")
    assert not _run("container", "examples/agent-network/README.md")


def test_no_diff_to_judge_runs(capsys: pytest.CaptureFixture[str]) -> None:
    # A push or a manual run passes no base: run.
    assert cc.main(["upgrade"]) == 0
    assert capsys.readouterr().out.strip() == "run=true"
    # A base git cannot resolve: run.
    assert cc.main(["upgrade", "--base", "0" * 40, "--head", "HEAD"]) == 0
    assert capsys.readouterr().out.strip() == "run=true"


def test_writes_the_decision_for_github_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert cc.main(["container", "--files", "docs/index.md"]) == 0
    assert capsys.readouterr().out.strip() == "run=false"
    assert output.read_text() == "run=false\n"


@pytest.mark.parametrize("workflow,group", [("upgrade.yml", "upgrade"), ("pilot-readiness.yml", "pilot"),
                                            ("interop.yml", "interop"), ("ci.yml", "container"),
                                            ("ci.yml", "postgres")])
def test_each_group_is_wired_into_its_workflow(workflow: str, group: str) -> None:
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    assert re.search(rf"uses: \./\.github/workflows/changes\.yml\s+with:\s+group: {group}\b", text)
    # Jobs skip only on an explicit "false": a failed detection runs them.
    assert "outputs.run != 'false'" in text
