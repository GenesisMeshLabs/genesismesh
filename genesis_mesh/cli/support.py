"""Shared support helpers for operational CLI commands."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import requests  # noqa: F401  (tests patch support.requests.Session)

from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..node.node import MeshNode
from ..node.runtime import MeshNodeRuntime
# Calls to a Network Authority live in workflows/ (workflows must not import
# cli/); CLI commands keep importing them from here.
from ..workflows.remote import (  # noqa: F401
    _ADMIN_AUDIENCES_META_KEY,
    _admin_audience,
    _api_error_message,
    _request_json,
    _require_positive_int,
    _signed_admin_headers,
)
from .config import get_config_value, load_config

VALID_ROLE_PREFIXES = (
    "role:anchor",
    "role:bridge",
    "role:client",
    "role:operator",
    "role:service:",
)


def _load_cli_config(config_path: str | None = None, required: bool = False) -> dict[str, Any]:
    """Load CLI config and translate missing-file errors into Click errors."""
    try:
        return load_config(config_path, required=required)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

def _parse_anchor(anchor: str) -> tuple[str, str]:
    """Parse an anchor string into ID and endpoint."""
    if ":" not in anchor:
        raise click.ClickException("Anchor must use id:endpoint format")
    anchor_id, endpoint = anchor.split(":", 1)
    return anchor_id, endpoint

def _normalize_role(role: str) -> str:
    """Return a canonical role string."""
    return role if role.startswith("role:") else f"role:{role}"

def _validate_cli_roles(roles: tuple[str, ...] | list[str]) -> list[str]:
    """Normalize and validate role arguments before making an NA request."""
    normalized = [_normalize_role(role) for role in roles]
    invalid = [
        role for role in normalized
        if not any(role.startswith(prefix) for prefix in VALID_ROLE_PREFIXES)
    ]
    if invalid:
        allowed = "client, anchor, bridge, operator, service:<name>"
        raise click.ClickException(
            f"Invalid role: {invalid[0]}. Allowed roles are: {allowed}."
        )
    return normalized

def _load_genesis(path: Path) -> GenesisBlock:
    """Load a signed genesis block from disk."""
    with path.open("r", encoding="utf-8") as f:
        return GenesisBlock(**json.load(f))

def _load_existing_certificate(cert_path: Path, node: MeshNode) -> JoinCertificate | None:
    """Load a valid local certificate for a node if one exists."""
    if not cert_path.exists():
        return None

    cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
    if cert.node_public_key != node.node_keypair.public_key_b64:
        raise click.ClickException(
            f"Local certificate {cert_path} does not match the configured node key."
        )
    if not node._verify_join_certificate(cert):
        return None
    return cert

def _describe_unusable_certificate(cert_path: Path, node: MeshNode) -> str | None:
    """Return a user-facing reason that a local certificate cannot be reused."""
    if not cert_path.exists():
        return None

    try:
        cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
    except Exception:
        return f"Local certificate {cert_path} is malformed."

    if cert.node_public_key != node.node_keypair.public_key_b64:
        return f"Local certificate {cert_path} does not match the configured node key."

    now = datetime.now(timezone.utc)
    if cert.expires_at < now:
        return f"Local certificate {cert.cert_id} expired at {cert.expires_at.isoformat()}."
    if cert.issued_at > now:
        return f"Local certificate {cert.cert_id} is not valid until {cert.issued_at.isoformat()}."

    return f"Local certificate {cert.cert_id} could not be verified."

def _load_existing_policy(policy_path: Path, node: MeshNode) -> PolicyManifest | None:
    """Load a valid local policy manifest if one exists."""
    if not policy_path.exists():
        return None

    policy = PolicyManifest.model_validate_json(policy_path.read_text(encoding="utf-8"))
    if not node._verify_policy_manifest(policy):
        return None
    node.policy_manifest = policy
    return policy

def _required_config_path(config: dict[str, Any], section: str, key: str) -> Path:
    """Return a required config path or raise a click error."""
    value = get_config_value(config, section, key)
    if not value:
        raise click.ClickException(f"Missing [{section}].{key} in config")
    return Path(value)

def _admin_headers(
    config: dict[str, Any],
    body: dict[str, Any],
    *,
    method: str,
    base_url: str,
    path: str,
    query: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Create signed admin request headers from CLI config."""
    key_id = get_config_value(config, "operator", "key_id", "operator-local")
    key_path = _required_config_path(config, "paths", "operator_private_key")
    return _signed_admin_headers(
        key_id, key_path, body, method=method, base_url=base_url, path=path, query=query
    )

def _admin_signer_from_inputs(
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
) -> tuple[str, Path]:
    """Resolve an admin signing key from explicit options or a CLI config."""
    if operator_key:
        return operator_key_id, Path(operator_key)
    if not config_path:
        raise click.ClickException(
            "Missing admin signing key. Pass --operator-key, endpoint-specific "
            "operator key options, or endpoint-specific config."
        )
    config = _load_cli_config(config_path, required=True)
    key_id = get_config_value(config, "operator", "key_id", operator_key_id)
    return key_id, _required_config_path(config, "paths", "operator_private_key")

def _parse_claims(claims: tuple[str, ...]) -> dict[str, str]:
    """Parse repeated key=value claim options."""
    parsed: dict[str, str] = {}
    for item in claims:
        if "=" not in item:
            raise click.ClickException("--claim values must use key=value format")
        key, value = item.split("=", 1)
        if not key:
            raise click.ClickException("--claim keys must not be empty")
        parsed[key] = value
    return parsed

async def _run_runtime_forever(runtime: MeshNodeRuntime) -> None:
    """Start a runtime and keep it alive until cancelled."""
    await runtime.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runtime.stop()


def ensure_parent(path: str | Path) -> Path:
    """Return ``path`` with its directory created, for a command's output file (v1.0.2)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def public_key_value(value: str) -> str:
    """A base64 public key given inline or as a key file (``#`` comment lines ignored) (v1.0.2)."""
    path = Path(value)
    try:
        is_file = path.is_file()
    except (OSError, ValueError):
        is_file = False
    if is_file:
        return "".join(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    return value
