"""Shared helpers for CLI operation tests."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from werkzeug.serving import make_server

from genesis_mesh.cli.config import load_config
from genesis_mesh.crypto import load_private_key
from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.auth import load_operator_public_keys
from genesis_mesh.na_service.server import create_app


@contextmanager
def _running_na_from_config(config_path: Path, db_path: Path):
    """Run a configured Network Authority on an ephemeral localhost port."""
    config = load_config(str(config_path), required=True)
    with open(config["paths"]["genesis"], "r", encoding="utf-8") as f:
        genesis = GenesisBlock(**json.load(f))

    app = create_app(
        genesis_block=genesis,
        na_private_key=load_private_key(config["paths"]["na_private_key"]),
        key_id=config["na"]["key_id"],
        db_path=str(db_path),
        operator_public_keys=load_operator_public_keys(
            [f"{config['operator']['key_id']}={config['paths']['operator_public_key']}"]
        ),
    )
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
