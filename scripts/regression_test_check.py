"""A bug-fix pull request that changes source files must change a test.

The CI check "Regression test" runs this on every pull request and merge
group. A pull request whose title starts with ``fix:``, ``fix(`` or ``fix!:``
and that changes source files (anything but docs, CI, changelog fragments,
plans, the contract and conformance vectors) fails unless it also changes a
test file, or carries the label ``no-test-needed`` (set by the Maintainer when
a fix cannot be tested, with the reason in the pull request). Other pull
requests and merge groups pass: the queue re-runs a pull request that already
passed this check.

Inputs come from the environment, never from the command line, so a title
is never interpreted by a shell::

    EVENT_NAME=pull_request PR_TITLE="fix: ..." NO_TEST_NEEDED=false \
    BASE_SHA=<base> HEAD_SHA=<head> python scripts/regression_test_check.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import PurePosixPath

FIX_TITLE = re.compile(r"^fix(\(|!?:)", re.IGNORECASE)
LABEL = "no-test-needed"

#: Paths that are not source: a fix that only changes these needs no test.
NOT_SOURCE_PREFIXES = (
    ".github/",
    "changelog.d/",
    "conformance/vectors/",
    "conformance/fixtures/",
    "contract/",
    "docs/",
    "ops/",
)
NOT_SOURCE_SUFFIXES = (".md", ".rst")
NOT_SOURCE_FILES = {
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "CODEOWNERS",
    "LICENSE",
    "VERSION",
}


def is_test(path: str) -> bool:
    """A test file: the test tree, the interop harness, or a ``test_*.py`` / ``*_test.py`` file."""
    p = PurePosixPath(path)
    return (
        path.startswith(("genesis_mesh/tests/", "interop/"))
        or "tests" in p.parts[:-1]
        or p.name.startswith("test_")
        or p.stem.endswith("_test")
    )


def is_source(path: str) -> bool:
    """A file whose change can introduce or fix a bug: not a test, not docs, CI, plans or vectors."""
    if is_test(path):
        return False
    return not (
        path.startswith(NOT_SOURCE_PREFIXES)
        or path.endswith(NOT_SOURCE_SUFFIXES)
        or path in NOT_SOURCE_FILES
    )


def is_fix(title: str) -> bool:
    return bool(FIX_TITLE.match(title.strip()))


def problems(title: str, labelled: bool, changed: Iterable[str]) -> list[str]:
    """Why the pull request fails the check (empty when it passes)."""
    if not is_fix(title) or labelled:
        return []
    files = list(changed)
    source = [f for f in files if is_source(f)]
    if not source or any(is_test(f) for f in files):
        return []
    shown = ", ".join(source[:5]) + (f" and {len(source) - 5} more" if len(source) > 5 else "")
    return [
        f"this bug fix changes source files ({shown}) but no test file: add the test that fails "
        f"without the fix, or ask the Maintainer for the label '{LABEL}' with the reason in the pull request"
    ]


def changed_files(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def main() -> int:
    event = os.environ.get("EVENT_NAME", "")
    if event != "pull_request":
        print(f"{event or 'this event'}: nothing to check (pull requests are checked when opened or updated)")
        return 0
    title = os.environ.get("PR_TITLE", "")
    labelled = os.environ.get("NO_TEST_NEEDED", "").lower() == "true"
    if not is_fix(title):
        print("not a bug fix (title does not start with fix: or fix(): no regression test required")
        return 0
    if labelled:
        print(f"labelled '{LABEL}': no regression test required")
        return 0
    base, head = os.environ.get("BASE_SHA", ""), os.environ.get("HEAD_SHA", "")
    if not base or not head:
        print("::error::BASE_SHA and HEAD_SHA are required for a pull request")
        return 1
    found = problems(title, labelled, changed_files(base, head))
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print("bug fix with a test change, or no source change: OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
