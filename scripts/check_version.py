"""Validate the coordinated Genesis Mesh release version."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag to compare, with or without a v prefix")
    args = parser.parse_args()

    release_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    with (ROOT / "pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]

    init_text = (ROOT / "genesis_mesh" / "__init__.py").read_text(encoding="utf-8")
    fallback_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    fallback_version = fallback_match.group(1) if fallback_match else None

    versions = {
        "VERSION": release_version,
        "pyproject.toml": package_version,
        "source fallback": fallback_version,
    }
    if len(set(versions.values())) != 1:
        for source, version in versions.items():
            print(f"{source}: {version}")
        raise SystemExit("Genesis Mesh version sources do not match")

    if args.tag and args.tag.removeprefix("v") != release_version:
        raise SystemExit(
            f"release tag {args.tag!r} does not match package version {release_version!r}"
        )

    print(f"Genesis Mesh release version verified: {release_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
