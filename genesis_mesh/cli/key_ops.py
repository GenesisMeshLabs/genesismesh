"""NA key succession and the NA host check (v1.5.0, Stage 4).

``na succession history`` saves the NA's public key history.
``na succession sign`` prepares the next key's succession record and signs it
with the root key, offline: it needs the saved history and the root private
key file, and never contacts the NA. ``na succession submit`` sends the
signed record with a privileged operator key; the NA countersigns it with its
outgoing key and records it. ``na reissue`` asks the NA to re-issue, under
the key that signs now, the records of a succeeded key that would outlive its
vouching horizon (1.8.0; the NA also does this on its own). ``na doctor``
checks an NA host against its settings file: the root key absent, the NA key
valid, nothing left to re-issue, archives required.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
import requests

from ..crypto import load_private_key, sign_model
from ..models.key_succession import KeySuccessionRecord
from ..trust.key_succession import valid_public_key, verify_key_history
from .support import _admin_signer_from_inputs, _request_json, _signed_admin_headers, public_key_value


@click.group("succession")
def succession() -> None:
    """NA key succession: the root key, kept offline, names the NA's next key."""


@succession.command("history")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="Where to save the key history (JSON).")
def history(na_endpoint: str, out_path: Path) -> None:
    """Save the NA's key history (GET /na/key-history) for the offline signing step."""
    body = _request_json(requests.Session(), "GET", f"{na_endpoint.rstrip('/')}/na/key-history",
                         label="Key history")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    keys = body.get("keys") or []
    click.echo(f"Key history of {body.get('sovereign_id')}: {len(keys)} key(s); saved to {out_path}")


def _listed_key_id(view: dict, public_key: str) -> str | None:
    """The key ID the saved view lists for a key: for the genesis key, the running NA's own (1.7.1)."""
    for key in view.get("keys") or []:
        if isinstance(key, dict) and key.get("public_key") == public_key and isinstance(key.get("key_id"), str):
            return key["key_id"]
    return None


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.BadParameter(f"not an ISO 8601 time: {value}") from exc
    if parsed.tzinfo is None:
        raise click.BadParameter("give a time with its offset, such as 2026-11-01T09:00:00Z")
    return parsed.astimezone(timezone.utc)


@succession.command("sign")
@click.option("--history", "history_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The key history saved with 'na succession history'.")
@click.option("--root-key", "root_key_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="The root private key file (offline).")
@click.option("--root-key-id", default="root", show_default=True, help="Key ID for the root signature.")
@click.option("--new-public-key", required=True, help="The new NA public key: base64 or a public key file.")
@click.option("--new-key-id", required=True, help="The new NA key's ID (NA_KEY_ID when the NA runs it).")
@click.option("--effective-at", default=None, help="When the new key takes effect (ISO 8601, UTC).")
@click.option("--effective-in", "effective_in", type=int, default=None,
              help="... or in this many seconds from now (at least 60 when it is submitted).")
@click.option("--valid-days", type=click.IntRange(1, 3653), default=365, show_default=True,
              help="How long the new key is valid after it takes effect (enforced).")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="Where to write the signed succession record.")
