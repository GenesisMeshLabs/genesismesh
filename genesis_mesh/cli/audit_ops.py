"""Audit packs: build, verify, archive (v1.5.0, Stage 4).

``audit pack`` asks the NA for one range of its store between two anchors
(a read-tier key is enough) and writes the pack. ``audit verify`` checks a
pack offline, from the root public key and the anchors the auditor holds,
and with ``--changes`` matches it against a log of changes kept outside
Genesis Mesh. ``audit archive`` (privileged) writes a pack to immutable
storage, reads it back and checks it, records the archive, then prunes the
store through it.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import click
import requests

from ..models.audit_pack import MANIFEST_FILE, AuditPackManifest
from ..trust.evidence_store import ExecutorKey
from ..workflows.audit_pack import (
    differences_from_pack_checks,
    parse_changes,
    read_pack_dir,
    verify_audit_pack,
)
from .evidence_store_ops import load_anchors
from .support import _admin_signer_from_inputs, _request_json, _signed_admin_headers, public_key_value


@click.group("audit")
def audit() -> None:
    """Audit packs: one range of the evidence store, verified independently."""


def _operator_options(func: Any) -> Any:
    for option in reversed((
        click.option("--config", "config_path", default=None, help="Config for operator signing."),
        click.option("--operator-key", default=None, help="Operator private key."),
        click.option("--operator-key-id", default="operator-local", help="Operator key ID."),
    )):
        func = option(func)
    return func


def _range_options(func: Any) -> Any:
    for option in reversed((
        click.option("--from-sequence", type=int, default=None,
                     help="First store entry (the range widens back to the anchor before it)."),
        click.option("--since", default=None, help="... or the first entry recorded at or after this time."),
        click.option("--until-sequence", type=int, default=None,
                     help="Last store entry (the range ends at the last anchor at or before it)."),
        click.option("--until", default=None, help="... or the last anchor signed at or before this time."),
    )):
        func = option(func)
    return func


def _range_body(from_sequence: int | None, since: str | None, until_sequence: int | None,
                until: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for name, value in (("from_sequence", from_sequence), ("since", since), ("until_sequence", until_sequence),
                        ("until", until)):
        if value is not None:
            body[name] = value
    return body


def _admin_call(base: str, method: str, path: str, body: dict[str, Any], key: tuple[str, Path], *,
                expected: int | tuple[int, ...] = 200, label: str) -> dict[str, Any]:
    headers = _signed_admin_headers(key[0], key[1], body, method=method, base_url=base, path=path)
    session = requests.Session()
    statuses = expected if isinstance(expected, tuple) else (expected,)
    try:
        resp = session.request(method, f"{base}{path}", json=body if method != "GET" else None, headers=headers,
                               timeout=120)
    except requests.RequestException as exc:
        raise click.ClickException(f"{label} failed: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text[:300]}
    if resp.status_code not in statuses:
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = f"{error.get('code')}: {error.get('message')}" if isinstance(error, dict) else str(payload)[:300]
        raise click.ClickException(f"{label} failed: {resp.status_code} {detail}")
    return payload if isinstance(payload, dict) else {}


def _pack_bytes(pack: dict[str, Any]) -> dict[str, bytes]:
    """The pack's files as the NA served them, with ``manifest.json`` in its exact form."""
    files = {path: text.encode("utf-8") for path, text in pack["files"].items()}
    files[MANIFEST_FILE] = AuditPackManifest.model_validate(pack["manifest"]).file_bytes()
    return files


def _safe_path(directory: Path, relative: str) -> Path:
    target = (directory / relative).resolve()
    if directory.resolve() not in target.parents:
        raise click.ClickException(f"the pack names a file outside its directory: {relative}")
    return target


