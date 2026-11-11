"""v1.11.0: which pull requests skip the heavy CI jobs (``scripts/ci_changes.py``).

The rules may only ever make CI run more: an unknown path, a change to the
detection itself, or no diff to judge runs every job.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
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


@pytest.mark.parametrize("path", ["contract/consumer-pins.json", "scripts/consumer_pins.py"])
def test_a_pin_bump_runs_the_interoperability_run_against_the_new_pins(path: str) -> None:
    # 1.11.0: Interoperability checks out the SDKs at contract/consumer-pins.json.
    assert cc.category(path) == {"contract/consumer-pins.json": "consumer-pins",
                                 "scripts/consumer_pins.py": "script:consumer_pins.py"}[path]
    assert _run("interop", path)
    assert _run("postgres", path)  # test_consumer_pins.py reads both
    assert not _run("upgrade", path) and not _run("pilot", path)


def test_unrelated_workflows_and_tests_do_not_run_other_groups() -> None:
    assert not _run("upgrade", ".github/workflows/docs.yml")
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


def _job(workflow: str, job: str) -> str:
    """One top-level job's block of a workflow file: its lines indented deeper than the job key.

    It ends at the next line at the job key's own indent, a job or a comment before one (a
    comment there once made the block end in it).
    """
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  \S|^\S|\Z)", text)
    assert match, f"{workflow} has no job {job}"
    return match.group(1)


#: (workflow, detection job, group, gated job, summary job, the summary's required-check name)
WIRING = [
    ("upgrade.yml", "changes", "upgrade", "upgrade", "rehearsals", "Upgrade rehearsals"),
    ("pilot-readiness.yml", "changes", "pilot", "pilot", "pilot-result", "Recovery drill and pilot rehearsal"),
    ("interop.yml", "changes", "interop", "interop", "interop-result", "Python, Go, TypeScript and C# agree"),
    ("ci.yml", "changes-container", "container", "container", "containers", "Container images"),
    ("ci.yml", "changes-postgres", "postgres", "postgres", "postgres-result", "PostgreSQL backend and HA failover"),
]

#: The required status checks of the main branch ruleset (read from GitHub on 2026-11-11; the
#: ruleset is the Maintainer's, this list only notices when a workflow stops reporting a name).
REQUIRED_CHECKS = (
    "Tests and smoke checks", "PostgreSQL backend and HA failover", "Python, Go, TypeScript and C# agree",
    "Recovery drill and pilot rehearsal", "Changelog fragments", "Container images", "Upgrade rehearsals",
    "Regression test",
)


def _job_names() -> dict[str, list[tuple[str, str]]]:
    """Every job ``name:`` in the workflows -> [(workflow, job id)]."""
    names: dict[str, list[tuple[str, str]]] = {}
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^  ([\w-]+):\n    name: (.+)$", text):
            names.setdefault(match.group(2).strip(), []).append((path.name, match.group(1)))
    return names


@pytest.mark.parametrize("workflow,detect,group,gated,summary,required", WIRING)
def test_each_group_is_wired_into_its_workflow(workflow: str, detect: str, group: str, gated: str,
                                               summary: str, required: str) -> None:
    block = _job(workflow, detect)
    assert "uses: ./.github/workflows/changes.yml" in block and f"group: {group}\n" in block
    job = _job(workflow, gated)
    assert f"needs: {detect}\n" in job
    # Jobs skip only on an explicit "false": a failed or cancelled detection runs them.
    assert "if: ${{ !cancelled() && needs." + detect + ".outputs.run != 'false' }}" in job
    # The gated job never carries the required name: a job skipped by its condition reports
    # success, so a skip on cancellation would pass the check. The summary carries it.
    text = _job(workflow, summary)
    assert text.startswith(f"    name: {required}\n")
    assert f"needs: [{detect}, {gated}]" in text and "if: always()" in text
    assert f"RESULT: ${{{{ needs.{gated}.result }}}}" in text
    assert f"RUN: ${{{{ needs.{detect}.outputs.run }}}}" in text
    assert 'if [ "$RUN" = false ] && [ "$RESULT" = skipped ]; then exit 0; fi' in text
    assert text.rstrip().endswith('test "$RESULT" = success')
    assert workflow in cc.CALLERS


def test_every_required_check_is_reported_by_exactly_one_job_and_never_by_a_gated_one() -> None:
    names = _job_names()
    gated = {(workflow, job) for workflow, _, _, job, _, _ in WIRING}
    for required in REQUIRED_CHECKS:
        assert len(names.get(required, [])) == 1, f"{required!r} reported by {names.get(required)}"
        assert names[required][0] not in gated, f"{required!r} is a gated job"


def _summary_script(workflow: str, summary: str) -> str:
    text = _job(workflow, summary)
    match = re.search(r"(?ms)run: \|\n(.*)", text)
    assert match
    return "\n".join(line[10:] for line in match.group(1).splitlines())


RESULTS = ("success", "failure", "cancelled", "skipped")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("workflow,detect,group,gated,summary,required", WIRING)
def test_a_summary_passes_only_on_success_or_on_a_skip_the_detection_asked_for(
        workflow: str, detect: str, group: str, gated: str, summary: str, required: str) -> None:
    """The summary's own shell script, run for every detection answer and job result.

    ``RUN`` is empty when the detection job failed, was cancelled or wrote no output.
    """
    script = _summary_script(workflow, summary)
    bash = shutil.which("bash")
    assert bash
    for run in ("true", "false", ""):
        for result in RESULTS:
            done = subprocess.run([bash, "-e", "-c", script], env={"RUN": run, "RESULT": result, "PATH": ""},
                                  capture_output=True, text=True)
            expected = result == "success" or (run == "false" and result == "skipped")
            assert (done.returncode == 0) == expected, (required, run, result, done.stdout, done.stderr)


def test_every_workflow_that_calls_the_detection_is_a_listed_caller() -> None:
    callers = {p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")
               if p.name != "changes.yml" and "workflows/changes.yml" in p.read_text(encoding="utf-8")}
    assert callers == set(cc.CALLERS)


def test_a_new_or_renamed_workflow_that_calls_the_detection_runs_everything(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "upgrades.yml").write_text("jobs:\n  changes:\n    uses: ./.github/workflows/changes.yml\n")
    (workflows / "other.yml").write_text("jobs:\n  build:\n    runs-on: ubuntu-latest\n")
    assert cc.category(".github/workflows/upgrades.yml", root=tmp_path) == "ci-changes"
    assert cc.category(".github/workflows/other.yml", root=tmp_path) == "workflow:other.yml"


def test_a_renamed_file_counts_under_its_old_path(tmp_path: Path) -> None:
    """Regression: git's rename detection reported only the new path, so moving a module out of
    the package into docs/ skipped every job."""
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.org",
                        *args], check=True, capture_output=True)

    (tmp_path / "genesis_mesh").mkdir()
    (tmp_path / "genesis_mesh" / "mod.py").write_text("VALUE = 1\n" * 20)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (tmp_path / "docs").mkdir()
    git("mv", "genesis_mesh/mod.py", "docs/mod.py")
    git("commit", "-q", "-m", "move")
    paths = cc.changed_paths("HEAD~1", "HEAD", repo=tmp_path)
    assert paths is not None and sorted(paths) == ["docs/mod.py", "genesis_mesh/mod.py"]
    assert all(cc.runs(group, paths) for group in GROUPS)
