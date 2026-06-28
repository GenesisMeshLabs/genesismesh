"""Federation bootstrap workflow: review a remote sovereign and issue a treaty."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from ..cli.support import (
    _request_json,
    _require_positive_int,
    _signed_admin_headers,
)
from .trust_bundle import bundle_endpoint, load_trust_bundle, validate_bundle_against_review


class FederationBootstrapVerificationError(Exception):
    """Raised when treaty issue succeeds but post-issue trust verification fails."""

    def __init__(self, result: dict[str, Any], message: str) -> None:
        super().__init__(message)
        self.result = result
        self.message = message


def run_federation_bootstrap(
    *,
    acceptor_endpoint: str,
    issuer_endpoint: str | None,
    acceptor_signer: tuple[str, Path] | None,
    roles: list[str],
    accepted_statuses: list[str],
    claims: dict[str, str],
    validity_hours: int,
    issue_treaty: bool,
    confirmed: bool,
    issuer_bundle_path: Path | None = None,
) -> dict[str, Any]:
    """Review a remote sovereign and optionally issue a direct treaty.

    Raises ValueError for invalid inputs.
    Raises FederationBootstrapVerificationError when treaty is issued but
    post-issue trust-path verification fails.
    When issue_treaty=True and confirmed=False, raises click.Abort so the
    CLI layer presents an interactive confirmation prompt.
    """
    _require_positive_int("--validity-hours", validity_hours)
    if issue_treaty and acceptor_signer is None:
        raise ValueError("Missing acceptor admin signer")

    acceptor = acceptor_endpoint.rstrip("/")
    issuer_bundle = load_trust_bundle(issuer_bundle_path) if issuer_bundle_path else None
    bundled_endpoint = bundle_endpoint(issuer_bundle) if issuer_bundle else None
    if issuer_endpoint is None and bundled_endpoint is None:
        raise ValueError("Missing issuer. Pass --issuer or --issuer-bundle.")
    issuer = (issuer_endpoint or bundled_endpoint or "").rstrip("/")
    if issuer_bundle and bundled_endpoint and issuer_endpoint and issuer != bundled_endpoint:
        raise ValueError(
            f"--issuer {issuer!r} does not match --issuer-bundle endpoint {bundled_endpoint!r}"
        )
    session = requests.Session()

    acceptor_review = _review_sovereign(session, acceptor, "acceptor")
    issuer_review = _review_sovereign(session, issuer, "issuer")
    issuer_bundle_report = None
    if issuer_bundle:
        issuer_bundle_report = validate_bundle_against_review(
            issuer_bundle, issuer_review, label="issuer"
        )
    issuer_id = issuer_review["sovereign_id"]
    acceptor_id = acceptor_review["sovereign_id"]
    issuer_public_key = issuer_review["network_authority"]["public_key"]

    treaty_body = _treaty_preview(
        issuer_id=issuer_id,
        issuer_public_key=issuer_public_key,
        issuer_endpoint=issuer,
        roles=roles,
        accepted_statuses=accepted_statuses,
        claims=claims,
        validity_hours=validity_hours,
    )

    result: dict[str, Any] = {
        "workflow": "federation-bootstrap",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not issue_treaty,
        "acceptor": _public_review_summary(acceptor_review),
        "issuer": _public_review_summary(issuer_review),
        "treaty_preview": _redacted_treaty_preview(treaty_body),
    }
    if issuer_bundle:
        result["issuer_bundle"] = {
            "path": str(issuer_bundle_path),
            "bundle_version": issuer_bundle.get("bundle_version"),
            "created_at": issuer_bundle.get("created_at"),
            "validation": issuer_bundle_report,
        }

    if not issue_treaty:
        return result

    if not confirmed:
        import click
        click.confirm(
            f"Issue direct-recognition treaty from {acceptor_id} to {issuer_id}?",
            abort=True,
        )

    assert acceptor_signer is not None
    key_id, key_path = acceptor_signer
    treaty = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/recognition-treaties",
        expected_status=201,
        label="acceptor treaty issue",
        json=treaty_body,
        headers=_signed_admin_headers(key_id, key_path, treaty_body),
    )
    result.update(
        {
            "treaty_id": treaty["treaty_id"],
            "treaty_status": treaty["status"],
            "verification": {"status": "pending"},
        }
    )
    trust_path = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome/trust-path?{urlencode({'from': acceptor_id, 'to': issuer_id})}",
        label="trust path verification",
    )
    if not trust_path.get("trusted"):
        result["trust_path"] = trust_path
        result["verification"] = {
            "status": "failed",
            "reason": trust_path.get("reason"),
            "message": "Treaty was persisted but post-issue trust-path verification failed.",
            "cleanup_hint": (
                "Inspect or revoke the persisted treaty before rerunning: "
                f"genesis-mesh treaty revoke --na {acceptor} {treaty['treaty_id']} "
                "--reason bootstrap_verification_failed"
            ),
        }
        raise FederationBootstrapVerificationError(
            result,
            "Treaty was persisted but trust path verification failed "
            f"(treaty_id={treaty['treaty_id']}, reason={trust_path.get('reason')}). "
            "Inspect or revoke the treaty before rerunning.",
        )

    connectome = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome.json",
        label="acceptor Connectome",
    )
    result.update(
        {
            "treaty_id": treaty["treaty_id"],
            "treaty_status": treaty["status"],
            "trust_path": trust_path,
            "verification": {"status": "passed", "reason": trust_path.get("reason")},
            "connectome_summary": connectome["summary"],
        }
    )
    return result


def write_evidence(output: Path, result: dict[str, Any]) -> None:
    """Write bootstrap evidence to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def _review_sovereign(session: requests.Session, endpoint: str, label: str) -> dict[str, Any]:
    healthz = _fetch_required(session, f"{endpoint}/healthz", f"{label} healthz")
    readyz = _fetch_required(session, f"{endpoint}/readyz", f"{label} readyz")
    genesis = _fetch_required(session, f"{endpoint}/genesis", f"{label} genesis")
    metadata = _fetch_required(session, f"{endpoint}/sovereign.json", f"{label} sovereign metadata")
    connectome = _fetch_required(session, f"{endpoint}/connectome.json", f"{label} Connectome")
    recognition_policy = _fetch_optional(session, f"{endpoint}/recognition-policy", f"{label} recognition policy")
    _validate_public_material(label, genesis, metadata)
    return {
        "endpoint": endpoint,
        "sovereign_id": metadata["sovereign_id"],
        "network_name": genesis["network_name"],
        "network_version": metadata.get("network_version"),
        "network_authority": metadata["network_authority"],
        "root_public_key": metadata.get("root_public_key"),
        "policy_manifest": metadata.get("policy_manifest"),
        "checks": {
            "healthz": _check_summary(healthz),
            "readyz": _check_summary(readyz),
            "genesis": {"status": "ok"},
            "sovereign_metadata": {"status": "ok"},
            "recognition_policy": _optional_summary(recognition_policy),
            "connectome": {"status": "ok", "summary": connectome.get("summary", {})},
        },
    }


