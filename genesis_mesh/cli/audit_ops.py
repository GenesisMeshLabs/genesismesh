"""Audit packs: build, verify, archive (v1.5.0, Stage 4).

``audit pack`` asks the NA for one range of its store between two anchors
(a read-tier key is enough) and writes the pack. ``audit verify`` checks a
pack offline, from the root public key and the anchors the auditor holds,
and with ``--changes`` matches it against a log of changes kept outside
Genesis Mesh. ``audit archive`` (privileged) writes a pack to immutable
storage, reads it back and verifies it, records the archive, then prunes the
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

from ..models.audit_pack import GENESIS_FILE, MANIFEST_FILE, AuditPackManifest
from ..models.evidence_store import StoreAnchor
from ..trust.evidence_store import ExecutorKey
from ..workflows.audit_pack import (
    differences_from_pack_checks,
    pack_entry_digests,
    parse_changes,
    parse_rfc3339,
    read_pack_dir,
    render_report,
    report_header,
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
    return _executor_key_rows(rows)


def _executor_key_rows(rows: Any) -> dict[str, ExecutorKey]:
    return {
        r["key_id"]: ExecutorKey(key_id=r["key_id"], public_key=r["public_key"],
                                 executor_sovereign_id=r["executor_sovereign_id"],
                                 role=r.get("role") or "executor", resource_prefix=r.get("resource_prefix"))
        for r in rows if isinstance(r, dict)
    }


def _fetch_anchors(base: str, key: tuple[str, Path]) -> list[StoreAnchor]:
    """Every anchor the NA serves (read tier), in order."""
    path = "/admin/evidence/anchors"
    session = requests.Session()
    anchors: list[StoreAnchor] = []
    after = 0
    while True:
        query = {"after_anchor": str(after), "limit": "1000"}
        headers = _signed_admin_headers(key[0], key[1], {}, method="GET", base_url=base, path=path, query=query)
        page = _request_json(session, "GET", f"{base}{path}", params=query, headers=headers, label="Anchor listing")
        anchors += [StoreAnchor.model_validate(raw) for raw in page.get("anchors", [])]
        nxt = page.get("next_after_anchor")
        if not isinstance(nxt, int) or nxt <= after:
            return anchors
        after = nxt


@audit.command("verify")
@click.argument("pack_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--anchor", "root_key", required=True,
              help="The root public key you hold (base64 or a key file): the pack's keys prove nothing alone.")
@click.option("--known-anchors", "anchors_path", default=None, type=click.Path(exists=True),
              help="Anchors you hold: a directory from 'evidence anchors fetch', or a JSON file. Without them "
                   "the pack proves its integrity, not that nothing was removed (warning no_held_anchors).")
@click.option("--require-anchors", is_flag=True, default=False,
              help="Fail (exit 1) when --known-anchors is not given.")
@click.option("--prior", "prior_dirs", multiple=True, type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="A pack verified before (repeatable): the entries this pack cites must equal the ones it holds.")
@click.option("--period", "period", nargs=2, default=None, metavar="FROM UNTIL",
              help="Two RFC 3339 times: fail when the pack does not cover this period.")
@click.option("--report", "report_path", default=None, type=click.Path(dir_okay=False, path_type=Path),
              help="Write the report this verification renders (from what it verified) to this file.")
@click.option("--executor-keys", "executor_keys_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Executor keys you hold, for a store without registry records.")
@click.option("--changes", "changes_path", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Changes from a log outside Genesis Mesh (CSV or JSON) to match against the pack.")
@click.option("--tolerance-seconds", type=click.IntRange(0, 86400), default=300, show_default=True,
              help="How far apart a change and its record may be when matched by time.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify(pack_dir: Path, root_key: str, anchors_path: str | None, require_anchors: bool,
           prior_dirs: tuple[Path, ...], period: tuple[str, str] | None, report_path: Path | None,
           executor_keys_path: Path | None, changes_path: Path | None, tolerance_seconds: int, fmt: str) -> None:
    """Verify an audit pack offline, from the root key and the anchors you hold.

    No network, no private key. Every NA signature is checked against the
    key valid at the record's own time, from the root key down; executor
    keys only from registry records the NA signed (or --executor-keys).
    Decisions are judged as of their own time. Exits 1 when a check fails
    or a change from --changes has no record.

    The entries a pack cites (cited.jsonl) are checked by their signatures;
    give the packs you verified before (--prior) or anchors at their
    positions to tie them to the store. Each one neither covers is a
    warning (cited_entry_unanchored).

    \b
        genesis-mesh audit verify pack-2026 --anchor root.pub \\
            --known-anchors /audit/anchors --changes cloud-log.csv
    """
    files = read_pack_dir(pack_dir)
    root = public_key_value(root_key)
    held: list[StoreAnchor] | None = None
    if anchors_path is not None:
        held = load_anchors(anchors_path)
        if not held:
            raise click.ClickException(f"No anchors found in {anchors_path}")
    elif require_anchors:
        raise click.ClickException("--require-anchors: give the anchors you hold with --known-anchors")
    else:
        click.echo("WARNING: no --known-anchors: this checks the pack's integrity, not that nothing was "
                   "removed from the store. Fetch the anchors with 'genesis-mesh evidence anchors fetch' and "
                   "keep them outside the NA.", err=True)
    asked: tuple[Any, Any] | None = None
    if period is not None:
        try:
            asked = (parse_rfc3339(period[0]), parse_rfc3339(period[1]))
        except ValueError as exc:
            raise click.ClickException(f"--period: {exc}") from exc
        if asked[0] > asked[1]:
            raise click.ClickException("--period: FROM is after UNTIL")
    prior: dict[int, str] = {}
    for prior_dir in prior_dirs:
        prior_files = read_pack_dir(prior_dir)
        checked = verify_audit_pack(prior_files, root_public_key=root, held_anchors=held,
                                    executor_keys=_executor_keys(executor_keys_path))
        if not checked.verified:
            raise click.ClickException(f"--prior {prior_dir} does not verify: {', '.join(checked.reasons())}")
        prior.update(pack_entry_digests(prior_files))
    changes = None
    if changes_path is not None:
        try:
            changes = parse_changes(changes_path.read_text(encoding="utf-8"),
                                    csv_format=changes_path.suffix.lower() == ".csv")
        except ValueError as exc:
            raise click.ClickException(f"{changes_path}: {exc}") from exc
    result = verify_audit_pack(files, root_public_key=root, held_anchors=held,
                               executor_keys=_executor_keys(executor_keys_path), changes=changes,
                               tolerance=timedelta(seconds=tolerance_seconds), period=asked,
                               prior_entries=prior or None)
    differences = differences_from_pack_checks(result, files)
    if report_path is not None:
        _write_own_report(report_path, files, result)
    if fmt == "json":
        click.echo(json.dumps({**result.to_dict(), "check_differences": differences}, indent=2))
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
        if result.period is not None:
            click.echo(f"Period     : {result.period['from']} to {result.period['until']}")
        click.echo(f"Result     : {'VERIFIED' if result.verified else 'FAILED'}")
        for f in result.failures:
            click.echo(f"  - {f['file'] or '-'} #{f['store_sequence']}: {f['reason']} {f['detail']}".rstrip())
        unanchored = [w for w in result.warnings if w["reason"] == "cited_entry_unanchored"]
        for w in result.warnings:
            if w["reason"] != "cited_entry_unanchored":
                click.echo(f"  ~ {w['file'] or '-'} #{w['store_sequence']}: {w['reason']} {w['detail']}".rstrip())
        if unanchored:
            click.echo(f"  ~ {len(unanchored)} cited entries are covered by no prior pack and no held anchor "
                       "(cited_entry_unanchored): their signatures verify, their place in the store is not proven")
        for d in result.report_differences:
            click.echo(f"  ! report.md line {d['line']}: pack {d['pack']!r}, rendered {d['verifier']!r}")
        for d in differences:
            click.echo(f"  ! differs from the pack's own checks: {d['field']}: pack {d['pack']}, here {d['verifier']}")
    if not result.verified:
        raise SystemExit(1)


def _write_own_report(path: Path, files: dict[str, bytes], result: Any) -> None:
    """The report rendered from this verification: its own checks, the pack's verified entries."""
    from ..models.audit_pack import ENTRIES_FILE, STATES_FILE
    from ..workflows.audit_pack import _events

    try:
        manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
        entries = _events(files[ENTRIES_FILE])
        states = json.loads(files.get(STATES_FILE, b"{}"))
    except (KeyError, ValueError) as exc:
        raise click.ClickException(f"--report: the pack cannot be rendered ({exc})") from exc
    text = render_report(manifest=report_header(manifest), entries=entries,
                         checks={"verified": result.verified, "failures": result.failures, "counts": result.counts},
                         states=states.get("states") or {}, notices=states.get("notices") or {})
    text = text.replace("Verified by the Network Authority when it wrote the pack, against its own anchors",
                        "Verified by this verifier, from the root key and the anchors it holds")
    path.write_text(text, encoding="utf-8", newline="\n")


