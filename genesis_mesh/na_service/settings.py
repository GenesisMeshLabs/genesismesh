"""Network Authority settings, read once from the environment (v0.60).

With none of the v0.60 variables set, the NA behaves exactly as v0.59: SQLite
at ``DB_PATH``, the key file at ``NA_PRIVATE_KEY_FILE``, in-memory rate limits.

| variable | default | effect |
|---|---|---|
| ``DATABASE_URL`` | unset | ``postgresql://...`` stores state in shared PostgreSQL |
| ``NA_HA_MODE`` | ``off`` | ``on`` refuses to start unless PostgreSQL, a non-file key provider and the shared rate limiter are configured |
| ``NA_KEY_PROVIDER`` | ``file`` | ``file``, ``env`` or ``azure-keyvault`` |
| ``RATE_LIMIT_STORE`` | backend default | ``memory`` or ``database`` |
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .key_provider import KeyProviderConfig
from .rate_limit import RateLimits
from urllib.parse import urlsplit


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
    evidence_out_of_band: str = "off"
    anchor_interval_seconds: int = 3600
    max_request_bytes: int = 2 * 1024 * 1024
    proxy_hops: int = 1
    public_url: Optional[str] = None
    rate_limits: RateLimits = field(default_factory=RateLimits)
    # v1.3.0 (Stage 2)
    operator_key_holders: dict[str, str] = field(default_factory=dict)
    observation_max_backlog_seconds: int = 7 * 24 * 3600
    observation_clock_skew_seconds: int = 300
    judge_on_admission: bool = True


def _json_object(env: Mapping[str, str], name: str) -> dict[str, str]:
    raw = env.get(name)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    # v1.3.1: a value is a string as written; null, numbers and objects are refused, not turned into text.
    if not all(isinstance(v, str) for v in value.values()):
        raise ValueError(f"{name} values must be strings")
    return {str(k): v for k, v in value.items()}


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    """An integer setting; a bad value names its variable (v1.1.0)."""
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


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
        renewal_grace_seconds=_int(e, "RENEWAL_GRACE_SECONDS", 900),
        boundary_policy_enforcement=e.get("BOUNDARY_POLICY_ENFORCEMENT", "optional"),
        evidence_store=e.get("EVIDENCE_STORE", "off"),
        evidence_out_of_band=e.get("EVIDENCE_OUT_OF_BAND", "off"),
        anchor_interval_seconds=_int(e, "NA_ANCHOR_INTERVAL_SECONDS", 3600),
        max_request_bytes=_int(e, "NA_MAX_REQUEST_BYTES", 2 * 1024 * 1024),
        proxy_hops=_proxy_hops(e.get("NA_PROXY_HOPS", "1")),
        public_url=_public_url(e.get("NA_PUBLIC_URL")),
        rate_limits=RateLimits(
            admin=_int(e, "NA_RATE_LIMIT_ADMIN_PER_MINUTE", 300),
            verify=_int(e, "NA_RATE_LIMIT_VERIFY_PER_MINUTE", 60),
            evidence=_int(e, "NA_RATE_LIMIT_EVIDENCE_PER_MINUTE", 120),
            read=_int(e, "NA_RATE_LIMIT_READ_PER_MINUTE", 120),
            admin_auth_failures=_int(e, "NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE", 30),
            observations=_int(e, "NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE", 120),
        ),
        operator_key_holders=_json_object(e, "OPERATOR_KEY_HOLDERS_JSON"),
        observation_max_backlog_seconds=_int(e, "NA_OBSERVATION_MAX_BACKLOG_SECONDS", 7 * 24 * 3600),
        observation_clock_skew_seconds=_int(e, "NA_OBSERVATION_CLOCK_SKEW_SECONDS", 300),
        judge_on_admission=_on_off(e, "NA_JUDGE_ON_ADMISSION", True),
    )


def _on_off(env: Mapping[str, str], name: str, default: bool) -> bool:
    """An on/off setting (v1.3.0); a bad value names its variable."""
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in ("on", "true", "1", "yes"):
        return True
    if value in ("off", "false", "0", "no"):
        return False
    raise ValueError(f"{name} must be on or off")


def _public_url(raw: Optional[str]) -> Optional[str]:
    """The NA's public origin (v1.2.0): ``https://host[:port]``, nothing after it."""
    if not raw:
        return None
    parsed = urlsplit(raw.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password \
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("NA_PUBLIC_URL must be an http(s) origin: a scheme and a host, nothing after it")
    return f"{parsed.scheme}://{parsed.netloc}"


def _proxy_hops(raw: str) -> int:
    try:
        hops = int(raw)
    except ValueError:
        raise ValueError("NA_PROXY_HOPS must be an integer") from None
    if hops < 0:
        raise ValueError("NA_PROXY_HOPS must be 0 or more")
    return hops
