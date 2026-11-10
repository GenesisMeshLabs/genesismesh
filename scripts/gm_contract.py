"""The Genesis Mesh contract bundle tool (standard library only).

A contract bundle is the set of core files every SDK and the gateway are
tested against: the conformance vectors, the frozen audit pack, the public
surface, the record-kind table and this tool. ``contract/bundle.json`` says
which files belong to it and which suites and kinds each tier of consumer must
run. ``contract/MANIFEST.json`` is generated from it and committed: every
file with its hash, every suite with its kinds and the expanded requirements,
and a ``contract_digest`` that names the contract itself, so two releases
with the same contract are visibly the same.

Core commands (they refuse to run outside a core checkout):

    python scripts/gm_contract.py manifest            # write contract/MANIFEST.json
    python scripts/gm_contract.py manifest --check    # fail when it is stale or the spec is wrong
    python scripts/gm_contract.py archive --out DIR   # reproducible release archive + SHA256SUMS-contract

The consumer commands (sync, verify, receipt-check, release-check) follow in
the next change of ``ops/plan-v1.11.0-release-model.md``. Consumers vendor
this file byte for byte, so it must stay importable on Python 3.11 with the
standard library alone; ``manifest --check`` enforces that.

Exit codes: 0 ok, 1 check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

SPEC_PATH = "contract/bundle.json"
MANIFEST_PATH = "contract/MANIFEST.json"
TOOL_PATH = "scripts/gm_contract.py"
VECTORS_DIR = "conformance/vectors"
FIXTURES_DIR = "conformance/fixtures"
SPEC_SCHEMA = "gm.contract.spec/1"
MANIFEST_SCHEMA = "gm.contract.manifest/1"
#: The key a vector without a ``kind`` is counted under.
NO_KIND = "*"
#: Manifest keys left out of ``contract_digest``: the version labels, the digest itself and the
#: tool, so a release that changes only the tool or the version keeps its contract digest. Tiers
#: enter it by name only: rewording a tier's description does not change the contract.
UNDIGESTED = ("bundle_version", "core_version", "contract_digest", "tool")
SPEC_KEYS = frozenset({"schema", "include", "tiers", "suites"})
SUITE_KEYS = frozenset({"required", "na_only_kinds"})


class ContractError(Exception):
    """A spec, manifest or archive problem; the message is for the person running the tool."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: Any) -> bytes:
    """The canonical JSON the contract digest is taken over."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def render(data: Any) -> bytes:
    """The committed form of a generated JSON file: sorted keys, two-space indent, LF, final newline."""
    return (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def core_root(repo: Path) -> Path:
    """``repo`` when it is a core checkout; the core-only commands refuse anything else."""
    if not (repo / SPEC_PATH).is_file() or not (repo / "genesis_mesh").is_dir() or not (repo / "VERSION").is_file():
        raise ContractError(f"{repo} is not a Genesis Mesh core checkout (no {SPEC_PATH}, genesis_mesh/ or VERSION)")
    return repo


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    """Strict JSON: UTF-8, and a repeated key is an error, never "the last one wins"."""
    try:
        return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ContractError(f"{path}: cannot read JSON ({exc})") from exc


def core_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ContractError(f"VERSION is not a release version: {version!r}")
    return version


def candidate_files(root: Path) -> list[str] | None:
    """Files git tracks or would track (untracked, not ignored); None outside a git checkout.

    An ignored file (``__pycache__``, an editor backup) never enters the bundle, so a manifest
    written on a developer's machine equals the one a clean CI checkout computes.
    """
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [name for name in listed.decode("utf-8").split("\0") if name and (root / name).is_file()]


def _check_pattern(pattern: Any) -> str:
    """A relative POSIX pattern: ``*`` within one segment, or a trailing ``/**``; nothing else."""
    body = pattern.removesuffix("/**") if isinstance(pattern, str) else ""
    if (not body or "**" in body or "\\" in body or pattern.startswith("/")
            or any(part in ("", ".", "..") for part in body.split("/"))):
        raise ContractError(f"{SPEC_PATH}: include pattern {pattern!r} is not a relative path pattern")
    return pattern


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    if pattern.endswith("/**"):
        return re.compile(re.escape(pattern[:-3]) + "/.+")
    return re.compile("[^/]*".join(re.escape(part) for part in pattern.split("*")))


def expand(root: Path, patterns: list[Any]) -> list[str]:
    """The files the ``include`` patterns name, as sorted POSIX paths relative to ``root``.

    A pattern ending in ``/**`` names every file under that directory; otherwise ``*`` matches
    within one path segment. A pattern that matches nothing is an error, so a renamed file cannot
    drop out of the bundle unnoticed.
    """
    checked = [_check_pattern(p) for p in patterns]
    candidates = candidate_files(root)
    if candidates is None:
        candidates = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    found: set[str] = set()
    for pattern in checked:
        regex = _pattern_regex(pattern)
        matches = [name for name in candidates if regex.fullmatch(name)]
        if not matches:
            raise ContractError(f"{SPEC_PATH}: include pattern {pattern!r} matches no file")
        found.update(matches)
    found.discard(MANIFEST_PATH)
    return sorted(found)


def suite_kinds(path: Path) -> tuple[dict[str, Any], dict[str, int]]:
    """(the suite file, vectors per kind). A vector without ``kind`` counts under ``*``."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("vectors"), list):
        raise ContractError(f"{path}: not a vector suite (an object with a 'vectors' list)")
    counts: dict[str, int] = {}
    for vector in data["vectors"]:
        kind = vector.get("kind", NO_KIND) if isinstance(vector, dict) else None
        if not isinstance(kind, str):
            raise ContractError(f"{path}: a vector has no object form or a non-string kind")
        counts[kind] = counts.get(kind, 0) + 1
    return data, counts


def required_kinds(suite: str, entry: dict[str, Any], kinds: dict[str, int],
                   na_only: list[str], tiers: dict[str, Any]) -> dict[str, list[str]]:
    """The kinds each tier must run: ``"all"`` is every kind but the NA-only ones."""
    required = entry.get("required")
    if not isinstance(required, dict):
        raise ContractError(f"{SPEC_PATH}: suite {suite!r} has no 'required' object")
    out: dict[str, list[str]] = {}
    for tier, value in required.items():
        if tier not in tiers:
            raise ContractError(f"{SPEC_PATH}: suite {suite!r} names unknown tier {tier!r}")
        if value == "all":
            listed = [k for k in kinds if k not in na_only]
        elif isinstance(value, list) and value and all(isinstance(k, str) for k in value):
            listed = list(value)
            unknown = sorted(set(listed) - set(kinds))
            if unknown:
                raise ContractError(f"{SPEC_PATH}: suite {suite!r} tier {tier!r} requires kinds "
                                    f"the suite does not have: {unknown}")
            if set(listed) & set(na_only):
                raise ContractError(f"{SPEC_PATH}: suite {suite!r} tier {tier!r} requires an NA-only kind")
            if len(set(listed)) != len(listed):
                raise ContractError(f"{SPEC_PATH}: suite {suite!r} tier {tier!r} lists a kind twice")
        else:
            raise ContractError(f"{SPEC_PATH}: suite {suite!r} tier {tier!r}: 'all' or a list of kinds")
        out[tier] = sorted(listed)
    return out


def build_manifest(root: Path) -> dict[str, Any]:
    """The manifest for the core checkout at ``root``, checking the spec on the way."""
    spec = read_json(root / SPEC_PATH)
    if not isinstance(spec, dict) or spec.get("schema") != SPEC_SCHEMA:
        raise ContractError(f"{SPEC_PATH}: schema must be {SPEC_SCHEMA!r}")
    tiers = spec.get("tiers")
    suites_spec = spec.get("suites")
    includes = spec.get("include")
    if not isinstance(tiers, dict) or not tiers or not isinstance(suites_spec, dict) or not isinstance(includes, list):
        raise ContractError(f"{SPEC_PATH}: needs 'include' (list), 'tiers' and 'suites' (objects)")
    if set(spec) - SPEC_KEYS:
        raise ContractError(f"{SPEC_PATH}: unknown keys {sorted(set(spec) - SPEC_KEYS)}")

    paths = expand(root, includes)
    for needed in (TOOL_PATH, "contract/kinds.json", "contract/public-surface.json"):
        if needed not in paths:
            raise ContractError(f"{SPEC_PATH}: the bundle must include {needed}")
    files = {}
    for rel in paths:
        data = (root / rel).read_bytes()
        files[rel] = {"bytes": len(data), "sha256": sha256_bytes(data)}

    suite_files = sorted(p for p in paths if p.startswith(VECTORS_DIR + "/") and p.endswith(".json"))
    on_disk = {Path(p).stem: p for p in suite_files}
    missing_entry = sorted(set(on_disk) - set(suites_spec))
    if missing_entry:
        raise ContractError(f"{SPEC_PATH}: suites without a tier entry: {missing_entry} "
                            "(every new suite needs a decision on which tiers must run it)")
    missing_file = sorted(set(suites_spec) - set(on_disk))
    if missing_file:
        raise ContractError(f"{SPEC_PATH}: entries for suites that are not in the bundle: {missing_file}")

    suites: dict[str, Any] = {}
    for name in sorted(on_disk):
        entry = suites_spec[name]
        if not isinstance(entry, dict):
            raise ContractError(f"{SPEC_PATH}: suite {name!r} entry is not an object")
        if set(entry) - SUITE_KEYS:
            raise ContractError(f"{SPEC_PATH}: suite {name!r} has unknown keys {sorted(set(entry) - SUITE_KEYS)}")
        data, kinds = suite_kinds(root / on_disk[name])
        if data.get("suite") != name:
            raise ContractError(f"{on_disk[name]}: names suite {data.get('suite')!r}, not {name!r}")
        na_only = entry.get("na_only_kinds", [])
        if (not isinstance(na_only, list) or not all(isinstance(k, str) for k in na_only)
                or len(set(na_only)) != len(na_only)):
            raise ContractError(f"{SPEC_PATH}: suite {name!r} na_only_kinds must be a list without repeats")
        if set(na_only) - set(kinds):
            raise ContractError(f"{SPEC_PATH}: suite {name!r} na_only_kinds not in the suite: "
                                f"{sorted(set(na_only) - set(kinds))}")
        if "na_only_kinds" in data and sorted(data["na_only_kinds"]) != sorted(na_only):
            raise ContractError(f"{on_disk[name]}: its na_only_kinds {data.get('na_only_kinds', [])} differ "
                                f"from {SPEC_PATH} {na_only}")
        suites[name] = {
            "file": on_disk[name],
            "kinds": dict(sorted(kinds.items())),
            "na_only_kinds": sorted(na_only),
            "required": required_kinds(name, entry, kinds, na_only, tiers),
            "suite_version": data.get("version"),
            "vectors": len(data["vectors"]),
        }

    fixtures = sorted({p.split("/")[2] for p in paths if p.startswith(FIXTURES_DIR + "/") and p.count("/") >= 3})
    version = core_version(root)
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "bundle_version": version,
        "core_version": version,
        "contract": {
            "error_codes": "/error_codes",
            "kinds": "contract/kinds.json",
            "public_surface": "contract/public-surface.json",
            "routes": None,
        },
        "files": files,
        "fixtures": {name: {"dir": f"{FIXTURES_DIR}/{name}/"} for name in fixtures},
        "format_level": None,
        "suites": suites,
        "tiers": dict(sorted(tiers.items())),
        "tool": {"path": TOOL_PATH, "sha256": files[TOOL_PATH]["sha256"]},
    }
    manifest["contract_digest"] = "sha256:" + contract_digest(manifest)
    return manifest


def contract_digest(manifest: dict[str, Any]) -> str:
    """sha256 of the canonical manifest without the version labels, the digest, the tool and the tool's file."""
    body = {k: v for k, v in manifest.items() if k not in UNDIGESTED}
    body["tiers"] = sorted(manifest["tiers"])
    body["files"] = {k: v for k, v in manifest["files"].items() if k != manifest["tool"]["path"]}
    return sha256_bytes(canonical(body))


def check_stdlib_only(source: str) -> list[str]:
    """Imports in the tool that are not in the standard library (it is vendored into every consumer)."""
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else ["<relative import>"]
        else:
            continue
        bad += [n for n in names if n.split(".")[0] not in stdlib]
    return sorted(set(bad))


def cmd_manifest(root: Path, check: bool) -> int:
    bad = check_stdlib_only((root / TOOL_PATH).read_text(encoding="utf-8"))
    if bad:
        raise ContractError(f"{TOOL_PATH} imports outside the standard library: {bad}")
    rendered = render(build_manifest(root))
    target = root / MANIFEST_PATH
    if check:
        current = target.read_bytes() if target.is_file() else b""
        if current != rendered:
            print(f"{MANIFEST_PATH} is stale: run `python {TOOL_PATH} manifest` and commit it", file=sys.stderr)
            return 1
        print(f"{MANIFEST_PATH} is current")
        return 0
    target.write_bytes(rendered)
    print(f"wrote {MANIFEST_PATH}")
    return 0


def source_date_epoch(root: Path) -> int:
    """``SOURCE_DATE_EPOCH``, else the commit time of HEAD: the archive's timestamps."""
    value = os.environ.get("SOURCE_DATE_EPOCH")
    if value is None:
        try:
            value = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%ct"], check=True,
                                   capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ContractError("set SOURCE_DATE_EPOCH (no git commit to take the time from)") from exc
    if not value.isdigit():
        raise ContractError(f"SOURCE_DATE_EPOCH is not a whole number of seconds: {value!r}")
    return int(value)


def archive_bytes(root: Path, epoch: int) -> tuple[str, bytes]:
    """(file name, tar) of the committed bundle: the same bytes for the same tree and epoch.

    Uncompressed on purpose: deflate output differs between builds (CPython on Windows ships
    zlib-ng), and the published checksum must not depend on the machine that built it.
    """
    manifest_bytes = (root / MANIFEST_PATH).read_bytes()
    if manifest_bytes != render(build_manifest(root)):
        raise ContractError(f"{MANIFEST_PATH} is stale: run `python {TOOL_PATH} manifest` first")
    manifest = json.loads(manifest_bytes)
    version = manifest["bundle_version"]
    top = f"genesis-mesh-contract-{version}"
    members = sorted([*manifest["files"], MANIFEST_PATH])
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in members:
            data = manifest_bytes if rel == MANIFEST_PATH else (root / rel).read_bytes()
            if rel != MANIFEST_PATH and sha256_bytes(data) != manifest["files"][rel]["sha256"]:
                raise ContractError(f"{rel} changed while the archive was built")
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size = len(data)
            info.mtime = epoch
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return f"{top}.tar", raw.getvalue()


def cmd_archive(root: Path, out: Path) -> int:
    name, data = archive_bytes(root, source_date_epoch(root))
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data)
    (out / "SHA256SUMS-contract").write_bytes(f"{sha256_bytes(data)}  {name}\n".encode("ascii"))
    print(f"wrote {out / name} and {out / 'SHA256SUMS-contract'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gm_contract.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="The checkout to act on (default: the one holding this file)")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest", help="Write contract/MANIFEST.json (core only)")
    manifest.add_argument("--check", action="store_true", help="Fail when the committed manifest is stale")
    archive = sub.add_parser("archive", help="Build the release archive and SHA256SUMS-contract (core only)")
    archive.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = core_root(args.repo.resolve())
        if args.command == "manifest":
            return cmd_manifest(root, args.check)
        return cmd_archive(root, args.out)
    except ContractError as exc:
        print(f"gm_contract: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
