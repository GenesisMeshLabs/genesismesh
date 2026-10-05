"""Which tags a released container image gets (v1.1).

    python scripts/image_tags.py 1.1.0 [--tags-from-git]

Prints one tag per line: ``X.Y.Z`` always; ``X.Y`` when no later patch of that
minor version is released; ``latest`` when no later stable version is
released. A re-published or backfilled older release therefore never moves a
floating tag backwards. Released versions come from the repository's
``vX.Y.Z`` Git tags (fetch them first) or from stdin, one per line.
"""

from __future__ import annotations

import re
import subprocess
import sys

STABLE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse(version: str) -> tuple[int, int, int]:
    match = STABLE.match(version.strip())
    if not match:
        raise ValueError(f"not a stable X.Y.Z version: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def tags_for(version: str, released: list[str]) -> list[str]:
    current = parse(version)
    known = {parse(v) for v in released if STABLE.match(v.strip())} | {current}
    tags = [f"{current[0]}.{current[1]}.{current[2]}"]
    if current == max(v for v in known if v[:2] == current[:2]):
        tags.append(f"{current[0]}.{current[1]}")
    if current == max(known):
        tags.append("latest")
    return tags


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    if "--tags-from-git" in argv:
        released = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True,
                                  check=True).stdout.split()
    else:
        released = sys.stdin.read().split()
    for tag in tags_for(argv[0], released):
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
