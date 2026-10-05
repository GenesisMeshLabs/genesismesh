"""Membership attestation and revocation-feed commands, one sovereign at a time.

Each command acts on one Network Authority with that sovereign's own operator
key, so two independent operators can run a cross-sovereign flow without
either holding the other's keys (v1.0.2):

* the issuing operator: ``attestation issue`` and ``attestation revoke``;
* anyone: ``attestation verify-with-treaty`` against the accepting NA;
* the accepting operator: ``treaty import-feed``, which verifies the issuer's
  signed revocation feed under the key its own treaty pinned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import requests

from .support import (
    _admin_signer_from_inputs,
    _parse_claims,
    _request_json,
    _require_positive_int,
    _signed_admin_headers,
    _validate_cli_roles,
    ensure_parent,
)
from .treaty_ops import treaty

SIGNER_OPTIONS = [
    click.option("--config", "config_path", default=None, help="Config for operator signing."),
    click.option("--operator-key", default=None, help="This sovereign's operator private key."),
    click.option("--operator-key-id", default="operator-local", help="Operator key ID."),
]


def _signer_options(func):
    for option in reversed(SIGNER_OPTIONS):
        func = option(func)
    return func


def _load_json_file(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"Cannot read {label} from {path}: {exc}") from exc


def _admin_post(na_endpoint: str, path: str, body: dict[str, Any], signer, *, label: str,
                expected_status: int = 200) -> dict[str, Any]:
    key_id, key_path = signer
    base = na_endpoint.rstrip("/")
    return _request_json(
        requests.Session(), "POST", f"{base}{path}",
        expected_status=expected_status, label=label, json=body,
        headers=_signed_admin_headers(key_id, key_path, body, method="POST", base_url=base, path=path),
    )


@click.group("attestation")
def attestation() -> None:
    """Issue, revoke and verify membership attestations (one sovereign per command)."""


@attestation.command("issue")
@click.option("--na", "na_endpoint", required=True, help="The issuing sovereign's Network Authority.")
@click.option("--subject-id", required=True, help="Member identifier.")
@click.option("--role", "roles", multiple=True, required=True, help="Attested role. Repeatable.")
@click.option("--subject-public-key", default=None, help="Member public key (base64).")
@click.option("--claim", "claims", multiple=True, help="Attested claim as key=value. Repeatable.")
@click.option("--validity-hours", default=168, show_default=True, type=int, help="Validity window.")
@click.option("--output", default=None, help="Also write the signed attestation to this file.")
@_signer_options
def issue_attestation(na_endpoint: str, subject_id: str, roles: tuple[str, ...],
                      subject_public_key: str | None, claims: tuple[str, ...], validity_hours: int,
                      output: str | None, config_path: str | None, operator_key: str | None,
                      operator_key_id: str) -> None:
    """Issue a membership attestation signed by this sovereign's NA."""
    _require_positive_int("--validity-hours", validity_hours)
    body: dict[str, Any] = {
        "subject_id": subject_id,
        "roles": _validate_cli_roles(roles),
        "claims": _parse_claims(claims),
        "validity_hours": validity_hours,
    }
    if subject_public_key:
        body["subject_public_key"] = subject_public_key
    signed = _admin_post(
        na_endpoint, "/admin/attestations", body,
        _admin_signer_from_inputs(config_path, operator_key, operator_key_id),
        label="attestation issue", expected_status=201,
    )
    if output:
        ensure_parent(output).write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8")
    click.echo(json.dumps(signed, indent=2))


@attestation.command("revoke")
@click.option("--na", "na_endpoint", required=True, help="The issuing sovereign's Network Authority.")
@click.argument("attestation_id")
@click.option("--reason", default="unspecified", help="Revocation reason.")
@_signer_options
def revoke_attestation(na_endpoint: str, attestation_id: str, reason: str, config_path: str | None,
                       operator_key: str | None, operator_key_id: str) -> None:
    """Revoke an attestation this sovereign issued; it enters the signed feed."""
    result = _admin_post(
        na_endpoint, f"/admin/attestations/{attestation_id}/revoke", {"reason": reason},
        _admin_signer_from_inputs(config_path, operator_key, operator_key_id),
        label="attestation revoke",
    )
    click.echo(json.dumps(result, indent=2))


@attestation.command("verify-with-treaty")
@click.option("--na", "na_endpoint", required=True, help="The accepting sovereign's Network Authority.")
@click.option("--attestation", "attestation_path", required=True, help="Signed attestation JSON file.")
@click.option("--treaty", "treaty_path", required=True, help="The accepting sovereign's treaty JSON file.")
def verify_with_treaty(na_endpoint: str, attestation_path: str, treaty_path: str) -> None:
    """Ask the accepting NA whether its treaty accepts the attestation.

    Exits 0 when accepted, 1 otherwise. The answer names its trust basis.
    """
    attestation_doc = _load_json_file(attestation_path, "the attestation")
    treaty_doc = _load_json_file(treaty_path, "the treaty")
    treaty_doc = treaty_doc.get("treaty", treaty_doc) if isinstance(treaty_doc, dict) else treaty_doc
    result = _request_json(
        requests.Session(), "POST", f"{na_endpoint.rstrip('/')}/attestations/verify-with-treaty",
        label="treaty-backed verification",
        json={"attestation": attestation_doc, "treaty": treaty_doc},
    )
    click.echo(json.dumps(result, indent=2))
    if not result.get("accepted"):
        raise SystemExit(1)


@treaty.command("import-feed")
@click.option("--na", "na_endpoint", required=True, help="The accepting sovereign's Network Authority.")
@click.option("--from", "issuer_endpoint", default=None, help="Fetch the feed from the issuing sovereign's NA.")
@click.option("--feed", "feed_path", default=None, help="Signed revocation feed JSON file.")
@click.option("--expected-issuer", default=None, help="Refuse a feed from any other sovereign.")
@_signer_options
def import_feed(na_endpoint: str, issuer_endpoint: str | None, feed_path: str | None,
                expected_issuer: str | None, config_path: str | None, operator_key: str | None,
                operator_key_id: str) -> None:
    """Import an issuer's signed revocation feed into the accepting NA.

    The accepting NA verifies the feed under the keys its own treaty pinned for
    the issuer; this command never supplies a key of its own.
    """
    if bool(issuer_endpoint) == bool(feed_path):
        raise click.ClickException("Pass exactly one of --from or --feed.")
    if issuer_endpoint:
        feed = _request_json(
            requests.Session(), "GET", f"{issuer_endpoint.rstrip('/')}/sovereign-revocation-feed",
            label="issuer revocation feed",
        )
    else:
        feed = _load_json_file(str(feed_path), "the revocation feed")
    body: dict[str, Any] = {"feed": feed}
    if expected_issuer:
        body["expected_issuer_sovereign_id"] = expected_issuer
    result = _admin_post(
        na_endpoint, "/admin/sovereign-revocation-feeds/import", body,
        _admin_signer_from_inputs(config_path, operator_key, operator_key_id),
        label="revocation feed import",
    )
    click.echo(json.dumps(result, indent=2))
    if not result.get("accepted"):
        raise SystemExit(1)
