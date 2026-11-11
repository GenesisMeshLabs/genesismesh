"""The consumer releases the core's CI runs against (``contract/consumer-pins.json``).

    python scripts/consumer_pins.py check             # the file's form
    python scripts/consumer_pins.py env --verify      # SDK_GO_REF=... lines, each ref checked on GitHub

From 1.11.0 the core's CI no longer picks SDK branches by name. The
Interoperability run checks out each SDK at the ref pinned here: a release
tag (``vX.Y.Z``) or a commit on that repository's ``main`` (40 hex). A core
change that needs newer SDK behaviour pins the SDK's ``main`` commit that has
it, in the same pull request; a later SDK release replaces the commit with its
tag. So a core pull request is tested against the same SDK code in its own
run, in the merge queue and on ``main``, whatever merges elsewhere.

``--verify`` asks GitHub that each tag exists and each commit is on ``main``
(the compare API: ``main`` is ahead of it or identical). A token in
``GITHUB_TOKEN`` is sent only to ``api.github.com``. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "contract" / "consumer-pins.json"
SCHEMA = "gm.consumer-pins/1"
ORGANIZATION = "GenesisMeshLabs"
#: The pinned repositories and the environment variable each ref goes to.
CONSUMERS = {
    "sdk-dotnet": "SDK_DOTNET_REF",
    "sdk-go": "SDK_GO_REF",
    "sdk-typescript": "SDK_TS_REF",
}
TAG = re.compile(r"v\d+\.\d+\.\d+")
COMMIT = re.compile(r"[0-9a-f]{40}")


class PinError(Exception):
    pass


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise PinError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def load(path: Path | None = None) -> dict[str, str]:
    """The pinned ref of each consumer, after checking the file's form."""
    path = PINS if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, ValueError) as exc:
        raise PinError(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise PinError(f"{path.name}: schema must be {SCHEMA!r}")
    names = set(data) - {"schema"}
    if names != set(CONSUMERS):
        raise PinError(f"{path.name}: consumers {sorted(names)}, expected {sorted(CONSUMERS)}")
    refs = {}
    for name in sorted(CONSUMERS):
        entry = data[name]
        if not isinstance(entry, dict) or set(entry) != {"ref"} or not isinstance(entry["ref"], str):
            raise PinError(f"{path.name}: {name} must be {{\"ref\": \"...\"}}")
        ref = entry["ref"]
        if not (TAG.fullmatch(ref) or COMMIT.fullmatch(ref)):
            raise PinError(f"{path.name}: {name} ref {ref!r} is neither a release tag vX.Y.Z nor a 40-hex commit")
        refs[name] = ref
    return refs


def _github(path: str) -> object:
    request = urllib.request.Request(f"https://api.github.com{path}",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "genesis-mesh-consumer-pins"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def verify(name: str, ref: str, github=_github) -> None:
    """Fails unless the tag exists, or the commit is on ``main``."""
    repo = f"/repos/{ORGANIZATION}/{name}"
    try:
        if TAG.fullmatch(ref):
            github(f"{repo}/git/ref/tags/{ref}")
            return
        status = github(f"{repo}/compare/{ref}...main")
    except urllib.error.HTTPError as exc:
        raise PinError(f"{name}: {ref} not found on GitHub ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise PinError(f"{name}: could not check {ref}: {exc}") from exc
    if not isinstance(status, dict) or status.get("status") not in ("ahead", "identical"):
        found = status.get("status") if isinstance(status, dict) else status
        raise PinError(f"{name}: commit {ref} is not on main (compare status {found!r})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check the file's form")
    env = sub.add_parser("env", help="print NAME=ref lines for $GITHUB_ENV")
    env.add_argument("--verify", action="store_true", help="check each ref on GitHub")
    args = parser.parse_args(argv)
    try:
        refs = load()
        if args.command == "env":
            for name, ref in refs.items():
                if args.verify:
                    verify(name, ref)
                print(f"{CONSUMERS[name]}={ref}")
        else:
            print(", ".join(f"{name} {ref}" for name, ref in refs.items()))
    except PinError as exc:
        print(f"consumer pins: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
