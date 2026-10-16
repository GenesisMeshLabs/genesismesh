"""Upgrade-note fragments: feature PRs never add a section to upgrade.md.

docs/operations/upgrade.md has one "## Upgrading to <version>" section per
release, and nearly every feature used to append to the next one, so
parallel features conflicted there. A change now records its notes as a
fragment, ``upgrade.d/<version>/<name>.md``: Markdown written as part of
that section (paragraphs, bullets, ``###`` subsections), for the version it
ships in. The release PR folds the version's fragments into one section,
above the newest one, and removes them.

    python scripts/upgrade_notes.py check
    python scripts/upgrade_notes.py preview 1.8.0
    python scripts/upgrade_notes.py release 1.8.0

``check`` validates every fragment, refuses one for a version already
released (``VERSION``) or outside ``upgrade.d/<version>/``, and refuses an
"Upgrading to" section in upgrade.md for a version newer than ``VERSION``
(that section is written by ``release``, in the release PR that bumps
``VERSION``). ``release`` names the section "Upgrading to X.Y" for X.Y.0 and
"Upgrading to X.Y.Z" for a patch, as the page always has, and refuses a
version the page already has. A sibling of scripts/changelog.py, which is
shared verbatim by every repository; this one is the core's only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = ROOT / "upgrade.d"
PAGE = ROOT / "docs" / "operations" / "upgrade.md"
VERSION_DIR = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")
NOT_FRAGMENTS = ("README.md",)
SECTION = re.compile(r"^## Upgrading to ([0-9]+)\.([0-9]+)(?:\.([0-9]+))?\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
BULLET = re.compile(r"^[-*+] ")


def _version(text: str) -> tuple[int, int, int]:
    match = VERSION_DIR.match(text)
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return int(match[1]), int(match[2]), int(match[3])


def _current() -> tuple[int, int, int]:
    return _version((ROOT / "VERSION").read_text(encoding="utf-8").strip())


def _label(version: str) -> str:
    major, minor, patch = _version(version)
    return f"{major}.{minor}" if patch == 0 else f"{major}.{minor}.{patch}"


def _parse(path: Path) -> str:
    """A fragment's Markdown. Raises ValueError when malformed."""
    rel = path.relative_to(ROOT).as_posix()
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{rel}: starts with a byte order mark; save it as UTF-8 without one")
    try:
        text = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise ValueError(f"{rel}: is not UTF-8") from None
    fence = ""
    for line in text.split("\n"):
        opening = FENCE.match(line)
        if fence:
            if opening and opening[1][0] == fence[0] and len(opening[1]) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = ""
        elif opening:
            fence = opening[1]
        elif re.match(r"^#{1,2}(\s|$)", line):
            raise ValueError(f"{rel}: the section heading comes from the release; use '### ' for a "
                             f"subsection: {line!r}")
        elif re.match(r"^#{1,6}[A-Za-z]", line):
            raise ValueError(f"{rel}: a heading needs a space after its '#': {line!r}")
    if fence:
        raise ValueError(f"{rel}: a code block is not closed")
    body = text.strip("\n")
    if not body.strip():
        raise ValueError(f"{rel}: is empty")
    return body


def _fragments(version: str) -> list[Path]:
    folder = FRAGMENTS / version
    return sorted(path for path in folder.glob("*") if path.is_file()) if folder.is_dir() else []


def _sections(text: str) -> list[tuple[int, int, int]]:
    found = []
    for line in text.replace("\r\n", "\n").split("\n"):
        match = SECTION.match(line)
        if match:
            found.append((int(match[1]), int(match[2]), int(match[3] or 0)))
    return found


def check() -> list[str]:
    problems: list[str] = []
    current = _current()
    if FRAGMENTS.is_dir():
        for path in sorted(FRAGMENTS.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_dir():
                if path.parent != FRAGMENTS or not VERSION_DIR.match(path.name):
                    problems.append(f"{rel}: notes go in upgrade.d/<version>/ (a version like 1.8.0)")
                continue
            if path.parent == FRAGMENTS:
                if path.name not in NOT_FRAGMENTS and not path.name.startswith("."):
                    problems.append(f"{rel}: a fragment goes in upgrade.d/<version>/, or it is never released")
                continue
            if not VERSION_DIR.match(path.parent.name) or path.parent.parent != FRAGMENTS:
                continue  # its directory is reported above
            if not NAME.match(path.name):
                problems.append(f"{rel}: name fragments like 'short-name.md' (lower case)")
                continue
            try:
                if _version(path.parent.name) <= current:
                    problems.append(f"{rel}: version {path.parent.name} is released ({'.'.join(map(str, current))}); "
                                    "move the notes to the next version")
                _parse(path)
            except ValueError as exc:
                problems.append(str(exc))
    for section in _sections(PAGE.read_text(encoding="utf-8")):
        if section > current:
            problems.append(f"{PAGE.relative_to(ROOT).as_posix()}: 'Upgrading to "
                            f"{_label('.'.join(map(str, section)))}' is for an unreleased version; write "
                            "upgrade.d/<version>/<name>.md instead (see upgrade.d/README.md)")
    return problems


def _ends_in_list(text: str) -> bool:
    lines = text.rstrip().split("\n")
    i = len(lines) - 1
    while i >= 0 and (not lines[i].strip() or lines[i][:1].isspace()):
        i -= 1
    while i >= 0 and lines[i].strip():
        if BULLET.match(lines[i]):
            return True
        i -= 1
    return False


def assemble(version: str) -> str:
    """The version's fragments in name order; bullet lists from two fragments read as one list."""
    out = ""
    for path in _fragments(version):
        part = _parse(path)
        if not out:
            out = part
        else:
            tight = _ends_in_list(out) and bool(BULLET.match(part.lstrip("\n")))
            out += ("\n" if tight else "\n\n") + part
    return out


def release(version: str) -> None:
    if not VERSION_DIR.match(version):
        raise SystemExit(f"not a version: {version!r}")
    text = PAGE.read_text(encoding="utf-8").replace("\r\n", "\n")
    if _version(version) in _sections(text):
        raise SystemExit(f"{PAGE.name} already has 'Upgrading to {_label(version)}'")
    body = assemble(version)
    if not body:
        raise SystemExit(f"no fragments for {version} in upgrade.d/{version}/")
    lines = text.split("\n")
    at = next((i for i, line in enumerate(lines) if SECTION.match(line)), None)
    if at is None:
        at = next((i for i, line in enumerate(lines) if line.startswith("## Rollback")), len(lines))
    lines[at:at] = [*f"## Upgrading to {_label(version)}\n\n{body}".split("\n"), ""]
    PAGE.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    for path in _fragments(version):
        path.unlink()
    (FRAGMENTS / version).rmdir()
    print(f"{PAGE.name}: 'Upgrading to {_label(version)}' ({len(body.splitlines())} lines); upgrade.d/{version}/ removed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate fragments; refuse upgrade.md sections for unreleased versions")
    p = sub.add_parser("preview", help="print a version's section body as release would write it")
    p.add_argument("version")
    r = sub.add_parser("release", help="fold a version's fragments into upgrade.md (release PRs)")
    r.add_argument("version")
    args = parser.parse_args()
    if args.command == "check":
        problems = check()
        for problem in problems:
            print(f"::error::{problem}" if "GITHUB_ACTIONS" in os.environ else problem)
        if not problems:
            print("upgrade notes OK")
        return 1 if problems else 0
    if args.command == "preview":
        print(assemble(args.version))
        return 0
    release(args.version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