def _fetch_required(session: requests.Session, url: str, label: str) -> dict[str, Any]:
    return _request_json(session, "GET", url, label=label)


def _fetch_optional(session: requests.Session, url: str, label: str) -> dict[str, Any]:
    try:
        response = session.get(url, timeout=10)
    except requests.RequestException as exc:
        return {"status": "unavailable", "reason": str(exc)}
    if response.status_code == 404:
        return {"status": "not_configured"}
    if not response.ok:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:500]}
        reason = payload.get("error") if isinstance(payload, dict) else None
        return {
            "status": "unavailable",
            "reason": f"{label} failed: {response.status_code} {reason or payload}",
        }
    try:
        return {"status": "ok", "payload": response.json()}
    except ValueError:
        return {"status": "invalid_json"}


def _validate_public_material(label: str, genesis: dict[str, Any], metadata: dict[str, Any]) -> None:
    genesis_name = genesis.get("network_name")
    metadata_id = metadata.get("sovereign_id")
    if not genesis_name or not metadata_id or genesis_name != metadata_id:
        raise ValueError(
            f"{label} public material mismatch: genesis network_name={genesis_name!r}, "
            f"sovereign_id={metadata_id!r}"
        )
    genesis_key = (genesis.get("network_authority") or {}).get("public_key")
    metadata_key = (metadata.get("network_authority") or {}).get("public_key")
    if not genesis_key or not metadata_key or genesis_key != metadata_key:
        raise ValueError(f"{label} public material mismatch: NA public keys differ")


def _treaty_preview(
    *,
    issuer_id: str,
    issuer_public_key: str,
    issuer_endpoint: str,
    roles: list[str],
    accepted_statuses: list[str],
    claims: dict[str, str],
    validity_hours: int,
) -> dict[str, Any]:
    return {
        "subject_sovereign_id": issuer_id,
        "subject_public_keys": [issuer_public_key],
        "scope": {
            "allowed_roles": roles,
            "accepted_statuses": accepted_statuses,
            "claims": claims,
        },
        "validity_hours": validity_hours,
        "metadata": {
            "workflow": "federation-bootstrap",
            "subject_endpoint": issuer_endpoint,
        },
    }


def _public_review_summary(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": review["endpoint"],
        "sovereign_id": review["sovereign_id"],
        "network_version": review["network_version"],
        "na_public_key_prefix": review["network_authority"]["public_key"][:24],
        "na_valid_to": review["network_authority"].get("valid_to"),
        "policy_manifest": review.get("policy_manifest"),
        "checks": review["checks"],
    }


def _redacted_treaty_preview(treaty_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_sovereign_id": treaty_body["subject_sovereign_id"],
        "subject_public_key_prefixes": [
            pk[:24] for pk in treaty_body["subject_public_keys"]
        ],
        "scope": treaty_body["scope"],
        "validity_hours": treaty_body["validity_hours"],
        "metadata": treaty_body["metadata"],
    }


def _check_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": payload.get("status", "ok")}


def _optional_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "ok":
        return payload
    policy = payload.get("payload", {})
    return {
        "status": "ok",
        "local_sovereign_id": policy.get("local_sovereign_id"),
        "recognized_issuer_count": len(policy.get("recognized_issuers", [])),
    }