@audit.command("archive")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--to", "to_dir", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Immutable storage: a directory (for example a mounted bucket with object lock).")
@click.option("--until-sequence", type=int, default=None, help="Archive through the last anchor at or before it.")
@click.option("--until", default=None, help="... or through the last anchor signed at or before this time.")
@click.option("--older-than-days", type=click.IntRange(1), default=None,
              help="Prune only entries older than this (default: everything the archive covers that may go).")
@click.option("--prune/--no-prune", default=True, show_default=True, help="Prune the store through the archive.")
@click.option("--anchor", "root_key", default=None,
              help="The root public key to verify the pack read back from (default: the pack's genesis block's).")
@click.option("--force", is_flag=True, default=False,
              help="Record the archive even when the pack read back does not verify (the NA still refuses a "
                   "pack whose own checks failed).")
@_operator_options
def archive(na_endpoint: str, to_dir: Path, until_sequence: int | None, until: str | None,
            older_than_days: int | None, prune: bool, root_key: str | None, force: bool, config_path: str | None,
            operator_key: str | None, operator_key_id: str) -> None:
    """Archive the store: write a pack to immutable storage, read it back, verify it, record it, prune through it.

    The pack runs from the end of the last archive (or the store's start) to
    the last anchor. Nothing is recorded or pruned unless every file was
    written and read back matching the manifest the NA signed, and the pack
    read back verifies (``audit verify``, with the NA's anchors and executor
    keys; ``--force`` records it anyway). Needs a privileged key.
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
    # v1.5.0 review fixes: the pack read back must verify, as an auditor will verify it.
    read_back = read_pack_dir(target)
    try:
        root = public_key_value(root_key) if root_key else str(json.loads(read_back[GENESIS_FILE])["root_public_key"])
    except (KeyError, ValueError) as exc:
        raise click.ClickException(f"The pack read back has no readable genesis block ({exc}); nothing was "
                                   "recorded or pruned") from exc
    anchors = _fetch_anchors(base, key)
    keys = _admin_call(base, "GET", "/admin/evidence/executor-keys", {}, key, label="Executor keys")
    checked = verify_audit_pack(read_back, root_public_key=root, held_anchors=anchors,
                                executor_keys=_executor_key_rows(keys.get("executor_keys", [])))
    if not checked.verified:
        reasons = ", ".join(checked.reasons())
        if not force:
            raise click.ClickException(f"The pack read back from {target} does not verify ({reasons}). Nothing was "
                                       "recorded or pruned; --force records it anyway.")
        click.echo(f"WARNING: the pack read back does not verify ({reasons}); recording it (--force).", err=True)
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
