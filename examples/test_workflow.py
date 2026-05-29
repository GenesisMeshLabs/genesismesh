#!/usr/bin/env python3
"""Complete end-to-end workflow smoke test for Genesis Mesh."""

import json
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from genesis_mesh.crypto import generate_keypair, sign_data, sign_model
from genesis_mesh.models import (
    BootstrapAnchor,
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
)
from genesis_mesh.na_service import NetworkAuthorityService
from genesis_mesh.node import MeshNode


def _admin_headers(body: dict, operator_keypair, key_id: str = "operator-test") -> dict:
    """Create operator authentication headers for an admin request body."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {
            "body": body,
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(
            canonical.encode("utf-8"),
            operator_keypair.private_key,
        ),
    }


def _create_invite(
    na_endpoint: str,
    operator_keypair,
    roles: list[str],
    validity_hours: int,
) -> str:
    """Create a single-use invite token through the admin API."""
    body: dict[str, Any] = {
        "roles": roles,
        "max_validity_hours": validity_hours,
        "token_expiry_hours": 1,
    }
    response = requests.post(
        f"{na_endpoint}/admin/invite",
        json=body,
        headers=_admin_headers(body, operator_keypair),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["token_id"]


def main():
    """Run the local workflow smoke test."""
    print("=== Genesis Mesh End-to-End Test ===\n")

    print("Step 1: Generating keys...")
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    operator_keypair = generate_keypair()
    print("  Root Sovereign key generated")
    print("  Network Authority key generated")
    print("  Operator key generated")

    print("\nStep 2: Creating genesis block...")
    now = datetime.now(timezone.utc)

    genesis_block = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url=None,
        ),
        bootstrap_anchors=[
            BootstrapAnchor(id="anchor-test", endpoint="127.0.0.1:8444"),
        ],
    )

    print("Step 3: Signing genesis block with Root Sovereign...")
    signature = sign_model(genesis_block, root_keypair.private_key, "rs-test")
    genesis_block.signatures.append(signature)
    print("  Genesis block signed")

    print("\nStep 4: Starting Network Authority service...")
    na_service = NetworkAuthorityService(
        genesis_block=genesis_block,
        na_private_key=na_keypair.private_key,
        key_id="na-test",
        operator_public_keys={"operator-test": operator_keypair.public_key_b64},
    )
    na_server = make_server("127.0.0.1", 8444, na_service.app)

    na_thread = threading.Thread(
        target=na_server.serve_forever,
        daemon=True,
    )
    na_thread.start()
    time.sleep(2)
    na_endpoint = "http://127.0.0.1:8444"
    print("  Network Authority running on port 8444")

    print("\nStep 5: Creating mesh nodes...")

    print("  Creating anchor node...")
    anchor_node = MeshNode(
        genesis_block=genesis_block,
        roles=["role:anchor"],
    )
    print("    Anchor node created")

    print("  Requesting anchor invite and join certificate...")
    anchor_invite = _create_invite(
        na_endpoint,
        operator_keypair,
        roles=["role:anchor"],
        validity_hours=168,
    )
    anchor_node.join_network(
        na_endpoint,
        validity_hours=168,
        invite_token=anchor_invite,
    )
    print(f"    Join certificate received: {anchor_node.join_certificate.cert_id}")

    print("  Fetching policy manifest...")
    anchor_node.fetch_policy(na_endpoint)
    print(f"    Policy manifest received: {anchor_node.policy_manifest.policy_id}")

    print("\n  Creating client node...")
    client_node = MeshNode(
        genesis_block=genesis_block,
        roles=["role:client"],
    )
    print("    Client node created")

    print("  Requesting client invite and join certificate...")
    client_invite = _create_invite(
        na_endpoint,
        operator_keypair,
        roles=["role:client"],
        validity_hours=24,
    )
    client_node.join_network(
        na_endpoint,
        validity_hours=24,
        invite_token=client_invite,
    )
    print(f"    Join certificate received: {client_node.join_certificate.cert_id}")

    print("\nStep 6: Verifying node status...")

    anchor_status = anchor_node.get_status()
    print("\n  Anchor Node Status:")
    print(f"    Network: {anchor_status['network']}")
    print(f"    Roles: {anchor_status['roles']}")
    print(f"    Certificate Valid: {anchor_status['certificate_valid']}")
    print(f"    Expires: {anchor_status['certificate_expires']}")

    client_status = client_node.get_status()
    print("\n  Client Node Status:")
    print(f"    Network: {client_status['network']}")
    print(f"    Roles: {client_status['roles']}")
    print(f"    Certificate Valid: {client_status['certificate_valid']}")
    print(f"    Expires: {client_status['certificate_expires']}")

    print("\n=== Test Complete! ===")
    print("All smoke-test components completed.")
    na_server.shutdown()


if __name__ == "__main__":
    main()
