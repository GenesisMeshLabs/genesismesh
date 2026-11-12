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

    python scripts/gm_contract.py manifest            # write contract/MANIFEST.json (and the package's digest)
    python scripts/gm_contract.py manifest --check    # fail when it is stale or the spec is wrong
    python scripts/gm_contract.py archive --out DIR   # reproducible release archive + SHA256SUMS-contract

Consumer commands (an SDK or the gateway, with ``contract-bundle/consumer.json``):

    python scripts/gm_contract.py sync --core-ref <40-hex>   # copy the bundle at a core commit on main, pin it
    python scripts/gm_contract.py sync --core-path ../genesismesh  # local development; never passes verify
    python scripts/gm_contract.py sync --core-ref <sha> --no-lock  # canaries: copies only, lock untouched
    python scripts/gm_contract.py verify [--online]          # copies, tool and manifest copy match the lock
    python scripts/gm_contract.py conformance [--json-out F] # run the tests with receipts, then receipt-check
    python scripts/gm_contract.py receipt-check --receipts DIR
    python scripts/gm_contract.py core-ref                   # the pinned core commit, for workflows

Release pins (``sync --version``/``--latest``), ``release-check``, ``latest``,
``fragment`` and ``status`` follow in the next change of
``ops/plan-v1.11.0-release-model.md``. Consumers vendor this file byte for
byte, so it must stay importable on Python 3.11 with the standard library
alone; ``manifest --check`` enforces that.

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
#: The bundle version and contract digest the core package carries, so a running Network Authority
#: can name the bundle it was built with (``/health`` ``contract_bundle``). Written
#: with the manifest; not part of the bundle.
DIGEST_MODULE_PATH = "genesis_mesh/contract_bundle.py"
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


def digest_module(version: str, digest: str) -> bytes:
    """The committed form of ``genesis_mesh/contract_bundle.py`` for a manifest's
    ``bundle_version`` and ``contract_digest``."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ContractError(f"not a bundle version: {version!r}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ContractError(f"not a contract digest: {digest!r}")
    return (
        '"""The contract bundle this core was built with (1.11.0).\n'
        "\n"
        "Generated by ``python scripts/gm_contract.py manifest`` from\n"
        "``contract/MANIFEST.json``, and checked by ``manifest --check``: do not edit.\n"
        "The Network Authority reports it in ``/health`` as ``contract_bundle``.\n"
        "``scripts/check_version.py --set`` bumps the version with the manifest's.\n"
        '"""\n'
        "\n"
        f'BUNDLE_VERSION = "{version}"\n'
        f'CONTRACT_DIGEST = "{digest}"\n'
    ).encode("ascii")


def cmd_manifest(root: Path, check: bool) -> int:
    bad = check_stdlib_only((root / TOOL_PATH).read_text(encoding="utf-8"))
    if bad:
        raise ContractError(f"{TOOL_PATH} imports outside the standard library: {bad}")
    manifest = build_manifest(root)
    outputs = {MANIFEST_PATH: render(manifest), DIGEST_MODULE_PATH: digest_module(manifest["bundle_version"], manifest["contract_digest"])}
    if check:
        stale = [rel for rel, data in outputs.items()
                 if not (root / rel).is_file() or (root / rel).read_bytes() != data]
        for rel in stale:
            print(f"{rel} is stale: run `python {TOOL_PATH} manifest` and commit it", file=sys.stderr)
        if stale:
            return 1
        print(f"{MANIFEST_PATH} and {DIGEST_MODULE_PATH} are current")
        return 0
    for rel, data in outputs.items():
        (root / rel).write_bytes(data)
        print(f"wrote {rel}")
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


# --- Consumer side ------------------------------------------------------------------------------
#
# A consumer (an SDK or the gateway) declares in contract-bundle/consumer.json which bundle files
# it copies where, which tiers it implements and how it runs its conformance tests. `sync` copies
# a bundle in and pins it in contract-bundle/bundle.lock; `verify` checks the copies against the
# pin; `conformance` runs the tests with receipts and `receipt-check` compares the receipts with
# the pinned manifest. Release pins (`sync --version`, `release-check`) follow in the next change.

