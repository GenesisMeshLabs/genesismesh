"""Check the core's own version, and audit the other components nightly.

The default run is the core's own monotonic check, for pull requests and the
publish workflows: ``VERSION`` must not be behind a release the core has
already tagged, so a version number never means two different core releases.
It reads only this repository's tags; a component's release can never turn
the core's CI red.

``--audit-ceiling`` is the cross-component ceiling, run nightly, never on pull
requests. A component follows the core: its newest release may not be of a
newer major.minor than the core's latest release, because a component release
pins a released contract bundle, and bundles are core releases. Patch numbers
are each component's own. The Rust verifier and edge streams have their own
tag prefixes and are not read. Every component listed here follows the core;
an ``own-major`` component (ops/plan-contract-bundle.md, C1) would need its
``supports`` range instead, and the compatibility table (C4) takes this audit
over once it exists.

Component repositories run their own check against their pinned bundle
(docs/development/versioning.md).
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
CORE = "genesismesh"
COMPONENTS = ("sdk-typescript", "sdk-go", "sdk-dotnet", "sdk-rust", "gateway")
TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def parse(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise SystemExit(f"not a release version: {version!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


#: Clear credential helpers and any stored auth header (actions/checkout stores
#: one); an empty extraheader value resets git's header list.
_NO_AUTH = ["-c", "credential.helper=", "-c", "http.https://github.com/.extraheader="]


def _git_auth_args() -> list[str]:
    """Git options that authenticate with RELEASE_TRAIN_TOKEN, if set.

    Private component repositories need a read-only token. It is sent as an
    HTTP header, never in the URL, so it cannot appear in error output.
    """
    token = os.environ.get("RELEASE_TRAIN_TOKEN", "").strip()
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return [*_NO_AUTH, "-c", f"http.https://github.com/.extraheader=Authorization: Basic {basic}"]


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
    result = _ls_remote(url, _NO_AUTH)
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


def behind(version: tuple[int, int, int], core_released: list[tuple[int, int, int]]) -> str | None:
    """Describe the core release ``version`` is behind, or return None."""
    newest = max(core_released, default=None)
    if newest is not None and newest > version:
        return f"{CORE} already released v{_text(newest)}"
    return None


def ceiling_breaches(
    core_released: list[tuple[int, int, int]], released: dict[str, list[tuple[int, int, int]]],
) -> list[str]:
    """Describe every component whose newest release is above the core's major.minor."""
    core = max(core_released, default=None)
    if core is None:
        raise SystemExit(f"{CORE} has no release tags to audit against")
    problems = []
    for component, versions in released.items():
        newest = max(versions, default=None)
        if newest is not None and newest[:2] > core[:2]:
            problems.append(
                f"{component} released v{_text(newest)}, above the core's latest release v{_text(core)}"
            )
    return problems


def _text(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def check_core(text: str) -> int:
    version = parse(text)
    problem = behind(version, released_versions(CORE))
    if problem:
        print(problem)
        raise SystemExit(
            f"VERSION {text.strip()} is behind the core's own releases: the next core version "
            "must be newer than its latest tag; see docs/development/versioning.md."
        )
    print(f"Core version verified: v{text.strip()} is not behind any core release")
    return 0


def audit_ceiling() -> int:
    core_released = released_versions(CORE)
    problems = ceiling_breaches(core_released, {c: released_versions(c) for c in COMPONENTS})
    core = _text(max(core_released))
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(
            f"A component released above the core's latest release v{core}. A component release "
            "pins a released bundle; see docs/development/versioning.md."
        )
    print(f"Ceiling verified: no component released above the core's latest release v{core}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--version", help="Version to check (default: VERSION file)")
    group.add_argument(
        "--audit-ceiling", action="store_true",
        help="Audit every component's newest release against the core's latest release (nightly)",
    )
    args = parser.parse_args(argv)
    if args.audit_ceiling:
        return audit_ceiling()
    return check_core(args.version or (ROOT / "VERSION").read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
