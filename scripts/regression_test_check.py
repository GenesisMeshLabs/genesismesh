"""A bug-fix pull request that changes source files must change a test.

The CI check "Regression test" runs this on every pull request and merge
group. A pull request whose title starts with ``fix:``, ``fix(`` or ``fix!:``
and that changes source files (anything but docs, CI, changelog fragments,
plans, the contract and conformance vectors) fails unless it also changes a
test file (added or modified; a deleted test is a source change, and test
data such as fixtures or vectors is not a test), or carries the label
``no-test-needed`` (set by the Maintainer when
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
#: Code a test is written in; anything else in a test tree is test data.
TEST_CODE_SUFFIXES = (".py", ".go", ".ts", ".js", ".mjs", ".cs", ".rs", ".sh")
#: Directories that hold test data (fixtures, vectors), never tests themselves.
TEST_DATA_DIRS = {"fixtures", "vectors", "testdata", "conformance"}
NOT_SOURCE_FILES = {
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "CODEOWNERS",
    "LICENSE",
    "VERSION",
}


def in_test_tree(path: str) -> bool:
    """In the test tree or the interop harness (test code or test data)."""
    p = PurePosixPath(path)
    return path.startswith(("genesis_mesh/tests/", "interop/")) or "tests" in p.parts[:-1]


def is_test(path: str) -> bool:
    """Test code: a code file in the test tree or named ``test_*`` / ``*_test``, not fixtures or vectors."""
    p = PurePosixPath(path)
    if not path.endswith(TEST_CODE_SUFFIXES) or TEST_DATA_DIRS & set(p.parts[:-1]):
        return False
    return in_test_tree(path) or p.name.startswith("test_") or p.stem.endswith("_test")


def is_doc_ci_or_data(path: str) -> bool:
    """Docs, CI, changelog fragments, plans, the contract and conformance vectors."""
    return path.startswith(NOT_SOURCE_PREFIXES) or path.endswith(NOT_SOURCE_SUFFIXES) or path in NOT_SOURCE_FILES


def is_source(path: str) -> bool:
    """A file whose change can introduce or fix a bug: not test code or test data, docs, CI, plans or vectors."""
    return not (in_test_tree(path) or is_test(path) or is_doc_ci_or_data(path))


def is_fix(title: str) -> bool:
    return bool(FIX_TITLE.match(title.strip()))


def problems(title: str, labelled: bool, changed: Iterable[str], deleted: Iterable[str] = ()) -> list[str]:
    """Why the pull request fails the check (empty when it passes).

    ``changed`` are added or modified files, ``deleted`` deleted ones. Only an
    added or modified test counts as a test; a deleted file (a test too) counts
    as a source change unless it is docs, CI, plans or vectors.
    """
    if not is_fix(title) or labelled:
        return []
    files = list(changed)
    removed = list(deleted)
    source = [f for f in files if is_source(f)] + [f for f in removed if not is_doc_ci_or_data(f)]
    if not source or any(is_test(f) for f in files):
        return []
    shown = ", ".join(source[:5]) + (f" and {len(source) - 5} more" if len(source) > 5 else "")
    return [
        f"this bug fix changes source files ({shown}) but no test file: add the test that fails "
        f"without the fix, or ask the Maintainer for the label '{LABEL}' with the reason in the pull request"
    ]


def changed_files(base: str, head: str) -> tuple[list[str], list[str]]:
    """``(added or modified, deleted)`` paths between the merge base and ``head``."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    )
    changed: list[str] = []
    deleted: list[str] = []
    for line in out.stdout.splitlines():
        status, _, path = line.partition("\t")
        if path:
            (deleted if status.startswith("D") else changed).append(path)
    return changed, deleted


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
    changed, deleted = changed_files(base, head)
    found = problems(title, labelled, changed, deleted)
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print("bug fix with a test change, or no source change: OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
