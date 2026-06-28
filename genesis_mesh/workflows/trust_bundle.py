"""Trust bundle export, validation, and loading workflows."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import requests

from ..cli.support import _request_json

BUNDLE_TYPE = "genesis-mesh.trust-bundle"
BUNDLE_VERSION = "v1"


def export_trust_bundle(
    *,
    session: requests.Session,
    endpoint: str,
    include_revocation_feed: bool = True,
) -> dict[str, Any]:
    """Fetch public material and build a trust bundle."""
    material = fetch_public_material(
        session=session,
        endpoint=endpoint,
        include_revocation_feed=include_revocation_feed,
    )
    metadata = material["sovereign_metadata"]
    genesis = material["genesis"]
    return {
        "bundle_type": BUNDLE_TYPE,
        "bundle_version": BUNDLE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_endpoint": endpoint.rstrip("/"),
        "sovereign_id": metadata.get("sovereign_id"),
        "network_version": metadata.get("network_version") or genesis.get("network_version"),
        "sovereign_metadata": metadata,
        "genesis": genesis,
        "recognition_policy": material["recognition_policy"],
        "revocation_feed": material["revocation_feed"],
        "connectome": {
            "summary": material["connectome"].get("summary", {}),
            "recognition_edges": material["connectome"].get("recognition_edges", []),
            "active_treaties": material["connectome"].get("active_treaties", []),
            "revoked_trust_material": material["connectome"].get("revoked_trust_material", []),
        },
        "endpoint_checks": {
            "healthz": _status_value(material["healthz"]),
            "readyz": _status_value(material["readyz"]),
        },
    }


def fetch_public_material(
    *,
    session: requests.Session,
    endpoint: str,
    include_revocation_feed: bool,
) -> dict[str, Any]:
    """Fetch the public endpoints that make up a trust bundle."""
    base = endpoint.rstrip("/")
    genesis = _fetch_required(session, f"{base}/genesis", "genesis")
    metadata = _fetch_required(session, f"{base}/sovereign.json", "sovereign metadata")
    sovereign_id = metadata.get("sovereign_id") or genesis.get("network_name")
    revocation_feed: dict[str, Any] = {"status": "skipped"}
    if include_revocation_feed and sovereign_id:
        revocation_feed = _fetch_optional(
            session,
            f"{base}/sovereign-revocation-feed?issuer_sovereign_id={sovereign_id}",
            "sovereign revocation feed",
        )

    return {
        "endpoint": base,
        "healthz": _fetch_required(session, f"{base}/healthz", "healthz"),
        "readyz": _fetch_required(session, f"{base}/readyz", "readyz"),
        "genesis": genesis,
        "sovereign_metadata": metadata,
        "connectome": _fetch_required(session, f"{base}/connectome.json", "Connectome"),
        "recognition_policy": _fetch_optional(
            session,
            f"{base}/recognition-policy",
            "recognition policy",
        ),
        "revocation_feed": revocation_feed,
    }


def load_trust_bundle(path: Path) -> dict[str, Any]:
    """Load a bundle JSON file; raise ValueError on parse failure."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read trust bundle: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Trust bundle is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Trust bundle JSON must be an object")
    return payload