def write_pack(directory: Path, files: dict[str, bytes]) -> None:
    """Write every file of a pack, never replacing one: a file that exists stops the write."""
    for relative, body in sorted(files.items()):
        path = _safe_path(directory, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(path, 0o444)
        except OSError:
            pass


def _manifest_problems(files: dict[str, bytes], expected_manifest: bytes) -> list[str]:
    """What differs between the files read back and the manifest the NA signed."""
    problems: list[str] = []
    if files.get(MANIFEST_FILE) != expected_manifest:
        problems.append("manifest.json differs from the one the NA signed")
        return problems
    manifest = AuditPackManifest.model_validate_json(expected_manifest)
    listed = {f.path: f for f in manifest.files}
    for path, item in sorted(listed.items()):
        body = files.get(path)
        if body is None:
            problems.append(f"{path} is missing")
        elif hashlib.sha256(body).hexdigest() != item.sha256 or len(body) != item.bytes:
            problems.append(f"{path} does not match its digest")
    problems += [f"{p} is not in the manifest" for p in sorted(files) if p != MANIFEST_FILE and p not in listed]
    return problems


@audit.command("pack")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Directory to write the pack into (new or empty).")
@_range_options
@_operator_options
def pack(na_endpoint: str, out_dir: Path, from_sequence: int | None, since: str | None,
         until_sequence: int | None, until: str | None, config_path: str | None, operator_key: str | None,
         operator_key_id: str) -> None:
    """Write an audit pack: one range of the store between two anchors (a read-tier key is enough).

    \b
        genesis-mesh audit pack --na https://na.example --since 2026-01-01T00:00:00Z \\
            --until 2027-01-01T00:00:00Z --out pack-2026 \\
            --operator-key auditor.key --operator-key-id auditor
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        raise click.ClickException(f"{out_dir} is not empty")
    base = na_endpoint.rstrip("/")
    key = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    result = _admin_call(base, "POST", "/admin/evidence/audit-pack",
                         _range_body(from_sequence, since, until_sequence, until), key, label="Audit pack")
    files = _pack_bytes(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_pack(out_dir, files)
    problems = _manifest_problems(read_pack_dir(out_dir), files[MANIFEST_FILE])
    if problems:
        raise click.ClickException("The pack written does not match its manifest: " + "; ".join(problems))
    manifest = result["manifest"]
    checks = json.loads(result["files"]["checks.json"])
    click.echo(f"Pack {manifest['pack_id']}: entries {manifest['from_sequence']} to {manifest['through_sequence']}, "
               f"ending at anchor {manifest['end_anchor_sequence']}; written to {out_dir}.")
    click.echo(f"The NA's own checks: {'verified' if checks.get('verified') else 'FAILED'}. Verify it yourself with "
               f"'genesis-mesh audit verify {out_dir} --anchor <root key> --known-anchors <your anchors>'.")


def _executor_keys(path: Path | None) -> dict[str, ExecutorKey] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("executor_keys", raw) if isinstance(raw, dict) else raw
    return {
        r["key_id"]: ExecutorKey(key_id=r["key_id"], public_key=r["public_key"],
                                 executor_sovereign_id=r["executor_sovereign_id"],
                                 role=r.get("role") or "executor", resource_prefix=r.get("resource_prefix"))
        for r in rows
    }


@audit.command("verify")
@click.argument("pack_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--anchor", "root_key", required=True,
              help="The root public key you hold (base64 or a key file): the pack's keys prove nothing alone.")
@click.option("--known-anchors", "anchors_path", required=True, type=click.Path(exists=True),
              help="Anchors you hold: a directory from 'evidence anchors fetch', or a JSON file.")
@click.option("--executor-keys", "executor_keys_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Executor keys you hold, for a store without registry records.")
@click.option("--changes", "changes_path", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Changes from a log outside Genesis Mesh (CSV or JSON) to match against the pack.")
@click.option("--tolerance-seconds", type=click.IntRange(0, 86400), default=300, show_default=True,
              help="How far apart a change and its record may be when matched by time.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify(pack_dir: Path, root_key: str, anchors_path: str, executor_keys_path: Path | None,
           changes_path: Path | None, tolerance_seconds: int, fmt: str) -> None:
    """Verify an audit pack offline, from the root key and the anchors you hold.

    No network, no private key. Every NA signature is checked against the
    key valid at the record's own time, from the root key down; executor
    keys only from registry records the NA signed (or --executor-keys).
    Decisions are judged as of their own time. Exits 1 when a check fails
    or a change from --changes has no record.

    \b
        genesis-mesh audit verify pack-2026 --anchor root.pub \\
            --known-anchors /audit/anchors --changes cloud-log.csv
    """
    files = read_pack_dir(pack_dir)
    held = load_anchors(anchors_path)
    if not held:
        raise click.ClickException(f"No anchors found in {anchors_path}")
    changes = None
    if changes_path is not None:
        try:
            changes = parse_changes(changes_path.read_text(encoding="utf-8"),
                                    csv_format=changes_path.suffix.lower() == ".csv")
        except ValueError as exc:
            raise click.ClickException(f"{changes_path}: {exc}") from exc
    result = verify_audit_pack(files, root_public_key=public_key_value(root_key), held_anchors=held,
                               executor_keys=_executor_keys(executor_keys_path), changes=changes,
                               tolerance=timedelta(seconds=tolerance_seconds))
    differences = differences_from_pack_checks(result, files)
    if fmt == "json":
        click.echo(json.dumps({**result.to_dict(), "report_differences": differences}, indent=2))
    else:
        r = result.range
        click.echo(f"Range      : entries {r.get('from_sequence')} to {r.get('through_sequence')} "
                   f"({r.get('entries')} entries)")
        counts = ", ".join(f"{k} {v}" for k, v in sorted(result.counts.items()) if v and k != "checked_entries")
        click.echo(f"Records    : {counts or 'none'}")
        click.echo(f"NA keys    : {len(result.keys)} in the key history")
        if result.completeness is not None:
            c = result.completeness
            click.echo(f"Changes    : {c['changes']}: {len(c['pairs'])} matched, {len(c['unmatched_changes'])} "
                       f"without a record, {len(c['outside_period'])} outside the period, "
                       f"{len(c['unmatched_records'])} records without a change")
        click.echo(f"Result     : {'VERIFIED' if result.verified else 'FAILED'}")
        for f in result.failures:
            click.echo(f"  - {f['file'] or '-'} #{f['store_sequence']}: {f['reason']} {f['detail']}".rstrip())
        for d in differences:
            click.echo(f"  ! differs from the pack's own checks: {d['field']}: pack {d['pack']}, here {d['verifier']}")
    if not result.verified:
        raise SystemExit(1)


@audit.command("archive")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--to", "to_dir", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Immutable storage: a directory (for example a mounted bucket with object lock).")
@click.option("--until-sequence", type=int, default=None, help="Archive through the last anchor at or before it.")
@click.option("--until", default=None, help="... or through the last anchor signed at or before this time.")
@click.option("--older-than-days", type=click.IntRange(1), default=None,
              help="Prune only entries older than this (default: everything the archive covers that may go).")
@click.option("--prune/--no-prune", default=True, show_default=True, help="Prune the store through the archive.")
@_operator_options
def archive(na_endpoint: str, to_dir: Path, until_sequence: int | None, until: str | None,
            older_than_days: int | None, prune: bool, config_path: str | None, operator_key: str | None,
            operator_key_id: str) -> None:
    """Archive the store: write a pack to immutable storage, read it back, record it, prune through it.

    The pack runs from the end of the last archive (or the store's start) to
    the last anchor. Nothing is recorded or pruned unless every file was
    written and read back matching the manifest the NA signed. Needs a
    privileged key.
    """
    base = na_endpoint.rstrip("/")
    key = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    archives = _admin_call(base, "GET", "/admin/evidence/archives", {}, key, label="Archive listing")
    body = _range_body(int(archives["archived_through_sequence"]) + 1, None, until_sequence, until)
    result = _admin_call(base, "POST", "/admin/evidence/audit-pack", body, key, label="Audit pack")
    files = _pack_bytes(result)
    manifest = result["manifest"]
    target = to_dir / manifest["pack_id"]
    try:
        target.mkdir(parents=True, exist_ok=False)
        write_pack(target, files)
    except OSError as exc:
        raise click.ClickException(f"Writing the pack to {target} failed ({exc}); nothing was recorded or pruned") from exc
    try:
        problems = _manifest_problems(read_pack_dir(target), files[MANIFEST_FILE])
    except OSError as exc:
        problems = [f"reading it back failed ({exc})"]
    if problems:
        raise click.ClickException(f"The pack read back from {target} does not match its manifest: "
                                   + "; ".join(problems) + ". Nothing was recorded or pruned.")
    recorded = _admin_call(base, "POST", "/admin/evidence/archives",
                           {"manifest": manifest, "location": str(target)}, key, expected=(200, 201),
                           label="Archive record")
    click.echo(f"Archived entries {manifest['from_sequence']} to {manifest['through_sequence']} to {target} "
               f"(archive {recorded['archive']['archive_id']}); archives cover the store through "
               f"{recorded['archived_through_sequence']}.")
    if not prune:
        return
    retention: dict[str, Any] = {"through_sequence": int(manifest["through_sequence"])}
    if older_than_days is not None:
        retention["older_than_days"] = older_than_days
    applied = _admin_call(base, "POST", "/admin/evidence/retention/apply", retention, key, label="Retention")
    held = applied.get("held_back")
    click.echo(f"Pruned {applied['removed_count']} entries" + (f"; held back: {held['message']}" if held else "."))
