"""Validate the coordinated Genesis Mesh release version.

``VERSION`` is the release version. The package metadata and every file in
``SITES`` that states the current release must name it: the check (pre-commit,
CI and the publish workflows) fails when one lags, so a release cannot leave a
stale install command or image tag behind. Historical mentions ("from 1.7.0",
"Upgrading to 1.8.1") are not sites and never change.

    python scripts/check_version.py                 # check
    python scripts/check_version.py --tag v1.9.0    # check, and compare a release tag
    python scripts/check_version.py --set 1.9.0     # write the version everywhere (release PRs)

A new statement of the current release (a page that shows an install command
with the version, an image tag in a deployment example) belongs in ``SITES``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"(\d+\.\d+\.\d+)"
IMAGE = rf"ghcr\.io/genesismeshlabs/genesis-mesh(?:-gateway|-edge)?:{NUMBER}"

#: (file, pattern, count): ``count`` statements of the current release, the
#: version in each match's first group. A count that no longer matches means a
#: statement was added, reworded or removed: update this table with it.
SITES: tuple[tuple[str, str, int], ...] = (
    ("pyproject.toml", rf'(?m)^version = "{NUMBER}"', 1),
    ("genesis_mesh/__init__.py", rf'__version__ = "{NUMBER}"', 1),
    ("README.md", rf"current release line \({NUMBER} today\)", 1),
    ("docs/concepts/rust-gateway.md", rf"at the same version \({NUMBER}\s+today\)", 1),
    ("docs/sdk/index.md", rf"Version {NUMBER} is the coordinated source version", 1),
    ("docs/sdk/index.md", rf"\| {NUMBER} \| `GenesisMeshLabs/(?:sdk-[a-z]+|gateway)` \|", 5),
    ("docs/installation.md", IMAGE, 4),
    ("deploy/compose/docker-compose.images.yml", IMAGE, 4),
    ("deploy/kubernetes/na-deployment.yaml", IMAGE, 1),
    ("docs/examples/assets/github-actions/supply-chain-trust-gate.yml", rf"genesis-mesh=={NUMBER}", 1),
)


def _read(path: Path) -> str:
    # newline="" keeps the file's own line endings when it is written back.
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def release_version(root: Path) -> str:
    version = _read(root / "VERSION").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"VERSION is not a release version: {version!r}")
    return version


def problems(root: Path) -> list[str]:
    """Every site that does not name ``VERSION``, or no longer has its statements."""
    version = release_version(root)
    found = []
    for name, pattern, count in SITES:
        matches = list(re.finditer(pattern, _read(root / name)))
        if len(matches) != count:
            found.append(f"{name}: expected {count} statement(s) of the release, found {len(matches)} "
                         "(update SITES in scripts/check_version.py with the change)")
        found += [f"{name}: {m.group(1)} where VERSION is {version}" for m in matches if m.group(1) != version]
    return found


def set_version(root: Path, version: str) -> None:
    """Write ``version`` to VERSION and every site."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"not a release version: {version!r}")

    def replace(match: re.Match[str]) -> str:
        start, end = match.span(1)
        return match.group(0)[: start - match.start()] + version + match.group(0)[end - match.start():]

    _write(root / "VERSION", version + "\n")
    for name in dict.fromkeys(site[0] for site in SITES):
        path = root / name
        text = _read(path)
        for site, pattern, _ in SITES:
            if site == name:
                text = re.sub(pattern, replace, text)
        _write(path, text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag to compare, with or without a v prefix")
    parser.add_argument("--set", metavar="VERSION", help="Write this version to VERSION and every site")
    args = parser.parse_args()

    if args.set:
        set_version(ROOT, args.set.removeprefix("v"))
    found = problems(ROOT)
    if found:
        for problem in found:
            print(problem)
        raise SystemExit("Genesis Mesh version sources do not match")

    version = release_version(ROOT)
    if args.tag and args.tag.removeprefix("v") != version:
        raise SystemExit(f"release tag {args.tag!r} does not match package version {version!r}")
    print(f"Genesis Mesh release version verified: {version} ({len(SITES)} sites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
