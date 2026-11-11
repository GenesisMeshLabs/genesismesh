"""Decide whether a heavy CI job has anything to test in a pull request.

    python scripts/ci_changes.py GROUP --base SHA --head SHA     # prints run=true|false
    python scripts/ci_changes.py GROUP --files a.py docs/x.md    # the same, for given paths

The upgrade rehearsals, the container images, the PostgreSQL suite, the
interoperability proof and the pilot rehearsal take most of a pull request's
CI time. Each still runs on every push to ``main``, every manual run and
every change that can affect it. A pull request or merge-queue entry that
touches none of a job's inputs skips it. A summary job carries the
required-check name and passes only when the job succeeded or was skipped
on an explicit ``run=false``.

Every changed path is put in one category. A job runs when any changed path
is in one of its categories. A path no rule knows is ``unknown`` and runs
every job. So does a change to this script, to ``changes.yml``, or to any
workflow that calls it: a pull request that edits how its own jobs are
chosen runs them all. A renamed file counts under both its old and its new
path. So the rules can only make CI run more, never hide a change. When
anything goes wrong (no base, a git error), the answer is ``run=true``.

The check runs the pull request's own copy of this script and of
``changes.yml``. Each guards edits to the other, but a pull request that
breaks both is caught only by review. Both are CI workflow paths, which the
Maintainer reviews.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The workflows that call changes.yml. A change to one of them, or to any workflow that calls it
#: now (a renamed or new caller), runs every group.
CALLERS = frozenset({"ci.yml", "upgrade.yml", "pilot-readiness.yml", "interop.yml"})

#: (pattern, category), first match wins. ``*`` matches across ``/`` (fnmatch).
RULES: tuple[tuple[str, str], ...] = (
    ("scripts/ci_changes.py", "ci-changes"),
    (".github/workflows/changes.yml", "ci-changes"),
    *((f".github/workflows/{name}", "ci-changes") for name in sorted(CALLERS)),
    (".github/workflows/*", "workflow:{name}"),
    (".github/*", "github-meta"),
    ("genesis_mesh/tests/*", "tests"),
    ("genesis_mesh/*", "package"),
    ("conformance/*", "conformance"),
    # The SDK releases the Interoperability run checks out and the gateway
    # release the container jobs test with.
    ("contract/consumer-pins.json", "consumer-pins"),
    ("contract/*", "contract"),
    ("interop/*", "interop"),
    ("examples/*", "examples"),
    ("deploy/*", "image"),
    ("docker/*", "image"),
    ("Dockerfile", "image"),
    (".dockerignore", "image"),
    ("start.sh", "image"),
    # The image copies README.md and LICENSE; VERSION is its build argument.
    ("README.md", "build"),
    ("LICENSE", "build"),
    ("VERSION", "build"),
    ("pyproject.toml", "build"),
    ("setup.py", "build"),
    ("requirements*", "build"),
    # Line-ending and binary rules change the bytes every job checks out.
    (".gitattributes", "build"),
    ("pytest.ini", "build"),
    ("mypy.ini", "build"),
    ("ruff.toml", "build"),
    ("scripts/*", "script:{name}"),
    ("docs/*", "docs"),
    ("ops/*", "docs"),
    ("changelog.d/*", "docs"),
    ("upgrade.d/*", "docs"),
    ("infrastructure/*", "infrastructure"),
    ("*.md", "docs"),
    (".env.example", "docs"),
    # Local tooling and repository settings no CI job reads.
    (".gitignore", "repo-meta"),
    (".pre-commit-config.yaml", "repo-meta"),
    ("CODEOWNERS", "repo-meta"),
)

#: The categories each group runs for (``unknown`` and ``ci-changes`` always run every group).
GROUPS: dict[str, frozenset[str]] = {
    "upgrade": frozenset({"package", "build", "script:upgrade_rehearsal.py"}),
    "pilot": frozenset({"package", "build", "script:pilot_rehearsal.py",
                        "script:recovery_drill.py", "script:upgrade_rehearsal.py"}),
    "interop": frozenset({"package", "build", "conformance", "interop", "consumer-pins",
                          "script:consumer_pins.py"}),
    "postgres": frozenset({"package", "tests", "build", "conformance", "contract", "consumer-pins", "examples",
                           "interop", "script:*"}),
    "container": frozenset({"package", "build", "image", "consumer-pins", "script:consumer_pins.py",
                            "script:container_smoke.py", "script:image_vuln_gate.py",
                            "script:lock_image_requirements.py"}),
}
ALWAYS = frozenset({"unknown", "ci-changes"})


def category(path: str, root: Path = ROOT) -> str:
    for pattern, name in RULES:
        if fnmatch.fnmatchcase(path, pattern):
            found = name.format(name=path.rsplit("/", 1)[-1])
            if found.startswith("workflow:") and _calls_detection(root / path):
                return "ci-changes"
            return found
    return "unknown"


def _calls_detection(workflow: Path) -> bool:
    """A workflow (new or renamed) that calls changes.yml decides how its own jobs are chosen."""
    try:
        return "workflows/changes.yml" in workflow.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def runs(group: str, paths: list[str]) -> bool:
    wanted = GROUPS[group]
    for path in paths:
        found = category(path)
        if found in ALWAYS or found in wanted or (found.startswith("script:") and "script:*" in wanted):
            return True
    return False


def changed_paths(base: str, head: str, repo: Path | None = None) -> list[str] | None:
    """Paths changed between the merge base of ``base`` and ``head``, and ``head``; None on any error."""
    git = ["git"] if repo is None else ["git", "-C", str(repo)]
    try:
        # --no-renames: a moved file counts under its old path too (a module moved out of the
        # package is a package change).
        out = subprocess.run([*git, "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"], check=True,
                             capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.decode("utf-8").split("\0") if p]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("group", choices=sorted(GROUPS))
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--files", nargs="*")
    args = parser.parse_args(argv)
    if args.files is not None:
        paths: list[str] | None = args.files
    elif args.base and args.head:
        paths = changed_paths(args.base, args.head)
    else:
        paths = None
    if paths is None:
        decision, why = True, "no diff to judge (push, manual run, or a git error): run"
    elif not paths:
        decision, why = True, "an empty diff: run"
    else:
        decision = runs(args.group, paths)
        relevant = [p for p in paths if runs(args.group, [p])]
        why = f"{len(paths)} changed path(s); relevant to {args.group}: {relevant[:20] or 'none'}"
    print(f"{args.group}: {why}", file=sys.stderr)
    line = f"run={'true' if decision else 'false'}"
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
