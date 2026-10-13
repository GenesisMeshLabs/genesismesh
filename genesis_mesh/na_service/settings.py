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

import ipaddress
import json
import os
import re
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
    proxy_hops: int = 0
    public_url: Optional[str] = None
    rate_limits: RateLimits = field(default_factory=RateLimits)
    # v1.3.0 (Stage 2)
    operator_key_holders: dict[str, str] = field(default_factory=dict)
    observation_max_backlog_seconds: int = 7 * 24 * 3600
    observation_clock_skew_seconds: int = 300
    judge_on_admission: bool = True
    # v1.4.0 (Stage 3)
    evidence_remediation: str = "off"
    remediation_grace_seconds: int = 24 * 3600
    remediation_default_mode: str = "alert_only"
    review_max_waiver_seconds: int = 30 * 24 * 3600
    review_actor_holders: dict[str, str] = field(default_factory=dict)
    # v1.5.0 (Stage 4)
    retention_require_archive: bool = True
    deployment: str = "local"
    decision_lifetime_seconds: int = 300


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
        proxy_hops=_proxy_hops(e.get("NA_PROXY_HOPS", "0")),
        public_url=_public_url(e.get("NA_PUBLIC_URL")),
        rate_limits=RateLimits(
            admin=_int(e, "NA_RATE_LIMIT_ADMIN_PER_MINUTE", 300),
            verify=_int(e, "NA_RATE_LIMIT_VERIFY_PER_MINUTE", 60),
            evidence=_int(e, "NA_RATE_LIMIT_EVIDENCE_PER_MINUTE", 120),
            read=_int(e, "NA_RATE_LIMIT_READ_PER_MINUTE", 120),
            admin_auth_failures=_int(e, "NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE", 30),
            observations=_int(e, "NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE", 120),
            audit_packs=_int(e, "NA_RATE_LIMIT_AUDIT_PACKS_PER_HOUR", 12),
        ),
        operator_key_holders=_json_object(e, "OPERATOR_KEY_HOLDERS_JSON"),
        observation_max_backlog_seconds=_int(e, "NA_OBSERVATION_MAX_BACKLOG_SECONDS", 7 * 24 * 3600),
        observation_clock_skew_seconds=_int(e, "NA_OBSERVATION_CLOCK_SKEW_SECONDS", 300),
        judge_on_admission=_on_off(e, "NA_JUDGE_ON_ADMISSION", True),
        evidence_remediation=e.get("EVIDENCE_REMEDIATION", "off"),
        remediation_grace_seconds=_int(e, "NA_REMEDIATION_GRACE_SECONDS", 24 * 3600),
        remediation_default_mode=e.get("NA_REMEDIATION_DEFAULT_MODE", "alert_only"),
        review_max_waiver_seconds=_int(e, "NA_REVIEW_MAX_WAIVER_SECONDS", 30 * 24 * 3600),
        review_actor_holders=_json_object(e, "NA_REVIEW_ACTOR_HOLDERS_JSON"),
        retention_require_archive=_on_off(e, "NA_RETENTION_REQUIRE_ARCHIVE", True),
        deployment=_deployment(e.get("NA_DEPLOYMENT", "local")),
        decision_lifetime_seconds=_decision_lifetime(_int(e, "NA_DECISION_LIFETIME_SECONDS", 300)),
    )


def _decision_lifetime(value: int) -> int:
    """``NA_DECISION_LIFETIME_SECONDS`` (v1.5.0 review fixes): 1 to 300 seconds."""
    from ..models.key_succession import MAX_DECISION_LIFETIME

    if not 1 <= value <= int(MAX_DECISION_LIFETIME.total_seconds()):
        raise ValueError(f"NA_DECISION_LIFETIME_SECONDS must be 1 to {int(MAX_DECISION_LIFETIME.total_seconds())}")
    return value


def _deployment(raw: str) -> str:
    """``NA_DEPLOYMENT`` (v1.5.0): ``local`` or ``managed`` (the root key must not be on the NA host)."""
    value = raw.strip().lower() or "local"
    if value not in ("local", "managed"):
        raise ValueError("NA_DEPLOYMENT must be local or managed")
    return value


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
    try:
        return public_origin(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"NA_PUBLIC_URL must be an http(s) origin: a scheme and a host, nothing after it ({exc})"
        ) from None


_HOST_LABEL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")


def public_origin(value: str) -> str:
    """``value`` as an origin, ``http(s)://host[:port]``; ``ValueError`` naming why it is not one.

    v1.3.1: strict. The host is a DNS name or an IP address (IPv6 in
    brackets), a port is 1 to 65535 in plain digits, and nothing else may
    appear: no user, path, query, fragment, whitespace or control character.
    A trailing ``/`` is dropped.
    """
    if any(c.isspace() or not c.isprintable() for c in value):
        raise ValueError("whitespace or a control character")
    if any(c in value for c in "?#@\\"):
        raise ValueError("a user, query or fragment")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not value.lower().startswith(parsed.scheme + "://"):
        raise ValueError("the scheme is not http or https")
    if parsed.path not in ("", "/"):
        raise ValueError("a path")
    netloc = parsed.netloc
    if netloc.startswith("["):
        host, _, rest = netloc[1:].partition("]")
        if rest and not rest.startswith(":"):
            raise ValueError(f"the host {netloc!r}")
        sep, port = (":", rest[1:]) if rest else ("", "")
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError(f"the IPv6 address {host!r}") from None
    else:
        host, sep, port = netloc.partition(":")
        labels = host.split(".")
        if len(host) > 253 or not all(_HOST_LABEL.match(label) for label in labels):
            raise ValueError(f"the host {host!r}")
        if all(label.isdigit() for label in labels):
            try:
                ipaddress.IPv4Address(host)
            except ValueError:
                raise ValueError(f"the IPv4 address {host!r}") from None
    if sep and not (port.isascii() and port.isdigit() and str(int(port)) == port and 1 <= int(port) <= 65535):
        raise ValueError(f"the port {port!r}")
    return f"{parsed.scheme}://{netloc}"


def _proxy_hops(raw: str) -> int:
    try:
        hops = int(raw)
    except ValueError:
        raise ValueError("NA_PROXY_HOPS must be an integer") from None
    if hops < 0:
        raise ValueError("NA_PROXY_HOPS must be 0 or more")
    return hops
