"""Changelog fragments: feature PRs never edit CHANGELOG.md.

A change records its entry as a fragment, ``changelog.d/<version>/<name>.md``:
Markdown under ``### <Section>`` headings (Added, Changed, Fixed, Security,
Upgrading, ...), for the version it ships in. Only a release PR (a branch
named ``release/...``) changes CHANGELOG.md: it folds that version's
fragments into one section and removes them. So a feature PR for the next
version never conflicts with the release PR of the current one, nor with
another feature PR.

    python scripts/changelog.py check [--base origin/main] [--branch NAME]
    python scripts/changelog.py preview 1.3.0
    python scripts/changelog.py release 1.3.0 --heading "## [1.3.0] - 2026-10-11"

``check`` validates every fragment, refuses one for a version already
released (``VERSION``), and with ``--base`` refuses lines a non-release
branch adds to CHANGELOG.md (removing lines is allowed). The same file is
shipped in every Genesis Mesh repository.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_DIR = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")
SECTION = re.compile(r"^### (\S.*)$")


def _version(text: str) -> tuple[int, int, int]:
    match = VERSION_DIR.match(text)
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return int(match[1]), int(match[2]), int(match[3])


def _current() -> tuple[int, int, int]:
    return _version((ROOT / "VERSION").read_text(encoding="utf-8").strip())


def _parse(path: Path) -> list[tuple[str, str]]:
    """A fragment as (section, body) pairs, in order. Raises ValueError when malformed."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    sections: list[tuple[str, list[str]]] = []
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        heading = None if fenced else SECTION.match(line)
        if heading:
            sections.append((heading[1].strip(), []))
        elif not fenced and re.match(r"^#{1,6} ", line):
            raise ValueError(f"{path.relative_to(ROOT)}: only '### Section' headings belong in a fragment: {line!r}")
        elif sections:
            sections[-1][1].append(line)
        elif line.strip():
            raise ValueError(f"{path.relative_to(ROOT)}: text before the first '### Section' heading")
    out = [(name, "\n".join(body).strip("\n")) for name, body in sections]
    if not out or any(not body for _, body in out):
        raise ValueError(f"{path.relative_to(ROOT)}: every '### Section' needs an entry")
    return out


def _fragments(version: str | None = None) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    if not FRAGMENTS.is_dir():
        return found
    for path in sorted(FRAGMENTS.rglob("*")):
        if path.is_dir() or path.parent == FRAGMENTS:
            continue  # changelog.d/README.md and the like
        found.setdefault(path.parent.name, []).append(path)
    return {version: found.get(version, [])} if version else found


def check(base: str | None, branch: str | None) -> list[str]:
    problems: list[str] = []
    current = _current()
    if FRAGMENTS.is_dir():
        for path in sorted(FRAGMENTS.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_dir():
                if path.parent != FRAGMENTS or not VERSION_DIR.match(path.name):
                    problems.append(f"{rel}: fragments go in changelog.d/<version>/")
                continue
            if path.parent == FRAGMENTS:
                continue
            if not NAME.match(path.name):
                problems.append(f"{rel}: name fragments like 'short-name.md' (lower case)")
                continue
            try:
                if _version(path.parent.name) <= current:
                    problems.append(f"{rel}: version {path.parent.name} is released ({'.'.join(map(str, current))}); "
                                    "move the entry to the next version")
                _parse(path)
            except ValueError as exc:
                problems.append(str(exc))
    if base and not (branch or "").startswith("release/"):
        diff = subprocess.run(
            ["git", "diff", "--unified=0", f"{base}...HEAD", "--", "CHANGELOG.md"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
        if added:
            problems.append("CHANGELOG.md gains lines outside a release PR: add the entry as "
                            "changelog.d/<version>/<name>.md instead (see changelog.d/README.md)")
    return problems


def assemble(version: str) -> str:
    """The version's fragments as one section body, sections in order of first appearance."""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    for path in _fragments(version)[version]:
        for name, body in _parse(path):
            if name not in bodies:
                order.append(name)
                bodies[name] = []
            bodies[name].append(body)
    def join(parts: list[str]) -> str:
        # Bullet lists from two fragments read as one list; other text stays in paragraphs.
        out = parts[0]
        for part in parts[1:]:
            tight = out.rstrip().split("\n")[-1].lstrip().startswith(("- ", "* ")) and part.lstrip().startswith(("- ", "* "))
            out += ("\n" if tight else "\n\n") + part
        return out

    return "\n\n".join(f"### {name}\n\n" + join(bodies[name]) for name in order)


def release(version: str, heading: str) -> None:
    body = assemble(version)
    if not body:
        raise SystemExit(f"no fragments for {version} in changelog.d/{version}/")
    if not heading.startswith("## "):
        raise SystemExit("the heading must start with '## '")
    text = CHANGELOG.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    at = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    lines[at:at] = [*f"{heading}\n\n{body}".split("\n"), ""]
    CHANGELOG.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    for path in _fragments(version)[version]:
        path.unlink()
    (FRAGMENTS / version).rmdir()
    print(f"CHANGELOG.md: {heading} ({len(body.splitlines())} lines); changelog.d/{version}/ removed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="validate fragments; refuse CHANGELOG.md additions outside release PRs")
    c.add_argument("--base", help="the branch the PR merges into, e.g. origin/main")
    c.add_argument("--branch", help="the PR's branch (release/... may edit CHANGELOG.md)")
    p = sub.add_parser("preview", help="print a version's section as release would write it")
    p.add_argument("version")
    r = sub.add_parser("release", help="fold a version's fragments into CHANGELOG.md (release PRs)")
    r.add_argument("version")
    r.add_argument("--heading", required=True)
    args = parser.parse_args()
    if args.command == "check":
        problems = check(args.base, args.branch)
        for problem in problems:
            print(f"::error::{problem}" if "GITHUB_ACTIONS" in os.environ else problem)
        if not problems:
            print("changelog fragments OK")
        return 1 if problems else 0
    if args.command == "preview":
        print(assemble(args.version))
        return 0
    release(args.version, args.heading)
    return 0


if __name__ == "__main__":
    sys.exit(main())