CONSUMER_DIR = "contract-bundle"
CONSUMER_PATH = f"{CONSUMER_DIR}/consumer.json"
LOCK_PATH = f"{CONSUMER_DIR}/bundle.lock"
MANIFEST_COPY_PATH = f"{CONSUMER_DIR}/MANIFEST.json"
CONSUMER_SCHEMA = "gm.contract.consumer/1"
LOCK_SCHEMA = "gm.contract.lock/1"
RECEIPT_SCHEMA = "gm.contract.receipt/1"
CONSUMER_KEYS = frozenset({"schema", "component", "tiers", "tool_path", "files", "regenerate",
                           "conformance", "streams", "version_policy"})
LOCK_KEYS = frozenset({"schema", "source", "bundle_version", "core_tag", "core_commit", "archive",
                       "manifest_sha256", "contract_digest", "files", "tool_sha256"})
RECEIPT_KEYS = frozenset({"schema", "suite", "file", "runner", "run", "not_run"})
CORE_REPOSITORY = "GenesisMeshLabs/genesismesh"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"
COMPARE_URL = "https://api.github.com/repos/{repo}/compare/{commit}...main"
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
RECEIPTS_ENV = "GM_CONFORMANCE_RECEIPTS"
CACHE_ENV = "GM_CONTRACT_CACHE"


def _relative(path: Any, what: str, directory: bool = False) -> str:
    """A relative POSIX path inside the checkout; a directory mapping ends in ``/``."""
    if not isinstance(path, str) or path.endswith("/") != directory:
        raise ContractError(f"{CONSUMER_PATH}: {what} {path!r} must be a relative "
                            f"{'directory ending in /' if directory else 'file path'}")
    body = path[:-1] if directory else path
    if (not body or "\\" in body or body.startswith("/") or ":" in body
            or any(part in ("", ".", "..") for part in body.split("/"))):
        raise ContractError(f"{CONSUMER_PATH}: {what} {path!r} is not a relative path inside the checkout")
    return path


def _commands(value: Any, what: str) -> list[list[str]]:
    if (not isinstance(value, list) or not all(isinstance(c, list) and c and all(isinstance(a, str) and a for a in c)
                                               for c in value)):
        raise ContractError(f"{CONSUMER_PATH}: {what!r} must be a list of commands, each a non-empty list of strings")
    return value


def load_consumer(repo: Path) -> dict[str, Any]:
    """``contract-bundle/consumer.json``, checked for shape; the mapping is checked against a manifest later."""
    path = repo / CONSUMER_PATH
    if not path.is_file():
        raise ContractError(f"{repo} has no {CONSUMER_PATH}: the consumer commands run in an SDK or gateway checkout")
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != CONSUMER_SCHEMA:
        raise ContractError(f"{CONSUMER_PATH}: schema must be {CONSUMER_SCHEMA!r}")
    unknown = sorted(set(data) - CONSUMER_KEYS)
    missing = sorted({"component", "tiers", "tool_path", "files", "conformance"} - set(data))
    if unknown or missing:
        raise ContractError(f"{CONSUMER_PATH}: unknown keys {unknown}, missing keys {missing}")
    tiers = data["tiers"]
    if (not isinstance(data["component"], str) or not data["component"] or not isinstance(tiers, list) or not tiers
            or not all(isinstance(t, str) for t in tiers) or len(set(tiers)) != len(tiers)):
        raise ContractError(f"{CONSUMER_PATH}: 'component' is a name and 'tiers' a non-empty list without repeats")
    _relative(data["tool_path"], "tool_path")
    files = data["files"]
    if not isinstance(files, dict) or not files:
        raise ContractError(f"{CONSUMER_PATH}: 'files' maps bundle paths to paths in this checkout")
    for source, dest in files.items():
        directory = source.endswith("/")
        _relative(source, "bundle path", directory)
        _relative(dest, f"destination of {source}", directory)
    _commands(data.get("regenerate", []), "regenerate")
    _commands(data["conformance"], "conformance")
    return data


