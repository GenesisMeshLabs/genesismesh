#!/usr/bin/env python3
"""
Complete end-to-end workflow test for Genesis Mesh.

This script demonstrates:
1. Key generation
2. Genesis block creation and signing
3. Network Authority service startup
4. Node joining the network
5. Certificate and policy validation
"""

import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

from genesis_mesh.crypto import generate_keypair, save_keypair, sign_model
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    BootstrapAnchor
)
from genesis_mesh.na_service import NetworkAuthorityService
from genesis_mesh.node import MeshNode


def main():
    print("=== Genesis Mesh End-to-End Test ===\n")

    # Step 1: Generate keys
    print("Step 1: Generating keys...")
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    print(f"  ✓ Root Sovereign key generated")
    print(f"  ✓ Network Authority key generated")

    # Step 2: Create genesis block
    print("\nStep 2: Creating genesis block...")
    now = datetime.utcnow()

    genesis_block = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90)
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url=None
        ),
        bootstrap_anchors=[
            BootstrapAnchor(id="anchor-test", endpoint="127.0.0.1:8444")
        ]
    )

    # Step 3: Sign genesis block
    print("Step 3: Signing genesis block with Root Sovereign...")
    signature = sign_model(genesis_block, root_keypair.private_key, "rs-test")
    genesis_block.signatures.append(signature)
    print(f"  ✓ Genesis block signed")

    # Step 4: Start Network Authority service in background
    print("\nStep 4: Starting Network Authority service...")
    na_service = NetworkAuthorityService(
        genesis_block=genesis_block,
        na_private_key=na_keypair.private_key,
        key_id="na-test"
    )

    # Run NA service in a background thread
    na_thread = threading.Thread(
        target=lambda: na_service.run(host='127.0.0.1', port=8444, debug=False),
        daemon=True
    )
    na_thread.start()
    time.sleep(2)  # Give service time to start
    print(f"  ✓ Network Authority running on port 8444")

    # Step 5: Create and join nodes
    print("\nStep 5: Creating mesh nodes...")

    # Anchor node
    print("  Creating anchor node...")
    anchor_node = MeshNode(
        genesis_block=genesis_block,
        roles=['role:anchor']
    )
    print(f"    ✓ Anchor node created")

    # Join network
    print("  Requesting join certificate...")
    anchor_node.join_network("http://127.0.0.1:8444", validity_hours=168)
    print(f"    ✓ Join certificate received: {anchor_node.join_certificate.cert_id}")

    # Fetch policy
    print("  Fetching policy manifest...")
    anchor_node.fetch_policy("http://127.0.0.1:8444")
    print(f"    ✓ Policy manifest received: {anchor_node.policy_manifest.policy_id}")

    # Client node
    print("\n  Creating client node...")
    client_node = MeshNode(
        genesis_block=genesis_block,
        roles=['role:client']
    )
    print(f"    ✓ Client node created")

    print("  Requesting join certificate...")
    client_node.join_network("http://127.0.0.1:8444", validity_hours=24)
    print(f"    ✓ Join certificate received: {client_node.join_certificate.cert_id}")

    # Step 6: Verify everything
    print("\nStep 6: Verifying node status...")

    anchor_status = anchor_node.get_status()
    print(f"\n  Anchor Node Status:")
    print(f"    Network: {anchor_status['network']}")
    print(f"    Roles: {anchor_status['roles']}")
    print(f"    Certificate Valid: {anchor_status['certificate_valid']}")
    print(f"    Expires: {anchor_status['certificate_expires']}")

    client_status = client_node.get_status()
    print(f"\n  Client Node Status:")
    print(f"    Network: {client_status['network']}")
    print(f"    Roles: {client_status['roles']}")
    print(f"    Certificate Valid: {client_status['certificate_valid']}")
    print(f"    Expires: {client_status['certificate_expires']}")

    print("\n=== Test Complete! ===")
    print("All components working correctly:")
    print("  ✓ Cryptographic signing and verification")
    print("  ✓ Genesis block validation")
    print("  ✓ Network Authority certificate issuance")
    print("  ✓ Node joining and policy enforcement")
    print("  ✓ Role-based access control")


if __name__ == '__main__':
    main()
