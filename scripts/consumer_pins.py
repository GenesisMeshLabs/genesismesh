"""The SDK and gateway revisions the core's CI runs against (``contract/consumer-pins.json``).

    python scripts/consumer_pins.py check     # the file's form, offline
    python scripts/consumer_pins.py env       # SDK_GO_REF=<commit> lines, each pin resolved on GitHub
    python scripts/consumer_pins.py gateway   # GATEWAY_IMAGE=<image@digest> and its expected version,
                                              # revision and signing identity

From 1.11.0 the core's CI no longer picks SDK or gateway branches by name. The
Interoperability run checks out each SDK at the revision pinned here: a
release tag (``vX.Y.Z``) or a commit on that repository's ``main`` (40 hex).
A core change that needs newer SDK behaviour pins the SDK's ``main`` commit
that has it, in the same pull request; a later SDK release replaces the
commit with its tag. So a core pull request is tested against the same SDK
code in its own run, in the merge queue and on ``main``, whatever merges
elsewhere.

``env`` resolves every pin on GitHub to the commit it names and prints that
commit, never a name: a branch called like a tag cannot stand in for it. A
tag must exist; a commit must be on ``main`` (the compare API answers
``ahead`` or ``identical`` for ``<commit>...main``). Anything else, including
GitHub being unreachable or refusing the request, fails. A token in
``GITHUB_TOKEN`` is sent to ``api.github.com`` only, never on a redirect.

The container jobs (``ci.yml`` and ``publish-image.yml``) test the Network
Authority with the gateway release pinned here, never one built from a branch
or from ``main``. The gateway is pinned to a release tag and its published
image index digest, since only releases have images. ``gateway`` resolves the
tag to its commit and prints the image by digest, the version and revision its
labels and binary must report, and the identity its cosign signature must
carry: the gateway's ``distribution.yml`` at that tag. A core change that
needs newer gateway behaviour waits for a gateway release and pins it.
Stdlib only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "contract" / "consumer-pins.json"
SCHEMA = "gm.consumer-pins/1"
ORGANIZATION = "GenesisMeshLabs"
API = "https://api.github.com"
#: The pinned repositories and the environment variable each commit goes to.
CONSUMERS = {
    "sdk-dotnet": "SDK_DOTNET_REF",
    "sdk-go": "SDK_GO_REF",
    "sdk-rust": "SDK_RUST_REF",
    "sdk-typescript": "SDK_TS_REF",
}
#: The gateway is pinned to a release and its image, signed by the gateway's own release workflow.
GATEWAY = "gateway"
GATEWAY_IMAGE = "ghcr.io/genesismeshlabs/genesis-mesh-gateway"
GATEWAY_WORKFLOW = ".github/workflows/distribution.yml"
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
COMMIT = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

GitHub = Callable[[str], object]


class PinError(Exception):
    pass


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise PinError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


class GatewayPin(NamedTuple):
    ref: str  #: the release tag, vX.Y.Z
    digest: str  #: the image index digest published for it, sha256:<64 hex>

    @property
    def version(self) -> str:
        return self.ref.removeprefix("v")

    @property
    def image(self) -> str:
        return f"{GATEWAY_IMAGE}@{self.digest}"

    @property
    def identity(self) -> str:
        return f"https://github.com/{ORGANIZATION}/{GATEWAY}/{GATEWAY_WORKFLOW}@refs/tags/{self.ref}"


def _read(path: Path | None) -> tuple[str, dict[str, object]]:
    """The file's name and its entries, after checking the schema and the set of names."""
    path = PINS if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, ValueError) as exc:
        raise PinError(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise PinError(f"{path.name}: schema must be {SCHEMA!r}")
    names = set(data) - {"schema"}
    expected = set(CONSUMERS) | {GATEWAY}
    if names != expected:
        raise PinError(f"{path.name}: consumers {sorted(names)}, expected {sorted(expected)}")
    return path.name, data


def load_gateway(path: Path | None = None) -> GatewayPin:
    """The pinned gateway release and image digest, after checking the whole file's form."""
    load(path)  # the SDK entries too: a file is valid as a whole or not at all
    file, data = _read(path)
    entry = data[GATEWAY]
    if (not isinstance(entry, dict) or set(entry) != {"ref", "image"}
            or not all(isinstance(value, str) for value in entry.values())):
        raise PinError(f"{file}: {GATEWAY} must be {{\"ref\": \"vX.Y.Z\", \"image\": \"sha256:...\"}}")
    if not TAG.fullmatch(entry["ref"]):
        raise PinError(f"{file}: {GATEWAY} ref {entry['ref']!r} is not a release tag vX.Y.Z "
                       "(only gateway releases have images)")
    if not DIGEST.fullmatch(entry["image"]):
        raise PinError(f"{file}: {GATEWAY} image {entry['image']!r} is not an image digest sha256:<64 hex>")
    return GatewayPin(entry["ref"], entry["image"])


def load(path: Path | None = None) -> dict[str, str]:
    """The pinned ref of each SDK, after checking the file's form."""
    file, data = _read(path)
    refs = {}
    for name in sorted(CONSUMERS):
        entry = data[name]
        if not isinstance(entry, dict) or set(entry) != {"ref"} or not isinstance(entry["ref"], str):
            raise PinError(f"{file}: {name} must be {{\"ref\": \"...\"}}")
        ref = entry["ref"]
        if not (TAG.fullmatch(ref) or COMMIT.fullmatch(ref)):
            raise PinError(f"{file}: {name} ref {ref!r} is neither a release tag vX.Y.Z nor a 40-hex commit")
        refs[name] = ref
    return refs


def github_api(path: str) -> object:
    """GET ``api.github.com<path>`` as JSON."""
    request = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/vnd.github+json",
                                                              "User-Agent": "genesis-mesh-consumer-pins"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        # Not copied onto a redirect, which could point at another host.
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _ask(github: GitHub, name: str, path: str, what: str) -> dict[str, object]:
    try:
        answer = github(path)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PinError(f"{name}: {what} not found on GitHub") from exc
        raise PinError(f"{name}: GitHub answered {exc.code} for {what} (rate limit or outage?)") from exc
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        raise PinError(f"{name}: could not check {what}: {exc}") from exc
    if not isinstance(answer, dict):
        raise PinError(f"{name}: unexpected answer for {what}: {answer!r}")
    return answer


def _sha(value: object) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("sha"), str) and COMMIT.fullmatch(value["sha"]):
        return value["sha"]
    return None


