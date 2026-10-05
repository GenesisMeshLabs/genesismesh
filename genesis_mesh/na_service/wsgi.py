"""WSGI entry point for the Network Authority service.

Configuration is read from the environment by ``settings.load_settings``; see
that module for the variables. With no v0.60 variables set the NA runs exactly
as before (SQLite, key file).
"""

import json

from werkzeug.middleware.proxy_fix import ProxyFix

from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.key_provider import load_signer
from genesis_mesh.na_service.server import create_app
from genesis_mesh.na_service.settings import load_settings
from genesis_mesh.observability import configure_logging


configure_logging()

settings = load_settings()

with open(settings.genesis_file, "r", encoding="utf-8") as f:
    genesis_block = GenesisBlock(**json.load(f))

app = create_app(
    genesis_block=genesis_block,
    na_private_key=load_signer(settings.key),
    db_path=settings.db_path,
    key_id=settings.key.key_id,
    operator_public_keys=settings.operator_public_keys,
    operator_key_tiers=settings.operator_key_tiers,
    renewal_grace_seconds=settings.renewal_grace_seconds,
    boundary_policy_enforcement=settings.boundary_policy_enforcement,
    evidence_store=settings.evidence_store,
    database_url=settings.database_url,
    ha_mode=settings.ha_mode,
    rate_limit_store=settings.rate_limit_store,
    max_request_bytes=settings.max_request_bytes,
    rate_limits=settings.rate_limits,
    admin_legacy_signatures=settings.admin_legacy_signatures,
)

# Trust exactly NA_PROXY_HOPS reverse proxies (default 1, e.g. nginx) for the
# client address that rate limits key on. With 0 (the NA exposed directly) the
# X-Forwarded-* headers are ignored: a client cannot set its own address and
# escape per-IP limits (v0.62.0 security review). Flask's documented ProxyFix
# idiom; mypy flags the wsgi_app reassignment.
if settings.proxy_hops:
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app, x_for=settings.proxy_hops, x_proto=settings.proxy_hops, x_host=settings.proxy_hops,
    )
