"""Remote sovereign proof and proof-bundle workflows."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..cli.support import (
    _request_json,
    _require_positive_int,
    _signed_admin_headers,
)


def run_remote_proof(
    *,
    acceptor_endpoint: str,
    issuer_endpoint: str,
    acceptor_signer: tuple[str, Path],
    issuer_signer: tuple[str, Path],
    role: str,
    subject_id: str,
    subject_public_key: str,
    claims: dict[str, str],
    validity_hours: int,
    operator_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the direct-recognition proof and return a redacted proof bundle.

    Raises ValueError on any unexpected step result.
    """
    _require_positive_int("--validity-hours", validity_hours)
    acceptor = acceptor_endpoint.rstrip("/")
    issuer = issuer_endpoint.rstrip("/")
    session = requests.Session()

    acceptor_genesis = _request_json(session, "GET", f"{acceptor}/genesis", label="acceptor genesis")
    issuer_genesis = _request_json(session, "GET", f"{issuer}/genesis", label="issuer genesis")
    acceptor_id = acceptor_genesis["network_name"]
    issuer_id = issuer_genesis["network_name"]
    issuer_public_key = issuer_genesis["network_authority"]["public_key"]

    attestation_body = {
        "subject_id": subject_id,
        "subject_public_key": subject_public_key,
        "roles": [role],
        "claims": claims,
        "validity_hours": validity_hours,
    }
    issuer_key_id, issuer_key_path = issuer_signer
    attestation = _request_json(
        session, "POST", f"{issuer}/admin/attestations",
        expected_status=201, label="issuer attestation issue",
        json=attestation_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, attestation_body),
    )

    treaty_body = {
        "subject_sovereign_id": issuer_id,
        "subject_public_keys": [issuer_public_key],
        "scope": {
            "allowed_roles": [role],
            "accepted_statuses": ["active"],
            "claims": claims,
        },
        "validity_hours": validity_hours,
        "metadata": {"proof": "remote-sovereign-proof", "subject_endpoint": issuer},
    }
    acceptor_key_id, acceptor_key_path = acceptor_signer
    treaty = _request_json(
        session, "POST", f"{acceptor}/admin/recognition-treaties",
        expected_status=201, label="acceptor treaty issue",
        json=treaty_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, treaty_body),
    )

    pre_revocation = _request_json(
        session, "POST", f"{acceptor}/attestations/verify-with-treaty",
        label="pre-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if not pre_revocation.get("accepted"):
        raise ValueError(f"Pre-revocation proof was rejected: {pre_revocation}")

    revoke_body = {"reason": "remote_sovereign_proof_revocation"}
    _request_json(
        session, "POST",
        f"{issuer}/admin/attestations/{attestation['attestation_id']}/revoke",
        label="issuer attestation revoke",
        json=revoke_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, revoke_body),
    )

    feed = _request_json(
        session, "GET",
        f"{issuer}/sovereign-revocation-feed?issuer_sovereign_id={issuer_id}",
        label="issuer revocation feed",
    )
    import_body = {
        "feed": feed,
        "issuer_public_keys": [issuer_public_key],
        "expected_issuer_sovereign_id": issuer_id,
    }
    imported = _request_json(
        session, "POST", f"{acceptor}/admin/sovereign-revocation-feeds/import",
        label="acceptor feed import",
        json=import_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, import_body),
    )
    if not imported.get("accepted"):
        raise ValueError(f"Revocation feed import was rejected: {imported}")

    post_revocation = _request_json(
        session, "POST", f"{acceptor}/attestations/verify-with-treaty",
        label="post-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if post_revocation.get("accepted"):
        raise ValueError("Post-revocation proof was still accepted")

    connectome = _request_json(session, "GET", f"{acceptor}/connectome.json", label="acceptor Connectome")
    trust_path = _request_json(
        session, "GET",
        f"{acceptor}/connectome/trust-path?from={acceptor_id}&to={issuer_id}",
        label="acceptor trust path",
    )

    return {
        "proof": "remote-sovereign-recognition-revocation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operators": operator_evidence or {
            "acceptor": {"operator_label": "unspecified", "operator_type": "unknown"},
            "issuer": {
                "operator_label": "unspecified",
                "operator_type": "unknown",
                "controls_keys": False,
                "controls_infrastructure": False,
            },
            "assistance_notes": [],
            "adoption_proof": False,
        },
        "acceptor": {
            "network_name": acceptor_id,
            "endpoint": acceptor,
            "na_public_key_prefix": acceptor_genesis["network_authority"]["public_key"][:24],
        },
        "issuer": {
            "network_name": issuer_id,
            "endpoint": issuer,
            "na_public_key_prefix": issuer_public_key[:24],
        },
        "attestation_id": attestation["attestation_id"],
        "treaty_id": treaty["treaty_id"],
        "feed_id": feed["feed_id"],
        "feed_sequence": feed["sequence"],
        "pre_revocation": {
            "accepted": pre_revocation["accepted"],
            "reason": pre_revocation["reason"],
        },
        "post_revocation": {
            "accepted": post_revocation["accepted"],
            "reason": post_revocation["reason"],
        },
        "trust_path": trust_path,
        "connectome_summary": connectome["summary"],
    }


def inspect_proof_bundle(
    bundle: dict[str, Any], *, connectome_artifact: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate the operator-safe proof summary emitted by proof remote."""
    errors: list[str] = []
    acceptor = bundle.get("acceptor", {})
    issuer = bundle.get("issuer", {})
    trust_path = bundle.get("trust_path", {})
    connectome = bundle.get("connectome_summary", {})
    pre_revocation = bundle.get("pre_revocation", {})
    post_revocation = bundle.get("post_revocation", {})

    proof_name = bundle.get("proof")
    acceptor_name = acceptor.get("network_name")
    issuer_name = issuer.get("network_name")

    if proof_name != "remote-sovereign-recognition-revocation":
        errors.append("unexpected proof type")
    for key in ("attestation_id", "treaty_id", "feed_id"):
        if not bundle.get(key):
            errors.append(f"missing {key}")
    if not acceptor_name:
        errors.append("missing acceptor network name")
    if not issuer_name:
        errors.append("missing issuer network name")
    if pre_revocation.get("accepted") is not True or pre_revocation.get("reason") != "accepted":
        errors.append("pre-revocation result is not accepted")
    if (
        post_revocation.get("accepted") is not False
        or post_revocation.get("reason") != "attestation_locally_revoked"
    ):
        errors.append("post-revocation result is not locally revoked")
    if trust_path.get("trusted") is not True:
        errors.append("trust path is not trusted")
    if trust_path.get("from") != acceptor_name or trust_path.get("to") != issuer_name:
        errors.append("trust path endpoints do not match acceptor/issuer")
    if int(trust_path.get("hop_count") or 0) < 1:
        errors.append("trust path has no hops")
    if int(connectome.get("sovereign_count") or 0) < 2:
        errors.append("connectome has fewer than two sovereigns")
    if int(connectome.get("active_edge_count") or 0) < 1:
        errors.append("connectome has no active recognition edge")
    if int(connectome.get("imported_revocation_count") or 0) < 1:
        errors.append("connectome has no imported revocation")
    if int(connectome.get("revoked_trust_material_count") or 0) < 1:
        errors.append("connectome has no revoked trust material")

    artifact_result: dict[str, Any] | None = None
    if connectome_artifact is not None:
        artifact_errors = connectome_artifact_errors(
            bundle=bundle,
            acceptor_name=acceptor_name,
            issuer_name=issuer_name,
            expected_summary=connectome,
            artifact=connectome_artifact,
        )
        errors.extend(artifact_errors)
        artifact_result = {"matched": not artifact_errors, "errors": artifact_errors}

    return {
        "valid": not errors,
        "errors": errors,
        "proof": proof_name or "unknown",
        "acceptor": acceptor_name or "unknown",
        "issuer": issuer_name or "unknown",
        "attestation_id": bundle.get("attestation_id") or "unknown",
        "treaty_id": bundle.get("treaty_id") or "unknown",
        "feed_id": bundle.get("feed_id") or "unknown",
        "feed_sequence": bundle.get("feed_sequence") or "unknown",
        "pre_revocation_reason": pre_revocation.get("reason") or "unknown",
        "post_revocation_reason": post_revocation.get("reason") or "unknown",
        "trust_path_reason": trust_path.get("reason") or "unknown",
        "trust_path_hops": trust_path.get("hop_count") or 0,
        "connectome": {
            "sovereign_count": int(connectome.get("sovereign_count") or 0),
            "active_edge_count": int(connectome.get("active_edge_count") or 0),
            "imported_revocation_count": int(connectome.get("imported_revocation_count") or 0),
            "revoked_trust_material_count": int(connectome.get("revoked_trust_material_count") or 0),
        },
        "connectome_artifact": artifact_result,
    }


def connectome_artifact_errors(
    *,
    bundle: dict[str, Any],
    acceptor_name: str | None,
    issuer_name: str | None,
    expected_summary: dict[str, Any],
    artifact: dict[str, Any],
) -> list[str]:
    """Return mismatches between a proof bundle and a Connectome artifact."""
    errors: list[str] = []
    artifact_summary = artifact.get("summary", {})
    for key in (
        "sovereign_count",
        "active_edge_count",
        "imported_revocation_count",
        "revoked_trust_material_count",
    ):
        expected = int(expected_summary.get(key) or 0)
        actual = int(artifact_summary.get(key) or 0)
        if actual != expected:
            errors.append(f"connectome {key} mismatch: expected {expected}, got {actual}")

    treaty_id = bundle.get("treaty_id")
    has_edge = any(
        edge.get("from") == acceptor_name
        and edge.get("to") == issuer_name
        and edge.get("treaty_id") == treaty_id
        for edge in artifact.get("recognition_edges", [])
    )
    if not has_edge:
        errors.append("connectome recognition edge missing for proof treaty")

    attestation_id = bundle.get("attestation_id")
    feed_id = bundle.get("feed_id")
    has_revoked_material = any(
        item.get("id") == attestation_id and item.get("feed_id") == feed_id
        for item in artifact.get("revoked_trust_material", [])
    )
    if not has_revoked_material:
        errors.append("connectome revoked trust material missing for proof attestation")

    return errors


def cleanup_proof_state(
    db_path: Path,
    backup_path: str | None,
    backup_dir: str | None,
) -> dict[str, Any]:
    """Back up a SQLite database and delete only cross-sovereign proof rows.

    Raises ValueError if the database is not found.
    """
    if not db_path.exists():
        raise ValueError(f"Database not found: {db_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if backup_path:
        backup = Path(backup_path)
    else:
        directory = Path(backup_dir) if backup_dir else db_path.parent
        backup = directory / f"{db_path.name}.backup-before-proof-cleanup-{timestamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)

    tables = [
        "imported_sovereign_revocations",
        "sovereign_revocation_feeds",
        "recognition_treaties",
        "membership_attestations",
    ]
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup))
        try:
            conn.backup(dest)
        finally:
            dest.close()
        with conn:
            for table in tables:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if not exists:
                    deleted[table] = 0
                    continue
                before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                deleted[table] = int(before)
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "backup_path": str(backup),
        "deleted_rows": deleted,
    }
