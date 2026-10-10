"""Changelog fragments: feature PRs never edit CHANGELOG.md.

A change records its entry as a fragment, ``changelog.d/<version>/<name>.md``:
Markdown under ``### <Section>`` headings (Added, Changed, Fixed, Security,
Upgrading, ...), for the version it ships in. Only a release PR (a branch
named ``release/<version>``) changes CHANGELOG.md: it folds that version's
fragments into one section and removes them. So a feature PR for the next
version never conflicts with the release PR of the current one, nor with
another feature PR.

    python scripts/changelog.py check [--base origin/main] [--branch NAME]
    python scripts/changelog.py preview 1.3.0
    python scripts/changelog.py release 1.3.0 --heading "## [1.3.0] - 2026-10-11"

``check`` validates every fragment, refuses one for a version already
released (``VERSION``) or outside ``changelog.d/<version>/``, and with
``--base`` refuses any change a branch other than ``release/<version>``
makes to CHANGELOG.md. ``release`` writes the sections in a fixed order
(``SECTION_ORDER``, then any other section in order of first appearance,
then Upgrading) and refuses a version CHANGELOG.md already has. The same
file is shipped in every Genesis Mesh repository.
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
#: A version without leading zeros: ``01.4.0`` would name no version the fold looks for.
VERSION_DIR = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
RELEASE_BRANCH = re.compile(r"^release/(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")
SECTION = re.compile(r"^### (\S.*)$")
#: Files changelog.d/ itself may hold; a fragment there would never be folded.
NOT_FRAGMENTS = ("README.md",)
#: Sections in the order a release writes them; others follow Fixed, Upgrading comes last.
SECTION_ORDER = ("Security", "Added", "Changed", "Deprecated", "Removed", "Fixed")
LAST_SECTION = "Upgrading"
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
BULLET = re.compile(r"^[-*+] ")


def _version(text: str) -> tuple[int, int, int]:
    match = VERSION_DIR.match(text)
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return int(match[1]), int(match[2]), int(match[3])


def _current() -> tuple[int, int, int]:
    return _version((ROOT / "VERSION").read_text(encoding="utf-8").strip())


def _parse(path: Path) -> list[tuple[str, str]]:
    """A fragment as (section, body) pairs, in order. Raises ValueError when malformed."""
    rel = path.relative_to(ROOT).as_posix()
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{rel}: starts with a byte order mark; save it as UTF-8 without one")
    try:
        text = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise ValueError(f"{rel}: is not UTF-8") from None
    sections: list[tuple[str, list[str]]] = []
    fence = ""
    for line in text.split("\n"):
        opening = FENCE.match(line)
        if fence:
            if opening and opening[1][0] == fence[0] and len(opening[1]) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = ""
            elif re.match(r"^##( |$)", line):
                # The release notes of a version end at its next '## ' line, fenced or not.
                raise ValueError(f"{rel}: a line in a code block starts with '## ', which would end the "
                                 f"version's release notes: {line!r}")
        elif opening:
            fence = opening[1]
        heading = None if fence else SECTION.match(line)
        if heading:
            sections.append((heading[1].strip(), []))
            continue
        if not fence and re.match(r"^\s*#{1,6}(\s|$)", line):
            raise ValueError(f"{rel}: only '### Section' headings, at the start of a line, belong in a "
                             f"fragment: {line!r}")
        if not fence and re.match(r"^#{1,6}[A-Za-z]", line):
            raise ValueError(f"{rel}: a heading needs a space after its '#': {line!r}")
        if sections:
            sections[-1][1].append(line)
        elif line.strip():
            raise ValueError(f"{rel}: text before the first '### Section' heading")
    if fence:
        raise ValueError(f"{rel}: a code block is not closed")
    out = [(name, "\n".join(body).strip("\n")) for name, body in sections]
    if not out or any(not body for _, body in out):
        raise ValueError(f"{rel}: every '### Section' needs an entry")
    return out


def _fragments(version: str | None = None) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    if not FRAGMENTS.is_dir():
        return found
    for path in sorted(FRAGMENTS.rglob("*")):
        if path.is_dir() or path.parent == FRAGMENTS:
            continue  # changelog.d/README.md; check refuses anything else there
        found.setdefault(path.parent.name, []).append(path)
    return {version: found.get(version, [])} if version else found


def _changelog_changed(base: str) -> bool:
    done = subprocess.run(
        ["git", "diff", "--quiet", f"{base}...HEAD", "--", "CHANGELOG.md"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if done.returncode not in (0, 1):
        raise SystemExit(f"git diff failed: {done.stderr.strip()}")
    return done.returncode == 1


def check(base: str | None, branch: str | None) -> list[str]:
    problems: list[str] = []
    current = _current()
    if FRAGMENTS.is_dir():
        for path in sorted(FRAGMENTS.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_dir():
                if path.parent != FRAGMENTS or not VERSION_DIR.match(path.name):
                    problems.append(f"{rel}: fragments go in changelog.d/<version>/ (a version like 1.3.0)")
                continue
            if path.parent == FRAGMENTS:
                if path.name not in NOT_FRAGMENTS and not path.name.startswith("."):
                    problems.append(f"{rel}: a fragment goes in changelog.d/<version>/, or it is never released")
                continue
            if not VERSION_DIR.match(path.parent.name) or path.parent.parent != FRAGMENTS:
                continue  # its directory is reported above
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
    if base and not RELEASE_BRANCH.match(branch or "") and _changelog_changed(base):
        problems.append("CHANGELOG.md changes outside a release PR (a branch named release/<version>): add the "
                        "entry as changelog.d/<version>/<name>.md instead (see changelog.d/README.md)")
    return problems


def _ends_in_list(text: str) -> bool:
    """True when Markdown text ends inside a bullet list (its last item may wrap or hold paragraphs)."""
    lines = text.rstrip().split("\n")
    i = len(lines) - 1
    while i >= 0 and (not lines[i].strip() or lines[i][:1].isspace()):
        i -= 1  # the last item's indented lines, and blank lines between them
    while i >= 0 and lines[i].strip():
        if BULLET.match(lines[i]):
            return True
        i -= 1  # an unindented line continuing the item above
    return False


def assemble(version: str) -> str:
    """The version's fragments as one section body, sections in their fixed order."""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    for path in _fragments(version)[version]:
        for name, body in _parse(path):
            if name not in bodies:
                order.append(name)
                bodies[name] = []
            bodies[name].append(body)
    # Known sections in their fixed order, then the others as they first appear, then Upgrading.
    rank = {name: i for i, name in enumerate(SECTION_ORDER)}
    rank.update({name: len(SECTION_ORDER) + i for i, name in enumerate(order) if name not in rank})
    rank[LAST_SECTION] = len(SECTION_ORDER) + len(order)
    order = sorted(order, key=rank.__getitem__)

    def join(parts: list[str]) -> str:
        # Bullet lists from two fragments read as one list; other text stays in paragraphs.
        out = parts[0]
        for part in parts[1:]:
            tight = _ends_in_list(out) and bool(BULLET.match(part.lstrip("\n")))
            out += ("\n" if tight else "\n\n") + part
        return out

    return "\n\n".join(f"### {name}\n\n" + join(bodies[name]) for name in order)


