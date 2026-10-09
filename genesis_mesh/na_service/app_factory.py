"""Build the Network Authority app from its settings (v1.1.0).

The WSGI entry point (Gunicorn, the container image) and
``genesis-mesh na start --env-file`` both build the app here, so a locally
started NA serves exactly what production serves.
"""

from __future__ import annotations

import json

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from ..models import GenesisBlock
from .key_provider import load_signer
from .server import create_app
from .settings import NASettings


def build_app(settings: NASettings) -> Flask:
    """Create the NA app for ``settings``, behind ``settings.proxy_hops`` proxies."""
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
        anchor_interval_seconds=settings.anchor_interval_seconds,
        database_url=settings.database_url,
        ha_mode=settings.ha_mode,
        rate_limit_store=settings.rate_limit_store,
        max_request_bytes=settings.max_request_bytes,
        rate_limits=settings.rate_limits,
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
    return app
