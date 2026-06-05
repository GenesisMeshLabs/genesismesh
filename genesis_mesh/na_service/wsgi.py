"""WSGI entry point for the Network Authority service."""

import json
import os

from werkzeug.middleware.proxy_fix import ProxyFix

from genesis_mesh.crypto import load_private_key
from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.server import create_app
from genesis_mesh.observability import configure_logging


configure_logging()


def _load_operator_public_keys() -> dict[str, str]:
    """Load operator public keys from JSON environment configuration."""
    raw = os.environ.get("OPERATOR_PUBLIC_KEYS_JSON")
    return json.loads(raw) if raw else {}


with open(os.environ["GENESIS_FILE"], "r", encoding="utf-8") as f:
    genesis_block = GenesisBlock(**json.load(f))

na_private_key = load_private_key(os.environ["NA_PRIVATE_KEY_FILE"])

app = create_app(
    genesis_block=genesis_block,
    na_private_key=na_private_key,
    db_path=os.environ.get("DB_PATH", "genesis_mesh_na.db"),
    key_id=os.environ.get("NA_KEY_ID", "na-2025-q1"),
    operator_public_keys=_load_operator_public_keys(),
)

# Trust one proxy hop (Nginx) so request.remote_addr reflects the real client IP.
# Flask's documented ProxyFix idiom — mypy flags the wsgi_app reassignment.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]