def mapping(consumer: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    """Destination -> bundle path for every copy, a directory mapping expanded over the manifest."""
    reserved = {consumer["tool_path"], LOCK_PATH, MANIFEST_COPY_PATH, CONSUMER_PATH}
    out: dict[str, str] = {}
    for source, dest in consumer["files"].items():
        if source.endswith("/"):
            # sync removes what the bundle drops from a directory copy, so the directory must hold
            # nothing else of the consumer's own: not the tool, the lock or the manifest copy.
            if any(path.startswith(dest) for path in (*reserved, CONSUMER_DIR + "/")):
                raise ContractError(f"{CONSUMER_PATH}: the directory {dest!r} would hold the tool or "
                                    f"{CONSUMER_DIR}/; copy the bundle into a directory of its own")
            pairs =[(rel, dest + rel[len(source):]) for rel in manifest["files"] if rel.startswith(source)]
        else:
            pairs = [(source, dest)] if source in manifest["files"] else []
        if not pairs:
            raise ContractError(f"{CONSUMER_PATH}: {source!r} names no file of bundle {manifest['bundle_version']}")
        for rel, target in pairs:
            if rel == manifest["tool"]["path"]:
                raise ContractError(f"{CONSUMER_PATH}: the tool is copied to tool_path, not through 'files'")
            if target in reserved or target.startswith(CONSUMER_DIR + "/"):
                raise ContractError(f"{CONSUMER_PATH}: {target!r} is reserved for the tool, the lock or the manifest")
            if target in out:
                raise ContractError(f"{CONSUMER_PATH}: two bundle files are copied to {target!r}")
            out[target] = rel
    return dict(sorted(out.items()))


def check_manifest(data: bytes) -> dict[str, Any]:
    """A manifest read from a bundle source: its schema, and a digest that matches its content."""
    try:
        manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError(f"the bundle manifest is not JSON ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ContractError(f"the bundle manifest's schema is not {MANIFEST_SCHEMA!r}")
    try:
        digest = "sha256:" + contract_digest(manifest)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ContractError(f"the bundle manifest is incomplete ({exc!r})") from exc
    if manifest.get("contract_digest") != digest:
        raise ContractError("the bundle manifest's contract_digest does not match its content")
    # A manifest that agrees with itself can still be hostile (any commit, a fork's included, is
    # served under the core's name): every path in it must be a plain relative path, and every
    # hash a sha256, before a single file is fetched or written.
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ContractError("the bundle manifest lists no files")
    for rel, entry in files.items():
        if not _plain_path(rel):
            raise ContractError(f"the bundle manifest lists an unsafe path {rel!r}")
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(entry["sha256"]):
            raise ContractError(f"the bundle manifest has no sha256 for {rel!r}")
    tool = manifest["tool"]
    if not isinstance(tool, dict) or tool.get("path") not in files or tool.get("sha256") != files[tool["path"]]["sha256"]:
        raise ContractError("the bundle manifest's tool is not one of its files")
    suites = manifest["suites"]
    if not isinstance(suites, dict) or not all(isinstance(s, dict) and s.get("file") in files for s in suites.values()):
        raise ContractError("the bundle manifest names a suite file it does not list")
    return manifest


def _plain_path(path: Any) -> bool:
    """A relative POSIX file path: no drive, no backslash, no empty, ``.`` or ``..`` segment."""
    return (isinstance(path, str) and bool(path) and "\\" not in path and ":" not in path
            and not path.startswith("/") and all(part not in ("", ".", "..") for part in path.split("/")))


def inside(repo: Path, rel: str) -> Path:
    """``repo / rel``, refusing a path that leaves the checkout (through ``..`` or a symbolic link)."""
    target = (repo / rel).resolve()
    if target != repo.resolve() and repo.resolve() not in target.parents:
        raise ContractError(f"{rel!r} resolves outside the checkout")
    return target


def required_suites(manifest: dict[str, Any], tiers: list[str]) -> dict[str, set[str]]:
    """Suite -> the kinds the given tiers must run, for every suite that requires any."""
    unknown = sorted(set(tiers) - set(manifest["tiers"]))
    if unknown:
        raise ContractError(f"{CONSUMER_PATH}: tiers {unknown} are not in bundle {manifest['bundle_version']} "
                            f"(it has {sorted(manifest['tiers'])})")
    out: dict[str, set[str]] = {}
    for name, suite in manifest["suites"].items():
        kinds = {k for tier in tiers for k in suite["required"].get(tier, [])}
        if kinds:
            out[name] = kinds
    return out


# Fetching (commit pins) -------------------------------------------------------------------------

def cache_dir() -> Path:
    configured = os.environ.get(CACHE_ENV)
    return Path(configured) if configured else Path.home() / ".cache" / "genesis-mesh" / "contract"


def fetch_url(url: str) -> bytes:
    """GET ``url``. A token (GITHUB_TOKEN or GH_TOKEN) is sent to api.github.com and nowhere else."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "gm_contract"})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        # Unredirected: urllib copies ordinary headers onto a redirect, wherever it leads.
        request.add_unredirected_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ContractError(f"cannot fetch {url} ({exc})") from exc


def on_main(commit: str) -> None:
    """Fail unless ``commit`` is core ``main`` or one of its ancestors (GitHub's compare API)."""
    try:
        compare = json.loads(fetch_url(COMPARE_URL.format(repo=CORE_REPOSITORY, commit=commit)))
    except ValueError as exc:
        raise ContractError(f"GitHub's compare answer is not JSON ({exc})") from exc
    status = compare.get("status") if isinstance(compare, dict) else None
    if status not in ("ahead", "identical"):
        raise ContractError(f"core {commit[:12]} is not on core main (compare status {status!r}): pin a merged commit")


class CommitSource:
    """The bundle at a core commit, read from raw.githubusercontent.com.

    Files are cached by their sha256 and used only when they still hash to it. The manifest is
    cached by commit for ``--offline`` alone: an online sync always fetches it again.
    """

    def __init__(self, commit: str, offline: bool = False) -> None:
        if not COMMIT.fullmatch(commit):
            raise ContractError(f"--core-ref must be a full 40-character commit hash, not {commit!r}")
        self.commit = commit
        self.offline = offline
        self.cache = cache_dir()

    def _fetch(self, rel: str) -> bytes:
        if self.offline:
            raise ContractError(f"--offline: {rel} at {self.commit[:12]} is not in the cache {self.cache}")
        return fetch_url(RAW_URL.format(repo=CORE_REPOSITORY, commit=self.commit, path=rel))

    def manifest_bytes(self) -> bytes:
        cached = self.cache / "commits" / self.commit / "MANIFEST.json"
        data = cached.read_bytes() if self.offline and cached.is_file() else self._fetch(MANIFEST_PATH)
        check_manifest(data)
        if not self.offline:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        return data

    def file(self, rel: str, sha256: str) -> bytes:
        cached = self.cache / "objects" / sha256
        if cached.is_file():
            data = cached.read_bytes()
            if sha256_bytes(data) == sha256:
                return data
        data = self._fetch(rel)
        if sha256_bytes(data) == sha256:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        return data


class PathSource:
    """The bundle in a core checkout on disk (local development; its lock never passes ``verify``)."""

    def __init__(self, root: Path) -> None:
        self.root = core_root(root.resolve())
        self.commit: str | None = None
        try:
            self.commit = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], check=True,
                                         capture_output=True, text=True).stdout.strip() or None
        except (OSError, subprocess.CalledProcessError):
            pass

    def manifest_bytes(self) -> bytes:
        path = self.root / MANIFEST_PATH
        if not path.is_file():
            raise ContractError(f"{self.root} has no {MANIFEST_PATH}")
        return path.read_bytes()

    def file(self, rel: str, sha256: str) -> bytes:
        return (self.root / rel).read_bytes()


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def _run(command: list[str], repo: Path, env: dict[str, str] | None = None) -> int:
    """Run a consumer.json command in the checkout; the program is looked up on PATH (npm.cmd on Windows)."""
    import shutil

    program = shutil.which(command[0]) or command[0]
    print("+ " + " ".join(command), flush=True)
    try:
        return subprocess.run([program, *command[1:]], cwd=repo, env=env).returncode
    except OSError as exc:
        raise ContractError(f"cannot run {command[0]!r} ({exc})") from exc


def directory_destinations(consumer: dict[str, Any]) -> list[str]:
    return [dest for source, dest in consumer["files"].items() if source.endswith("/")]


def extra_files(repo: Path, consumer: dict[str, Any], copies: dict[str, str]) -> list[str]:
    """Files under a directory mapping that the bundle does not have."""
    extra = []
    for dest in directory_destinations(consumer):
        base = repo / dest
        if base.is_dir():
            extra += [p.relative_to(repo).as_posix() for p in base.rglob("*")
                      if p.is_file() and p.relative_to(repo).as_posix() not in copies]
    return sorted(extra)


def cmd_sync(repo: Path, source: CommitSource | PathSource, write_lock: bool) -> int:
    consumer = load_consumer(repo)
    manifest_bytes = source.manifest_bytes()
    manifest = check_manifest(manifest_bytes)
    copies = mapping(consumer, manifest)
    required = required_suites(manifest, consumer["tiers"])
    mapped = set(copies.values())
    unmapped = sorted(name for name in required if manifest["suites"][name]["file"] not in mapped)
    if unmapped:
        raise ContractError(f"{CONSUMER_PATH}: suites required by tiers {consumer['tiers']} are not copied: {unmapped}")

    blobs: dict[str, bytes] = {}
    for rel in sorted({*copies.values(), manifest["tool"]["path"]}):
        data = source.file(rel, manifest["files"][rel]["sha256"])
        if sha256_bytes(data) != manifest["files"][rel]["sha256"]:
            raise ContractError(f"{rel} does not match the bundle manifest (a stale manifest at the source?)")
        blobs[rel] = data

    if isinstance(source, CommitSource) and write_lock and not source.offline:
        on_main(source.commit)   # before anything is written: a lock names a merged core commit
    targets = {dest: inside(repo, dest) for dest in copies}
    try:
        previous = set(read_lock(repo)["files"]) if (repo / LOCK_PATH).is_file() else set()
    except ContractError:
        previous = set()

    changed = [dest for dest, rel in copies.items() if write_if_changed(targets[dest], blobs[rel])]
    # Only copies the previous pin made and this one drops: never a file sync did not write.
    for stale in sorted(previous - set(copies)):
        path = inside(repo, stale) if _plain_path(stale) else None
        if path is not None and path.is_file():
            path.unlink()
            changed.append(f"{stale} (removed)")
    if write_if_changed(inside(repo, MANIFEST_COPY_PATH), manifest_bytes):
        changed.append(MANIFEST_COPY_PATH)
    tool = blobs[manifest["tool"]["path"]]
    if write_lock and write_if_changed(inside(repo, consumer["tool_path"]), tool):
        changed.append(consumer["tool_path"])
    for command in consumer.get("regenerate", []):
        if _run(command, repo) != 0:
            raise ContractError(f"regenerate command failed: {' '.join(command)} ({LOCK_PATH} left as it was)")
    if write_lock:
        lock = {
            "schema": LOCK_SCHEMA,
            "source": "path" if isinstance(source, PathSource) else "commit",
            "bundle_version": manifest["bundle_version"],
            "core_tag": None,
            "core_commit": source.commit,
            "archive": None,
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "contract_digest": manifest["contract_digest"],
            "files": {dest: {"from": rel, "sha256": manifest["files"][rel]["sha256"]} for dest, rel in copies.items()},
            "tool_sha256": sha256_bytes(tool),
        }
        if write_if_changed(inside(repo, LOCK_PATH), render(lock)):
            changed.append(LOCK_PATH)
    label = pin_label(manifest["bundle_version"], source.commit)
    print(f"bundle {label} ({manifest['contract_digest'][:19]}): "
          + (", ".join(changed) if changed else "nothing changed"))
    if not write_lock:
        print(f"--no-lock: {LOCK_PATH} and {consumer['tool_path']} were left as they are")
    return 0


def pin_label(version: str, commit: str | None) -> str:
    return f"{version}+g{commit[:12]}" if commit else version


def read_lock(repo: Path) -> dict[str, Any]:
    path = repo / LOCK_PATH
    if not path.is_file():
        raise ContractError(f"no {LOCK_PATH}: run `gm_contract.py sync` first")
    lock = read_json(path)
    if not isinstance(lock, dict) or lock.get("schema") != LOCK_SCHEMA or set(lock) != LOCK_KEYS:
        raise ContractError(f"{LOCK_PATH}: not a {LOCK_SCHEMA} lock with exactly the keys {sorted(LOCK_KEYS)}")
    if lock["source"] not in ("release", "commit", "path"):
        raise ContractError(f"{LOCK_PATH}: source must be release, commit or path")
    return lock


def verify_offline(repo: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(consumer, lock, manifest) after checking every copy, the tool and the manifest copy against the lock."""
    consumer = load_consumer(repo)
    lock = read_lock(repo)
    problems: list[str] = []
    if lock["source"] == "path":
        problems.append(f"{LOCK_PATH} pins a local core checkout (source 'path'): sync from a commit or a "
                        "release before committing")
    if lock["source"] == "commit":
        if not (isinstance(lock["core_commit"], str) and COMMIT.fullmatch(lock["core_commit"])):
            problems.append(f"{LOCK_PATH}: a commit pin needs a 40-character core_commit")
        if lock["core_tag"] is not None or lock["archive"] is not None:
            problems.append(f"{LOCK_PATH}: a commit pin has no core_tag or archive")
    if lock["source"] == "release":
        problems.append(f"{LOCK_PATH}: release pins are checked from the next version of this tool")
    copy_path = repo / MANIFEST_COPY_PATH
    if not copy_path.is_file():
        raise ContractError(f"no {MANIFEST_COPY_PATH}: run `gm_contract.py sync`")
    manifest_bytes = copy_path.read_bytes()
    manifest = check_manifest(manifest_bytes)
    if sha256_bytes(manifest_bytes) != lock["manifest_sha256"]:
        problems.append(f"{MANIFEST_COPY_PATH} is not the manifest {LOCK_PATH} pins")
    for key in ("bundle_version", "contract_digest"):
        if manifest[key] != lock[key]:
            problems.append(f"{LOCK_PATH} {key} {lock[key]!r} differs from the manifest's {manifest[key]!r}")
    copies = mapping(consumer, manifest)
    expected = {dest: {"from": rel, "sha256": manifest["files"][rel]["sha256"]} for dest, rel in copies.items()}
    if lock["files"] != expected:
        problems.append(f"{LOCK_PATH} files differ from {CONSUMER_PATH} applied to the pinned manifest: "
                        "run `gm_contract.py sync` with the same pin")
    for dest, entry in expected.items():
        path = repo / dest
        if not path.is_file():
            problems.append(f"{dest} is missing")
        elif sha256_bytes(path.read_bytes()) != entry["sha256"]:
            problems.append(f"{dest} differs from {entry['from']} in the pinned bundle (edited, or line endings "
                            "changed: mark it -text in .gitattributes)")
    problems += [f"{extra} is not in the pinned bundle" for extra in extra_files(repo, consumer, copies)]
    tool = repo / consumer["tool_path"]
    tool_sha = sha256_bytes(tool.read_bytes()) if tool.is_file() else None
    if tool_sha != lock["tool_sha256"] or tool_sha != manifest["tool"]["sha256"]:
        problems.append(f"{consumer['tool_path']} is not the tool of the pinned bundle")
    mapped = set(copies.values())
    for name in sorted(required_suites(manifest, consumer["tiers"])):
        if manifest["suites"][name]["file"] not in mapped:
            problems.append(f"suite {name} is required by tiers {consumer['tiers']} and not copied")
    if problems:
        raise ContractError("verify failed:\n  " + "\n  ".join(problems))
    return consumer, lock, manifest


def verify_online(lock: dict[str, Any]) -> None:
    """A commit pin: the manifest at that commit is the pinned one, and the commit is on core ``main``."""
    if lock["source"] != "commit":
        raise ContractError(f"verify --online checks commit pins; a {lock['source']} pin is checked from the "
                            "next version of this tool")
    commit = lock["core_commit"]
    data = fetch_url(RAW_URL.format(repo=CORE_REPOSITORY, commit=commit, path=MANIFEST_PATH))
    if sha256_bytes(data) != lock["manifest_sha256"]:
        raise ContractError(f"the manifest at core {commit[:12]} is not the one {LOCK_PATH} pins")
    on_main(commit)


def cmd_verify(repo: Path, online: bool) -> int:
    consumer, lock, manifest = verify_offline(repo)
    if online:
        verify_online(lock)
    print(f"{consumer['component']}: bundle {pin_label(lock['bundle_version'], lock['core_commit'])} "
          f"verified{' online' if online else ''} ({len(lock['files'])} copies)")
    return 0


def _counts(value: Any, what: str) -> dict[str, int]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and type(n) is int and n >= 0 for k, n in value.items()):
        raise ContractError(f"{what}: must map kinds to counts (whole numbers, 0 or more)")
    return value


def check_receipts(repo: Path, consumer: dict[str, Any], manifest: dict[str, Any],
                   receipts: Path) -> dict[str, Any]:
    """The summary of the receipts in ``receipts`` against the manifest; raises on any failure (see A6)."""
    copies = mapping(consumer, manifest)
    by_suite: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    problems: list[str] = []
    if not receipts.is_dir():
        raise ContractError(f"the receipts directory {receipts} does not exist")
    files = sorted(receipts.glob("*.json"))
    for path in files:
        receipt = read_json(path)
        if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA or set(receipt) != RECEIPT_KEYS:
            problems.append(f"{path.name}: not a {RECEIPT_SCHEMA} receipt with exactly {sorted(RECEIPT_KEYS)}")
            continue
        if not all(isinstance(receipt[key], str) for key in ("suite", "file", "runner")):
            problems.append(f"{path.name}: suite, file and runner must be strings")
            continue
        suite = receipt["suite"]
        if suite not in manifest["suites"]:
            problems.append(f"{path.name}: suite {suite!r} is not in bundle {manifest['bundle_version']}")
            continue
        _counts(receipt["run"], f"{path.name} run")
        _counts(receipt["not_run"], f"{path.name} not_run")
        source = manifest["suites"][suite]["file"]
        dest = receipt["file"]
        if copies.get(dest) != source:
            problems.append(f"{path.name}: {dest!r} is not where {CONSUMER_PATH} copies {source}")
        elif not (repo / dest).is_file() or sha256_bytes((repo / dest).read_bytes()) != manifest["files"][source]["sha256"]:
            problems.append(f"{path.name}: {dest} is not the bundle's {source}")
        by_suite.setdefault(suite, []).append((path.name, receipt))

    required = required_suites(manifest, consumer["tiers"])
    summary: dict[str, Any] = {}
    for suite in sorted(set(required) | set(by_suite)):
        kinds: dict[str, int] = manifest["suites"][suite]["kinds"]
        entries = by_suite.get(suite, [])
        if not entries:
            problems.append(f"suite {suite}: required by tiers {consumer['tiers']}, and no runner wrote a receipt")
            continue
        run: dict[str, int] = {}
        not_run: dict[str, int] = {}
        for name, receipt in entries:
            for kind in sorted(set(receipt["run"]) | set(receipt["not_run"])):
                if kind not in kinds:
                    problems.append(f"{name}: kind {kind!r} is not in suite {suite}")
            for kind, n in receipt["run"].items():
                run[kind] = run.get(kind, 0) + n
            for kind, n in receipt["not_run"].items():
                not_run[kind] = not_run.get(kind, 0) + n
        for kind, total in kinds.items():
            accounted = run.get(kind, 0) + not_run.get(kind, 0)
            if accounted != total:
                problems.append(f"suite {suite} kind {kind}: {accounted} vectors accounted for "
                                f"({run.get(kind, 0)} run, {not_run.get(kind, 0)} not run), the bundle has {total}")
        for kind in sorted(required.get(suite, set())):
            if run.get(kind, 0) < kinds[kind]:
                problems.append(f"suite {suite} kind {kind}: required, {run.get(kind, 0)} of {kinds[kind]} run")
        summary[suite] = {
            "required": sorted(required.get(suite, set())),
            "run": dict(sorted(run.items())),
            "not_run": dict(sorted(not_run.items())),
            "runners": sorted(receipt["runner"] for _, receipt in entries),
        }
    if problems:
        raise ContractError("receipt-check failed:\n  " + "\n  ".join(problems))
    return summary


def cmd_receipt_check(repo: Path, receipts: Path, json_out: Path | None = None) -> int:
    consumer = load_consumer(repo)
    manifest = check_manifest((repo / MANIFEST_COPY_PATH).read_bytes()) if (repo / MANIFEST_COPY_PATH).is_file() else None
    if manifest is None:
        raise ContractError(f"no {MANIFEST_COPY_PATH}: run `gm_contract.py sync`")
    summary = check_receipts(repo, consumer, manifest, receipts)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_bytes(render({
            "schema": "gm.contract.conformance/1",
            "component": consumer["component"],
            "tiers": consumer["tiers"],
            "bundle_version": manifest["bundle_version"],
            "contract_digest": manifest["contract_digest"],
            "suites": summary,
        }))
    for suite, entry in summary.items():
        print(f"{suite}: {sum(entry['run'].values())} run, {sum(entry['not_run'].values())} not run"
              + (f" (required: {', '.join(entry['required'])})" if entry["required"] else ""))
    print(f"{consumer['component']}: receipts match bundle {manifest['bundle_version']} for tiers {consumer['tiers']}")
    return 0


def cmd_conformance(repo: Path, receipts: Path | None, json_out: Path | None, lock_check: bool) -> int:
    import tempfile

    if lock_check:
        verify_offline(repo)
    consumer = load_consumer(repo)
    with tempfile.TemporaryDirectory(prefix="gm-receipts-") as scratch:
        target = receipts.resolve() if receipts is not None else Path(scratch)
        if target.is_dir() and any(target.glob("*.json")):
            raise ContractError(f"{target} already holds receipts: give an empty directory")
        target.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, RECEIPTS_ENV: str(target)}
        for command in consumer["conformance"]:
            if _run(command, repo, env) != 0:
                raise ContractError(f"conformance command failed: {' '.join(command)}")
        return cmd_receipt_check(repo, target, json_out)


def cmd_core_ref(repo: Path) -> int:
    lock = read_lock(repo)
    if not (isinstance(lock["core_commit"], str) and COMMIT.fullmatch(lock["core_commit"])):
        raise ContractError(f"{LOCK_PATH} names no 40-character core commit")
    print(lock["core_commit"])
    return 0


def usage(parser: argparse.ArgumentParser, message: str) -> int:
    """A usage error: exit code 2, as argparse gives for the errors it finds itself."""
    parser.print_usage(sys.stderr)
    print(f"{parser.prog}: error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gm_contract.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="The checkout to act on (default: the one holding this file)")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest", help="Write contract/MANIFEST.json and the package's digest (core only)")
    manifest.add_argument("--check", action="store_true", help="Fail when the committed manifest is stale")
    archive = sub.add_parser("archive", help="Build the release archive and SHA256SUMS-contract (core only)")
    archive.add_argument("--out", type=Path, required=True)
    sync = sub.add_parser("sync", help="Copy a bundle into this consumer and pin it")
    pin = sync.add_mutually_exclusive_group(required=True)
    pin.add_argument("--core-ref", metavar="SHA", help="A core commit (40 hex) on main")
    pin.add_argument("--core-path", type=Path, metavar="DIR", help="A core checkout (local development only)")
    sync.add_argument("--no-lock", action="store_true",
                      help="Write the copies and the manifest copy, not the lock or the tool (canaries)")
    sync.add_argument("--offline", action="store_true", help="With --core-ref: use only the cache")
    verify = sub.add_parser("verify", help="Check the copies, the tool and the manifest copy against the lock")
    verify.add_argument("--online", action="store_true", help="Also check the pin against GitHub")
    conformance = sub.add_parser("conformance", help="Run the conformance commands with receipts, then receipt-check")
    conformance.add_argument("--receipts", type=Path, help="Where the runners write receipts (an empty directory)")
    conformance.add_argument("--json-out", type=Path, help="Write the per-suite summary as JSON")
    conformance.add_argument("--no-lock-check", action="store_true",
                             help="Skip verify (after sync --no-lock: the copies follow the manifest copy)")
    receipt = sub.add_parser("receipt-check", help="Compare receipts with the pinned manifest")
    receipt.add_argument("--receipts", type=Path, required=True)
    receipt.add_argument("--json-out", type=Path)
    sub.add_parser("core-ref", help="Print the pinned core commit")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command == "sync":
        if args.core_ref is not None and not COMMIT.fullmatch(args.core_ref):
            return usage(parser, f"--core-ref must be a full 40-character commit hash, not {args.core_ref!r}")
        if args.offline and args.core_path is not None:
            return usage(parser, "--offline applies to --core-ref; a core checkout is already local")
    try:
        repo = args.repo.resolve()
        if args.command == "sync":
            if args.core_ref is not None:
                return cmd_sync(repo, CommitSource(args.core_ref, args.offline), not args.no_lock)
            return cmd_sync(repo, PathSource(args.core_path), not args.no_lock)
        if args.command == "verify":
            return cmd_verify(repo, args.online)
        if args.command == "conformance":
            return cmd_conformance(repo, args.receipts, args.json_out, not args.no_lock_check)
        if args.command == "receipt-check":
            return cmd_receipt_check(repo, args.receipts, args.json_out)
        if args.command == "core-ref":
            return cmd_core_ref(repo)
        root = core_root(repo)
        if args.command == "manifest":
            return cmd_manifest(root, args.check)
        return cmd_archive(root, args.out)
    except ContractError as exc:
        print(f"gm_contract: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