def sign(history_path: Path, root_key_path: str, root_key_id: str, new_public_key: str, new_key_id: str,
         effective_at: str | None, effective_in: int | None, valid_days: int, out_path: Path) -> None:
    """Prepare the NA's next key and sign it with the root key, offline.

    The saved history is verified from the root key first: a history that
    does not verify, or a root key that is not the genesis block's, is
    refused. Submit the output with 'na succession submit'; the NA signs it
    with its current key and the new key takes effect at --effective-at.

    \b
        genesis-mesh na succession sign --history history.json \\
            --root-key root.key --new-public-key na-2.pub --new-key-id na-2027 \\
            --effective-at 2026-11-01T09:00:00Z --valid-days 365 --out succession.json
    """
    if (effective_at is None) == (effective_in is None):
        raise click.UsageError("give --effective-at or --effective-in")
    data = json.loads(history_path.read_text(encoding="utf-8"))
    root = load_private_key(root_key_path)
    root_public = base64.b64encode(bytes(root.verify_key)).decode("ascii")
    result = verify_key_history(data.get("genesis"), data.get("successions") or [], root_public)
    if not result.verified or result.history is None:
        failure = result.failures[0] if result.failures else {"reason": "invalid", "key_sequence": None}
        raise click.ClickException(
            f"The key history does not verify with this root key: key {failure['key_sequence']} {failure['reason']}"
        )
    new_key = public_key_value(new_public_key)
    if not valid_public_key(new_key):
        raise click.ClickException("--new-public-key is not a base64 Ed25519 public key")
    if new_key == root_public or new_key in result.history.all_keys():
        raise click.ClickException("--new-public-key is the root key or a key the history already held")
    history = result.history
    current = history.keys[-1]
    now = datetime.now(timezone.utc)
    effective = _parse_time(effective_at) if effective_at else now + timedelta(seconds=effective_in or 0)
    record = KeySuccessionRecord(
        sovereign_id=history.sovereign_id, key_sequence=current.key_sequence + 1,
        previous_key_id=current.key_id or _listed_key_id(data, current.public_key) or f"na-key-{current.key_sequence}",
        previous_public_key=current.public_key,
        previous_succession_digest=history.successions[-1].digest() if history.successions else None,
        new_key_id=new_key_id, new_public_key=new_key, effective_at=effective.replace(microsecond=0),
        new_valid_to=(effective + timedelta(days=valid_days)).replace(microsecond=0),
        issued_at=now.replace(microsecond=0),
    )
    signed = record.model_copy(update={"signatures": [sign_model(record, root, root_key_id)]})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(signed.to_wire(), indent=2, sort_keys=True) + "\n", encoding="utf-8",
                        newline="\n")
    click.echo(f"Succession {signed.succession_id}: key {signed.key_sequence} ({new_key_id}) takes effect at "
               f"{signed.effective_at.isoformat()} and is valid until {signed.new_valid_to.isoformat()}.")
    click.echo(f"Signed with the root key; written to {out_path}. Have the new key prove it is held "
               "('na succession prove'), then submit it with 'na succession submit'.")


@succession.command("prove")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The record 'na succession sign' wrote.")
@click.option("--new-key", "new_key_path", default=None, type=click.Path(exists=True, dir_okay=False),
              help="The new NA private key file.")
@click.option("--env-file", "env_file", default=None, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="... or the settings file of the NA that will run the new key (its key provider is used).")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="Where to write the record with the new key's signature.")
def prove(file_path: Path, new_key_path: str | None, env_file: Path | None, out_path: Path) -> None:
    """Sign the succession with the new NA key: the proof that the new key exists and is held.

    Run it where the new key lives (a key file, or the key provider of the
    NA settings that will use it). The NA refuses a succession without it.
    """
    from ..trust.key_succession import sign_succession

    if (new_key_path is None) == (env_file is None):
        raise click.UsageError("give --new-key or --env-file")
    record = KeySuccessionRecord.model_validate_json(file_path.read_text(encoding="utf-8"))
    if env_file is not None:
        from ..na_service.key_provider import KeyProviderError, load_signer
        from ..na_service.settings import load_settings
        from .env_file import EnvFileError, read_env_file

        try:
            key: Any = load_signer(load_settings(read_env_file(env_file)).key)
        except (EnvFileError, ValueError, KeyError, KeyProviderError) as exc:
            raise click.ClickException(f"{env_file}: {exc}") from exc
        public = key.public_key_b64
    else:
        key = load_private_key(new_key_path or "")
        public = base64.b64encode(bytes(key.verify_key)).decode("ascii")
    if public != record.new_public_key:
        raise click.ClickException("this key is not the new key the succession names")
    signed = sign_succession(record, key, record.new_key_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(signed.to_wire(), indent=2, sort_keys=True) + "\n", encoding="utf-8",
                        newline="\n")
    click.echo(f"Signed by the new key {record.new_key_id}; written to {out_path}. Submit it with "
               "'na succession submit'.")