def resolve(name: str, ref: str, github: GitHub = github_api) -> str:
    """The commit ``ref`` names in ``name``: a tag's commit (annotated tags
    dereferenced), or the pinned commit once it is known to be on ``main``."""
    repo = f"/repos/{ORGANIZATION}/{name}"
    if TAG.fullmatch(ref):
        target = _ask(github, name, f"{repo}/git/ref/tags/{ref}", f"tag {ref}").get("object")
        # An annotated tag points at a tag object; follow it to the commit.
        for _ in range(3):
            if not isinstance(target, dict):
                break
            if target.get("type") == "commit" and _sha(target):
                return str(target["sha"])
            if target.get("type") != "tag" or not _sha(target):
                break
            target = _ask(github, name, f"{repo}/git/tags/{target['sha']}", f"tag {ref}").get("object")
        raise PinError(f"{name}: tag {ref} does not name a commit")
    status = _ask(github, name, f"{repo}/compare/{ref}...main?per_page=1", f"commit {ref}").get("status")
    if status not in ("ahead", "identical"):
        raise PinError(f"{name}: commit {ref} is not on main (compare status {status!r})")
    return ref


def main(argv: list[str] | None = None, github: GitHub = github_api) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check the file's form (offline)")
    sub.add_parser("env", help="print NAME=<commit> lines for $GITHUB_ENV, each SDK pin resolved on GitHub")
    sub.add_parser("gateway", help="print the pinned gateway image by digest and what it must report, "
                                   "for $GITHUB_ENV (its tag resolved on GitHub)")
    args = parser.parse_args(argv)
    try:
        refs = load()
        gateway = load_gateway()
        if args.command == "check":
            print(", ".join([f"{name} {ref}" for name, ref in refs.items()]
                            + [f"{GATEWAY} {gateway.ref} ({gateway.digest})"]))
            return 0
        if args.command == "gateway":
            revision = resolve(GATEWAY, gateway.ref, github)
            print(f"{GATEWAY}: {gateway.ref} is {revision}, image {gateway.digest}", file=sys.stderr)
            print(f"GATEWAY_IMAGE={gateway.image}")
            print(f"GATEWAY_VERSION={gateway.version}")
            print(f"GATEWAY_REVISION={revision}")
            print(f"GATEWAY_IDENTITY={gateway.identity}")
            return 0
        # Resolve all first: a failure prints no line at all.
        commits = {name: resolve(name, ref, github) for name, ref in refs.items()}
    except PinError as exc:
        print(f"consumer pins: {exc}", file=sys.stderr)
        return 1
    for name, commit in commits.items():
        print(f"{name}: {refs[name]} is {commit}", file=sys.stderr)
        print(f"{CONSUMERS[name]}={commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
