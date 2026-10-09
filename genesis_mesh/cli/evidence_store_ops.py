"""Evidence store CLI commands (v0.59): verify an exported evidence log offline.

v1.2.0 adds signed store anchors: ``evidence anchors fetch`` keeps a copy of
the NA's anchors in a directory the operator does not control, and
``verify-export --known-anchors`` checks an export against that copy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click
import requests

from ..models.evidence_store import StoreAnchor
from ..trust.evidence_store import (
    ExecutorKey,
    check_events_against_anchors,
    parse_export_lines,
    verify_evidence_events,
    verify_store_anchors,
)
from .support import _admin_signer_from_inputs, _request_json, _signed_admin_headers, public_key_value

ANCHOR_FILE_PREFIX = "anchor-"


@click.group("evidence")
def evidence() -> None:
    """Evidence store — verify exported decision and execution history offline."""


def load_anchors(path: str) -> list[StoreAnchor]:
    """Anchors from a directory written by ``anchors fetch``, or a JSON / JSON Lines file."""
    p = Path(path)
    try:
        if p.is_dir():
            raw: list[Any] = [
                json.loads(f.read_text(encoding="utf-8"))
                for f in sorted(p.glob(f"{ANCHOR_FILE_PREFIX}*.json"))
            ]
        else:
            text = p.read_text(encoding="utf-8").strip()
            if text.startswith("[") or text.startswith("{"):
                try:
                    data = json.loads(text)
                except ValueError:
                    data = [json.loads(line) for line in text.splitlines() if line.strip()]
            else:
                data = []
            if isinstance(data, dict):
                data = data.get("anchors", [data])
            raw = list(data)
        anchors = [StoreAnchor.model_validate(a) for a in raw]
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"Cannot read anchors from {path}: {exc}") from exc
    return sorted(anchors, key=lambda a: a.anchor_sequence)


@evidence.command("verify-export")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="gm.evidence.event JSON Lines from GET /admin/evidence/export.")
@click.option("--na-public-key", "na_keys", required=True, multiple=True,
              help="NA public key: base64 or path to a public key file. Repeatable.")
@click.option("--executor-keys", "executor_keys_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="JSON from GET /admin/evidence/executor-keys.")
@click.option("--known-anchors", "anchors_path", default=None, type=click.Path(exists=True),
              help="Anchors you hold: a directory from 'evidence anchors fetch', or a JSON file (v1.2.0).")
@click.option("--partial", is_flag=True,
              help="The export is a deliberate slice: anchors after its last entry are not a failure.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify_export(
    file_path: str, na_keys: tuple[str, ...], executor_keys_path: str,
    anchors_path: str | None, partial: bool, fmt: str,
) -> None:
    """Verify an evidence export: envelopes, store chain, signatures and chains.

    With --known-anchors, the export is also checked against anchors kept
    outside the Network Authority: a record removed or rewritten before an
    anchored position, or an export that stops before the newest anchor,
    fails.

    Example:

    \b
        genesis-mesh evidence verify-export \\
            --file export.jsonl --na-public-key <base64> \\
            --executor-keys executor-keys.json --known-anchors anchors/
    """
    try:
        events = parse_export_lines(Path(file_path).read_text(encoding="utf-8").splitlines())
    except ValueError as exc:
        raise click.ClickException(f"Export is malformed: {exc}") from exc
    raw_keys = json.loads(Path(executor_keys_path).read_text(encoding="utf-8"))
    rows = raw_keys.get("executor_keys", raw_keys) if isinstance(raw_keys, dict) else raw_keys
    keys = {
        r["key_id"]: ExecutorKey(
            key_id=r["key_id"], public_key=r["public_key"],
            executor_sovereign_id=r["executor_sovereign_id"], retired=bool(r.get("retired_at")),
        )
        for r in rows
    }
    na_public_keys = [public_key_value(k) for k in na_keys]
    result = verify_evidence_events(events, na_public_keys=na_public_keys, executor_keys=keys, contiguous=True)
    if anchors_path is not None:
        anchors = load_anchors(anchors_path)
        if not anchors:
            raise click.ClickException(f"No anchors found in {anchors_path}")
        chain = verify_store_anchors(anchors, na_public_keys=na_public_keys)
        for f in chain.failures:
            result.fail(None, f["reason"], f"anchor {f['anchor_sequence']} {f['detail']}".rstrip())
        check_events_against_anchors(events, anchors, result, partial=partial)
    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(f"Entries    : {result.checked_entries}")
        click.echo(f"Decisions  : {result.decisions}")
        click.echo(f"Executions : {result.executions}")
        if result.anchors is not None:
            a = result.anchors
            click.echo(f"Anchors    : {a['anchors_matched']} matched of {a['anchors_checked']}; "
                       f"anchored through #{a['anchored_through_sequence']}; "
                       f"{a['unanchored_entries']} entries after the last anchor")
        click.echo(f"Result     : {'VERIFIED' if result.verified else 'FAILED'}")
        for f in result.failures:
            click.echo(f"  - #{f['store_sequence']}: {f['reason']} {f['detail']}".rstrip())
    if not result.verified:
        raise SystemExit(1)


@evidence.group("anchors")
def anchors() -> None:
    """Signed store anchors — keep a copy outside the Network Authority (v1.2.0)."""


def _anchor_path(directory: Path, anchor: StoreAnchor) -> Path:
    return directory / f"{ANCHOR_FILE_PREFIX}{anchor.anchor_sequence:010d}.json"


def _same(a: StoreAnchor, b: StoreAnchor) -> bool:
    return a.to_wire() == b.to_wire()


def _write_anchor(directory: Path, anchor: StoreAnchor) -> None:
    """Write one anchor file atomically, never replacing an existing one.

    The file is written under a temporary name and hard-linked into place, so
    a crash never leaves a truncated anchor and an existing file is never
    replaced. An existing file holding the same anchor is accepted.
    """
    path = _anchor_path(directory, anchor)
    data = json.dumps(anchor.to_wire(), indent=2, sort_keys=True) + "\n"
    tmp = directory / f".{path.name}.{os.getpid()}.tmp"
    try:
        tmp.write_text(data, encoding="utf-8", newline="\n")
        try:
            os.link(tmp, path)
        except FileExistsError:
            existing = StoreAnchor.model_validate_json(path.read_text(encoding="utf-8"))
            if not _same(existing, anchor):
                raise click.ClickException(f"{path} holds a different anchor {anchor.anchor_sequence}") from None
            return
        except OSError:
            # A filesystem without hard links: exclusive create is still never a replacement.
            with open(path, "x", encoding="utf-8", newline="\n") as f:
                f.write(data)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


#: Anchors requested per page (the NA's maximum).
PAGE = 1000


@anchors.command("fetch")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--na-public-key", "na_keys", required=True, multiple=True,
              help="The NA public key you trust: base64 or a key file. Repeatable (key succession).")
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False),
              help="Directory that holds your copy of the anchors (created if missing).")
@click.option("--sovereign-id", default=None, help="Refuse anchors from any other sovereign.")
@click.option("--anchor-now", is_flag=True,
              help="Ask the NA to anchor its current head first, so recent entries are covered.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key (the read tier is enough).")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
def fetch_anchors(
    na_endpoint: str, na_keys: tuple[str, ...], out_dir: str, sovereign_id: str | None,
    anchor_now: bool, config_path: str | None, operator_key: str | None, operator_key_id: str,
) -> None:
    """Copy the NA's anchors into a directory you control.

    Every run reads all anchors the NA serves and compares each one with the
    copy you hold: if the NA serves a different anchor at any position you
    hold, or no longer serves one, nothing is written and the command fails.
    The NA's anchor history was rewritten or removed, and your copy is the
    evidence. Otherwise the whole set is checked (NA signature, unbroken
    chain) and missing positions are written, one file each; existing files
    are never replaced.

    Run it on a schedule with --anchor-now from a machine and storage the
    NA's operators cannot change: the schedule bounds how long a new record
    can be removed without detection.

    \b
        genesis-mesh evidence anchors fetch --na https://na.example \\
            --na-public-key na.pub --out /audit/anchors --anchor-now \\
            --operator-key auditor.key --operator-key-id auditor
    """
    base = na_endpoint.rstrip("/")
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    na_public_keys = [public_key_value(k) for k in na_keys]
    held = load_anchors(str(directory))
    key_id, key_path = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    session = requests.Session()
    path = "/admin/evidence/anchors"

    if anchor_now:
        resp = session.post(
            f"{base}{path}", json={}, timeout=20,
            headers=_signed_admin_headers(key_id, key_path, {}, method="POST", base_url=base, path=path),
        )
        if resp.status_code not in (200, 201):
            raise click.ClickException(f"Anchor request failed: {resp.status_code} {resp.text[:300]}")

    served: dict[int, StoreAnchor] = {}
    after = 0
    while True:
        query = {"after_anchor": str(after), "limit": str(PAGE)}
        page = _request_json(
            session, "GET", f"{base}{path}", params=query, label="Anchor listing",
            headers=_signed_admin_headers(key_id, key_path, {}, method="GET", base_url=base, path=path, query=query),
        )
        for raw in page.get("anchors", []):
            anchor = StoreAnchor.model_validate(raw)
            if anchor.anchor_sequence <= after or anchor.anchor_sequence in served:
                raise click.ClickException("The NA served anchors out of order; nothing was written.")
            served[anchor.anchor_sequence] = anchor
        nxt = page.get("next_after_anchor")
        if nxt is None:
            break
        if not isinstance(nxt, int) or nxt <= after:
            raise click.ClickException("The NA's anchor listing does not advance; nothing was written.")
        after = nxt

    for h in held:
        s = served.get(h.anchor_sequence)
        if s is None:
            raise click.ClickException(
                f"The NA no longer serves anchor {h.anchor_sequence}, which you hold: its anchor history "
                "was removed or the NA was restored from an older backup. Nothing was written; keep your "
                "copy as evidence (see the Evidence Anchors operations page)."
            )
        if not _same(s, h):
            raise click.ClickException(
                f"The NA serves a different anchor {h.anchor_sequence} than the one you hold: its anchor "
                "history was rewritten or the NA was restored from an older backup. Nothing was written; "
                "keep your copy as evidence (see the Evidence Anchors operations page)."
            )
    if served and min(served) != 1:
        raise click.ClickException(f"The NA does not serve anchors before {min(served)}; nothing was written.")
    ordered = [served[n] for n in sorted(served)]
    chain = verify_store_anchors(ordered, na_public_keys=na_public_keys,
                                 sovereign_id=sovereign_id or (held[0].sovereign_id if held else None))
    if not chain.verified:
        details = "; ".join(f"#{f['anchor_sequence']} {f['reason']}" for f in chain.failures[:5])
        raise click.ClickException(f"Anchors failed verification, nothing was written: {details}")
    held_sequences = {h.anchor_sequence for h in held}
    written = [a for a in ordered if a.anchor_sequence not in held_sequences]
    for anchor in written:
        _write_anchor(directory, anchor)
    if not ordered:
        click.echo("The NA has no anchors yet.")
        return
    latest = ordered[-1]
    refilled = sum(1 for a in written if held and a.anchor_sequence < max(held_sequences))
    note = f" ({refilled} missing position(s) refilled)" if refilled else ""
    click.echo(
        f"{len(written)} new anchor(s){note}; latest #{latest.anchor_sequence} covers store sequence "
        f"{latest.store_sequence} ({latest.anchored_at.isoformat()})"
    )