@succession.command("submit")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The record 'na succession sign' wrote.")
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False, path_type=Path),
              help="Where to write the countersigned record.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key (privileged tier).")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
def submit(na_endpoint: str, file_path: Path, out_path: Path | None, config_path: str | None,
           operator_key: str | None, operator_key_id: str) -> None:
    """Record a root-signed succession: the NA countersigns it with its current key.

    Restart the NA with the new key at the time the record names (set
    NA_PRIVATE_KEY_FILE and NA_KEY_ID): from then on the old key signs
    nothing, and the NA refuses to start with it.
    """
    record = json.loads(file_path.read_text(encoding="utf-8"))
    base = na_endpoint.rstrip("/")
    path = "/admin/na/succession"
    body: dict[str, Any] = {"succession": record}
    key_id, key_path = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    headers = _signed_admin_headers(key_id, key_path, body, method="POST", base_url=base, path=path)
    result = _request_json(requests.Session(), "POST", f"{base}{path}", json=body, headers=headers,
                           expected_status=201, label="Succession")
    signed = result["succession"]
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    click.echo(f"Recorded: key {signed['key_sequence']} ({signed['new_key_id']}) takes effect at "
               f"{signed['effective_at']}. Restart the NA with the new key then; the old key signs nothing after it.")


@click.command("reissue")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key (privileged tier).")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
def reissue(na_endpoint: str, config_path: str | None, operator_key: str | None, operator_key_id: str) -> None:
    """Re-issue the records of a succeeded NA key now (1.8.0).

    After a succession takes effect, the NA re-issues under the new key the
    attestations and treaties the old key signed that are still valid past
    the old key's vouching horizon, and signs the active policy manifest
    again. It does this on its own, in batches; this command runs it at once
    and reports what is still due.
    """
    base = na_endpoint.rstrip("/")
    path = "/admin/na/reissue"
    body: dict[str, Any] = {}
    key_id, key_path = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    headers = _signed_admin_headers(key_id, key_path, body, method="POST", base_url=base, path=path)
    result = _request_json(requests.Session(), "POST", f"{base}{path}", json=body, headers=headers,
                           expected_status=200, label="Re-issue")
    done, due = result["reissued"], result["due"]
    manifest = f"; policy manifest {done['policy_manifest']} signed again" if done.get("policy_manifest") else ""
    click.echo(f"Re-issued {done['attestations']} attestations and {done['treaties']} treaties{manifest}.")
    if result.get("reissue_pending"):
        click.echo(f"Still due: {due['attestations']} attestations, {due['treaties']} treaties"
                   + (", the policy manifest" if due["policy_manifest"] else "") + ". Run it again.")
    else:
        click.echo("Nothing left to re-issue.")


