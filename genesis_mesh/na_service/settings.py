"""Network Authority settings, read once from the environment (v0.60).

With none of the v0.60 variables set, the NA behaves exactly as v0.59: SQLite
at ``DB_PATH``, the key file at ``NA_PRIVATE_KEY_FILE``, in-memory rate limits.

| variable | default | effect |
|---|---|---|
| ``DATABASE_URL`` | unset | ``postgresql://...`` stores state in shared PostgreSQL |
| ``NA_HA_MODE`` | ``off`` | ``on`` refuses to start unless PostgreSQL, a non-file key provider and the shared rate limiter are configured |
| ``NA_KEY_PROVIDER`` | ``file`` | ``file``, ``env`` or ``azure-keyvault`` |
| ``RATE_LIMIT_STORE`` | backend default | ``memory`` or ``database`` |
| ``NA_ADMIN_LEGACY_SIGNATURES`` | ``reject`` | ``accept`` allows version 1 admin signatures for a migration window (v1.0.2) |
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .key_provider import KeyProviderConfig
from .rate_limit import RateLimits


@dataclass(frozen=True)
class NASettings:
    genesis_file: str
    key: KeyProviderConfig
    db_path: str = "genesis_mesh_na.db"
    database_url: Optional[str] = None
    ha_mode: str = "off"
    rate_limit_store: Optional[str] = None
    operator_public_keys: dict[str, str] = field(default_factory=dict)
    operator_key_tiers: dict[str, str] = field(default_factory=dict)
    renewal_grace_seconds: int = 900
    boundary_policy_enforcement: str = "optional"
    evidence_store: str = "off"
    max_request_bytes: int = 2 * 1024 * 1024
    proxy_hops: int = 1
    rate_limits: RateLimits = field(default_factory=RateLimits)
    admin_legacy_signatures: str = "reject"


def _json_object(env: Mapping[str, str], name: str) -> dict[str, str]:
    raw = env.get(name)
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return {str(k): str(v) for k, v in value.items()}


def load_settings(env: Optional[Mapping[str, str]] = None) -> NASettings:
    """Read the NA configuration from ``env`` (the process environment by default)."""
    e = os.environ if env is None else env
    key_id = e.get("NA_KEY_ID", "na-2025-q1")
    key = KeyProviderConfig(
        provider=e.get("NA_KEY_PROVIDER", "file"),
        key_id=key_id,
        key_file=e.get("NA_PRIVATE_KEY_FILE"),
        seed_env_var=e.get("NA_KEY_SEED_ENV", "NA_PRIVATE_KEY_SEED"),
        vault_url=e.get("AZURE_KEY_VAULT_URL"),
        secret_name=e.get("NA_KEY_SECRET_NAME"),
    )
    return NASettings(
        genesis_file=e["GENESIS_FILE"],
        key=key,
        db_path=e.get("DB_PATH", "genesis_mesh_na.db"),
        database_url=e.get("DATABASE_URL") or None,
        ha_mode=e.get("NA_HA_MODE", "off"),
        rate_limit_store=e.get("RATE_LIMIT_STORE") or None,
        operator_public_keys=_json_object(e, "OPERATOR_PUBLIC_KEYS_JSON"),
        operator_key_tiers=_json_object(e, "OPERATOR_KEY_TIERS_JSON"),
        renewal_grace_seconds=int(e.get("RENEWAL_GRACE_SECONDS", "900")),
        boundary_policy_enforcement=e.get("BOUNDARY_POLICY_ENFORCEMENT", "optional"),
        evidence_store=e.get("EVIDENCE_STORE", "off"),
        max_request_bytes=int(e.get("NA_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))),
        proxy_hops=_proxy_hops(e.get("NA_PROXY_HOPS", "1")),
        rate_limits=RateLimits(
            admin=int(e.get("NA_RATE_LIMIT_ADMIN_PER_MINUTE", "30")),
            verify=int(e.get("NA_RATE_LIMIT_VERIFY_PER_MINUTE", "60")),
            evidence=int(e.get("NA_RATE_LIMIT_EVIDENCE_PER_MINUTE", "120")),
            read=int(e.get("NA_RATE_LIMIT_READ_PER_MINUTE", "120")),
        ),
        admin_legacy_signatures=e.get("NA_ADMIN_LEGACY_SIGNATURES", "reject"),
    )


def _proxy_hops(raw: str) -> int:
    hops = int(raw)
    if hops < 0:
        raise ValueError("NA_PROXY_HOPS must be 0 or more")
    return hops
