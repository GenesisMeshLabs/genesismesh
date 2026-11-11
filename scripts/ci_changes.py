"""Decide whether a heavy CI job has anything to test in a pull request.

    python scripts/ci_changes.py GROUP --base SHA --head SHA     # prints run=true|false
    python scripts/ci_changes.py GROUP --files a.py docs/x.md    # the same, for given paths

The upgrade rehearsals, the container images, the PostgreSQL suite, the
interoperability proof and the pilot rehearsal take most of a pull request's
CI time. Each still runs on every push to ``main``, every manual run and
every change that can affect it. A pull request or merge-queue entry that
touches none of a job's inputs skips it, and the job reports success under
its required-check name.

Every changed path is put in one category. A job runs when any changed path
is in one of its categories. A path no rule knows is ``unknown`` and runs
every job, as does a change to this script or to the workflow file that
calls it. So the rules can only make CI run more, never hide a change. When
anything goes wrong (no base, a git error), the answer is ``run=true``.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys

#: (pattern, category), first match wins. ``*`` matches across ``/`` (fnmatch).
RULES: tuple[tuple[str, str], ...] = (
    ("scripts/ci_changes.py", "ci-changes"),
    (".github/workflows/changes.yml", "ci-changes"),
    (".github/workflows/*", "workflow:{name}"),
    (".github/*", "github-meta"),
    ("genesis_mesh/tests/*", "tests"),
    ("genesis_mesh/*", "package"),
    ("conformance/*", "conformance"),
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
    "upgrade": frozenset({"package", "build", "workflow:upgrade.yml", "script:upgrade_rehearsal.py"}),
    "pilot": frozenset({"package", "build", "workflow:pilot-readiness.yml", "script:pilot_rehearsal.py",
                        "script:recovery_drill.py", "script:upgrade_rehearsal.py"}),
    "interop": frozenset({"package", "build", "conformance", "interop", "workflow:interop.yml"}),
    "postgres": frozenset({"package", "tests", "build", "conformance", "contract", "examples", "interop",
                           "workflow:ci.yml", "script:*"}),
    "container": frozenset({"package", "build", "image", "workflow:ci.yml", "script:container_smoke.py",
                            "script:image_vuln_gate.py", "script:lock_image_requirements.py"}),
}
ALWAYS = frozenset({"unknown", "ci-changes"})


def category(path: str) -> str:
    for pattern, name in RULES:
        if fnmatch.fnmatchcase(path, pattern):
            return name.format(name=path.rsplit("/", 1)[-1])
    return "unknown"


def runs(group: str, paths: list[str]) -> bool:
    wanted = GROUPS[group]
    for path in paths:
        found = category(path)
        if found in ALWAYS or found in wanted or (found.startswith("script:") and "script:*" in wanted):
            return True
    return False


def changed_paths(base: str, head: str) -> list[str] | None:
    """Paths changed between the merge base of ``base`` and ``head``, and ``head``; None on any error."""
    try:
        out = subprocess.run(["git", "diff", "--name-only", "-z", f"{base}...{head}"], check=True,
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
