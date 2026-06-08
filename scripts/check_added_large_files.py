"""Fail when newly added files exceed the configured size limit."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _git_paths(*args: str) -> list[Path]:
    completed = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode(errors="replace").strip()
        if message:
            print(message, file=sys.stderr)
        return []

    raw_paths = completed.stdout.split(b"\0")
    return [Path(path.decode(errors="surrogateescape")) for path in raw_paths if path]


def _added_files_for_hook_stage() -> list[Path]:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")

    if from_ref and to_ref:
        return _git_paths("diff", "--name-only", "--diff-filter=A", "-z", from_ref, to_ref)

    return _git_paths("diff", "--cached", "--name-only", "--diff-filter=A", "-z")


def _size_kb(path: Path) -> float:
    return path.stat().st_size / 1024


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maxkb", type=int, default=500)
    args = parser.parse_args(argv)

    too_large: list[tuple[Path, float]] = []
    for path in _added_files_for_hook_stage():
        if not path.exists() or not path.is_file():
            continue

        size = _size_kb(path)
        if size > args.maxkb:
            too_large.append((path, size))

    if not too_large:
        return 0

    print(f"New files must not exceed {args.maxkb} KB:")
    for path, size in too_large:
        print(f"- {path} ({size:.1f} KB)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
