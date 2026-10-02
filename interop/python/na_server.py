"""Local Network Authority for the interoperability scenario.

Serves the real NA application (routes, admin authentication, signatures,
policy enforcement required, evidence store on) on 127.0.0.1 with fresh keys
and a temporary SQLite database. Writes the connection details to
``fixtures/na.json`` and serves until terminated.

    python interop/python/na_server.py
"""

from __future__ import annotations

import json
import signal
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.serving import make_server

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NETWORK = "interop-na"


def main() -> None:
    root = generate_keypair()
    operator = generate_keypair()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name=NETWORK, network_version="v0.61", root_public_key=root.public_key_b64,
        network_authority=NetworkAuthority(public_key=root.public_key_b64, valid_from=now, valid_to=now + timedelta(days=1)),
        policy_manifest=PolicyManifestRef(hash="sha256:interop", url=None),
    )
    genesis.signatures.append(sign_model(genesis, root.private_key, "root"))
    with tempfile.TemporaryDirectory(prefix="gm-interop-") as tmp:
        service = NetworkAuthorityService(
            genesis_block=genesis, na_private_key=root.private_key, key_id="na-interop",
            db_path=str(Path(tmp) / "na.db"),
            operator_public_keys={"ops": operator.public_key_b64}, operator_key_tiers={"ops": "privileged"},
            boundary_policy_enforcement="required", evidence_store="on",
        )
        server = make_server("127.0.0.1", 0, service.app, threaded=True)
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / "na.json").write_text(json.dumps({
            "base_url": f"http://127.0.0.1:{server.server_port}",
            "network": NETWORK,
            "na_public_key": root.public_key_b64,
            "operator_key_id": "ops",
            "operator_seed": operator.private_key_b64,
        }, indent=2), encoding="utf-8")
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"interop NA listening on http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