@click.command("doctor")
@click.option("--env-file", "env_file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="The NA's settings file (the variables the NA container reads).")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def doctor(env_file: Path, fmt: str) -> None:
    """Check an NA host against its settings: root key custody, the NA key, archives.

    Fails when the root private key is found where the NA's files live (the
    directories of the genesis block, the NA key, the database and this
    settings file, their parent and three levels below, and the settings'
    variables), or when the NA key cannot sign now. Warns when the
    key stops signing within 30 days, when records of a succeeded key are
    not yet re-issued (1.8.0), and when retention may prune what was not
    archived (NA_RETENTION_REQUIRE_ARCHIVE=off).
    """
    from ..models import GenesisBlock
    from ..na_service.db import NADatabase
    from ..na_service.key_provider import KeyProviderError, load_signer, root_key_findings
    from ..na_service.services.reissue import due_records
    from ..na_service.settings import load_settings
    from .env_file import EnvFileError, read_env_file

    try:
        env = read_env_file(env_file)
        settings = load_settings(env)
    except (EnvFileError, ValueError, KeyError) as exc:
        raise click.ClickException(f"{env_file}: {exc}") from exc
    genesis = GenesisBlock(**json.loads(Path(settings.genesis_file).read_text(encoding="utf-8")))
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    try:
        signer = load_signer(settings.key)
    except KeyProviderError as exc:
        raise click.ClickException(f"{env_file}: {exc}") from exc
    findings = root_key_findings(
        genesis.root_public_key, na_public_key=signer.public_key_b64,
        paths=(settings.genesis_file, settings.key.key_file, settings.db_path if not settings.database_url else None,
               env_file),
        environ={**os.environ, **env},
    )
    if findings:
        check("root_key_absent", "fail", "; ".join(findings) + ": move the root key offline (root key ceremony)")
    else:
        check("root_key_absent", "ok", "the root private key is not where the NA's files live")
    if settings.deployment != "managed":
        check("deployment", "warn", "NA_DEPLOYMENT is local: the NA does not refuse to start with the root key "
                                    "on its host; set NA_DEPLOYMENT=managed in production")
    else:
        check("deployment", "ok", "NA_DEPLOYMENT=managed")
    db = NADatabase(settings.db_path, database_url=settings.database_url)
    try:
        rows = db.na_key_history_rows() if "na_key_history" in db.table_names() else []
        successions = [json.loads(r["succession_json"]) for r in rows[1:]]
        result = verify_key_history(genesis.model_dump(mode="json"), successions)
        due = None
        if result.verified and result.history is not None:
            key = result.history.key_for(signer.public_key_b64)
            now = datetime.now(timezone.utc)
            if key is not None and key.signs_at(now):
                due = due_records(db, result.history, genesis.network_name, key, now)
    finally:
        db.close()
    if not result.verified or result.history is None:
        check("na_key", "fail", f"the key history does not verify: {result.failures}")
    else:
        key = result.history.key_for(signer.public_key_b64)
        now = datetime.now(timezone.utc)
        if key is None:
            check("na_key", "fail", "the NA key is neither the genesis key nor one a succession named")
        elif not key.signs_at(now):
            check("na_key", "fail", f"NA key {key.key_sequence} cannot sign now (succeeded, expired or not yet "
                                    "effective): see /na/key-history")
        else:
            ends = [t for t in (key.succeeded_at, key.valid_to if key.valid_to_enforced else None) if t is not None]
            if ends and min(ends) - now < timedelta(days=30):
                check("na_key", "warn", f"NA key {key.key_sequence} stops signing at {min(ends).isoformat()}: "
                                        "succeed it before then")
            else:
                note = "" if key.valid_to_enforced else " (the genesis key's valid_to is not enforced)"
                check("na_key", "ok", f"NA key {key.key_sequence} of {len(result.history.keys)} signs now{note}")
    if due is not None and due.pending:
        summary = due.summary()["due"]
        check("reissue", "warn", f"records of a succeeded key not yet re-issued: {summary['attestations']} "
                                 f"attestations, {summary['treaties']} treaties"
                                 + (", the policy manifest" if summary["policy_manifest"] else "")
                                 + ": start the NA with the current key, or run 'genesis-mesh na reissue'")
    elif due is not None:
        check("reissue", "ok", "nothing a key succession left is due for re-issue")
    if settings.retention_require_archive:
        check("retention_archive", "ok", "retention removes only what an archive covers")
    else:
        check("retention_archive", "warn", "NA_RETENTION_REQUIRE_ARCHIVE=off: retention may remove entries no "
                                           "archive holds (local development only)")
    failed = any(c["status"] == "fail" for c in checks)
    if fmt == "json":
        click.echo(json.dumps({"ok": not failed, "checks": checks}, indent=2))
    else:
        for c in checks:
            click.echo(f"{c['status'].upper():<5} {c['check']}: {c['detail']}")
        click.echo("Result: " + ("FAILED" if failed else "OK"))
    if failed:
        raise SystemExit(1)