def validate_trust_bundle(
    bundle: dict[str, Any],
    *,
    live_material: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Validate bundle structure, consistency, and optional live endpoint parity."""
    errors: list[str] = []
    warnings: list[str] = []

    if bundle.get("bundle_type") != BUNDLE_TYPE:
        errors.append(f"unsupported bundle_type: {bundle.get('bundle_type')!r}")
    if bundle.get("bundle_version") != BUNDLE_VERSION:
        errors.append(f"unsupported bundle_version: {bundle.get('bundle_version')!r}")

    for field in ("created_at", "source_endpoint", "sovereign_metadata", "genesis"):
        if field not in bundle:
            errors.append(f"missing required field: {field}")

    metadata = _dict_field(bundle, "sovereign_metadata", errors)
    genesis = _dict_field(bundle, "genesis", errors)
    if metadata and genesis:
        _validate_identity_consistency(metadata, genesis, errors)
        _validate_public_key_consistency(metadata, genesis, errors)

    if _contains_forbidden_key(bundle):
        errors.append("bundle contains private key, token, bearer, or credential-shaped fields")

    policy = bundle.get("recognition_policy")
    if isinstance(policy, dict) and policy.get("status") == "ok":
        payload = policy.get("payload")
        if not isinstance(payload, dict):
            errors.append("recognition_policy status is ok but payload is missing")
        elif payload.get("local_sovereign_id") not in (None, bundle.get("sovereign_id")):
            warnings.append("recognition policy local_sovereign_id differs from bundle sovereign_id")

    feed = bundle.get("revocation_feed")
    if isinstance(feed, dict) and feed.get("status") == "ok":
        payload = feed.get("payload")
        if not isinstance(payload, dict):
            errors.append("revocation_feed status is ok but payload is missing")
        elif payload.get("issuer_sovereign_id") != bundle.get("sovereign_id"):
            errors.append("revocation_feed issuer_sovereign_id differs from bundle sovereign_id")

    if live_material:
        _validate_live_material(bundle, live_material, errors)

    return {"errors": errors, "warnings": warnings}


def bundle_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return compact operator-facing bundle summary fields."""
    metadata = _typed_dict(bundle.get("sovereign_metadata"))
    genesis = _typed_dict(bundle.get("genesis"))
    na = _typed_dict(metadata.get("network_authority"))
    policy = _typed_dict(bundle.get("recognition_policy"))
    feed = _typed_dict(bundle.get("revocation_feed"))
    connectome = _typed_dict(bundle.get("connectome"))
    connectome_summary = _typed_dict(connectome.get("summary"))
    root_public_key = metadata.get("root_public_key") or genesis.get("root_public_key")
    return {
        "sovereign_id": metadata.get("sovereign_id") or genesis.get("network_name"),
        "endpoint": bundle.get("source_endpoint") or metadata.get("endpoint"),
        "network_version": metadata.get("network_version") or genesis.get("network_version"),
        "na_public_key_fingerprint": _fingerprint(na.get("public_key")),
        "na_valid_from": na.get("valid_from"),
        "na_valid_to": na.get("valid_to"),
        "root_public_key_fingerprint": _fingerprint(root_public_key),
        "policy_manifest": metadata.get("policy_manifest") or genesis.get("policy_manifest"),
        "recognition_policy_status": policy.get("status", "missing"),
        "revocation_feed_status": feed.get("status", "missing"),
        "revocation_feed_sequence": _revocation_sequence(feed),
        "recognition_edge_count": connectome_summary.get("recognition_edge_count", 0),
        "active_edge_count": connectome_summary.get("active_edge_count", 0),
        "active_treaty_count": len(connectome.get("active_treaties", [])),
    }


def bundle_hash(bundle: dict[str, Any]) -> str:
    """Return a deterministic hash of the bundle JSON."""
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bundle_endpoint(bundle: dict[str, Any]) -> str | None:
    """Return the endpoint embedded in a bundle if present."""
    endpoint = bundle.get("source_endpoint")
    return str(endpoint).rstrip("/") if endpoint else None


def validate_bundle_against_review(
    bundle: dict[str, Any],
    review: dict[str, Any],
    *,
    label: str,
) -> dict[str, list[str]]:
    """Validate bundle identity against an already-fetched sovereign review; raise ValueError on mismatch."""
    live_material = {
        "endpoint": review.get("endpoint"),
        "sovereign_metadata": {
            "sovereign_id": review.get("sovereign_id"),
            "network_version": review.get("network_version"),
            "network_authority": review.get("network_authority", {}),
            "root_public_key": review.get("root_public_key"),
            "policy_manifest": review.get("policy_manifest"),
        },
        "genesis": {
            "network_name": review.get("network_name"),
            "network_authority": review.get("network_authority", {}),
            "root_public_key": review.get("root_public_key"),
            "policy_manifest": review.get("policy_manifest"),
        },
    }
    report = validate_trust_bundle(bundle, live_material=live_material)
    if report["errors"]:
        details = "; ".join(report["errors"])
        raise ValueError(f"{label} trust bundle mismatch: {details}")
    return report


def fetch_bundle_from_endpoint(endpoint: str) -> dict[str, Any]:
    """Fetch a fresh bundle from an endpoint for internal callers."""
    return export_trust_bundle(
        session=requests.Session(),
        endpoint=endpoint,
        include_revocation_feed=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _typed_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


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


def _dict_field(bundle: dict[str, Any], field: str, errors: list[str]) -> dict[str, Any]:
    value = bundle.get(field)
    if not isinstance(value, dict):
        if field in bundle:
            errors.append(f"{field} must be an object")
        return {}
    return value


def _validate_identity_consistency(
    metadata: dict[str, Any], genesis: dict[str, Any], errors: list[str]
) -> None:
    metadata_id = metadata.get("sovereign_id")
    genesis_name = genesis.get("network_name")
    if not metadata_id:
        errors.append("sovereign_metadata.sovereign_id is required")
    if not genesis_name:
        errors.append("genesis.network_name is required")
    if metadata_id and genesis_name and metadata_id != genesis_name:
        errors.append("sovereign_metadata.sovereign_id differs from genesis.network_name")


def _validate_public_key_consistency(
    metadata: dict[str, Any], genesis: dict[str, Any], errors: list[str]
) -> None:
    metadata_key = (metadata.get("network_authority") or {}).get("public_key")
    genesis_key = (genesis.get("network_authority") or {}).get("public_key")
    if not metadata_key:
        errors.append("sovereign_metadata.network_authority.public_key is required")
    if not genesis_key:
        errors.append("genesis.network_authority.public_key is required")
    if metadata_key and genesis_key and metadata_key != genesis_key:
        errors.append("sovereign_metadata NA public key differs from genesis NA public key")


def _validate_live_material(
    bundle: dict[str, Any], live_material: dict[str, Any], errors: list[str]
) -> None:
    live_metadata = live_material.get("sovereign_metadata", {})
    live_genesis = live_material.get("genesis", {})
    summary = bundle_summary(bundle)
    live_id = live_metadata.get("sovereign_id") or live_genesis.get("network_name")
    if summary["sovereign_id"] != live_id:
        errors.append("bundle sovereign_id differs from live endpoint sovereign_id")
    live_key = (live_metadata.get("network_authority") or {}).get("public_key")
    bundle_key = ((bundle.get("sovereign_metadata") or {}).get("network_authority") or {}).get("public_key")
    if bundle_key != live_key:
        errors.append("bundle NA public key differs from live endpoint NA public key")
    live_endpoint = live_material.get("endpoint")
    if live_endpoint and bundle.get("source_endpoint") and bundle["source_endpoint"] != live_endpoint:
        errors.append("bundle source_endpoint differs from live endpoint")


def _contains_forbidden_key(value: Any) -> bool:
    forbidden = ("private_key", "operator_private_key", "na_private_key", "bearer", "credential", "password", "secret", "token")
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            if any(item in key_lower for item in forbidden):
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _status_value(payload: dict[str, Any]) -> str:
    return str(payload.get("status", "ok"))


def _fingerprint(public_key: Any) -> str | None:
    if not public_key:
        return None
    digest = hashlib.sha256(str(public_key).encode("utf-8")).hexdigest()
    return "sha256:" + digest[:24]


def _revocation_sequence(feed: dict[str, Any]) -> int | None:
    if feed.get("status") != "ok" or not isinstance(feed.get("payload"), dict):
        return None
    sequence = feed["payload"].get("sequence")
    return int(sequence) if isinstance(sequence, int) else None
