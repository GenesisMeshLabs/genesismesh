"""Keep the coordinated release train ahead of every component's released tags.

Genesis Mesh leads one coordinated product version (docs/development/versioning.md).
A component that tags a version the core has not reached creates a number that
means two different releases. This check fails when any component repository,
including this one, has already published a tag newer than ``VERSION``.

Component repositories run the mirror check: they may not declare or tag a
version newer than the core ``VERSION`` on ``main``.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORGANIZATION = "GenesisMeshLabs"
COMPONENTS = ("genesismesh", "sdk-typescript", "sdk-go", "sdk-dotnet", "sdk-rust", "gateway")
TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise SystemExit(f"not a release version: {version!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _git_auth_args() -> list[str]:
    """Git options that authenticate with RELEASE_TRAIN_TOKEN, if set.

    Private component repositories need a read-only token. It is sent as an
    HTTP header, never in the URL, so it cannot appear in error output.
    """
    token = os.environ.get("RELEASE_TRAIN_TOKEN", "").strip()
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", "credential.helper=", "-c", f"http.https://github.com/.extraheader=Authorization: Basic {basic}"]


def _ls_remote(url: str, auth: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *auth, "ls-remote", "--tags", "--refs", url],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def released_versions(component: str) -> list[tuple[int, int, int]]:
    """Return the release tags published by a component repository.

    Public repositories are read anonymously; the token is used only when
    anonymous access fails, so a token scoped to the private repositories
    never breaks the public ones.
    """
    url = f"https://github.com/{ORGANIZATION}/{component}.git"
    result = _ls_remote(url, ["-c", "credential.helper="])
    auth = _git_auth_args()
    if result.returncode and auth:
        result = _ls_remote(url, auth)
    if result.returncode:
        # stderr never contains the token (it is sent as a header, not in the URL).
        reason = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        hint = "" if auth else " (if the repository is private, set RELEASE_TRAIN_TOKEN to a read-only token)"
        raise SystemExit(f"could not list tags for {component}{hint}: {reason}")
    versions = []
    for line in result.stdout.splitlines():
        match = TAG.search(line)
        if match:
            versions.append(tuple(int(part) for part in match.groups()))
    return versions  # type: ignore[return-value]


def conflicts(version: tuple[int, int, int], released: dict[str, list[tuple[int, int, int]]]) -> list[str]:
    """Describe every component whose newest release is ahead of ``version``."""
    problems = []
    for component, versions in released.items():
        newest = max(versions, default=None)
        if newest is not None and newest > version:
            problems.append(f"{component} already released v{'.'.join(map(str, newest))}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="Version to check (default: VERSION file)")
    args = parser.parse_args(argv)
    text = args.version or (ROOT / "VERSION").read_text(encoding="utf-8")
    version = parse(text)
    problems = conflicts(version, {c: released_versions(c) for c in COMPONENTS})
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(
            f"VERSION {text.strip()} is behind the release train. Choose a version newer than "
            "every released component; see docs/development/versioning.md."
        )
    print(f"Release train verified: v{text.strip()} is not behind any component release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