def _names_version(line: str, version: str) -> bool:
    """True when ``line`` is a version heading for ``version`` (``## v1.3.0 - ...``, ``## [1.3.0] - ...``)."""
    return line.startswith("## ") and any(
        token.rstrip(".") in (version, f"v{version}") for token in re.findall(r"[0-9A-Za-z][0-9A-Za-z.+-]*", line)
    )


def release(version: str, heading: str) -> None:
    if not VERSION_DIR.match(version):
        raise SystemExit(f"not a version: {version!r}")
    if not heading.startswith("## ") or "\n" in heading:
        raise SystemExit("the heading must be one line starting with '## '")
    if not _names_version(heading, version):
        raise SystemExit(f"the heading must name version {version}: {heading!r}")
    text = CHANGELOG.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    existing = next((line for line in lines if _names_version(line, version)), None)
    if existing is not None:
        raise SystemExit(f"CHANGELOG.md already has {version}: {existing!r}")
    body = assemble(version)
    if not body:
        raise SystemExit(f"no fragments for {version} in changelog.d/{version}/")
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
    c = sub.add_parser("check", help="validate fragments; refuse CHANGELOG.md changes outside release PRs")
    c.add_argument("--base", help="the branch the PR merges into, e.g. origin/main")
    c.add_argument("--branch", help="the PR's branch (release/<version> may edit CHANGELOG.md)")
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
