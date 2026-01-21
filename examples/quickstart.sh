#!/bin/bash
# Genesis Mesh Quickstart Demo
# This script demonstrates the complete workflow for setting up a Genesis Mesh network

set -e

echo "=== Genesis Mesh Quickstart Demo ==="
echo ""

# Clean up any previous runs
rm -rf demo_keys demo_genesis.json demo_genesis.signed.json
mkdir -p demo_keys

echo "Step 1: Generate Root Sovereign keys (offline authority)"
python -m genesis_mesh.cli keygen root \
  --output demo_keys/root \
  --key-id rs-demo-2025

echo ""
echo "Step 2: Generate Network Authority keys"
python -m genesis_mesh.cli keygen network-authority \
  --output demo_keys/na \
  --key-id na-demo-2025

echo ""
echo "Step 3: Create genesis block"
python -m genesis_mesh.cli genesis create \
  --network-name "DEMO" \
  --network-version "v0.1" \
  --root-key demo_keys/root.pub \
  --na-key demo_keys/na.pub \
  --na-valid-days 90 \
  --anchor anchor-local:127.0.0.1:8443 \
  --output demo_genesis.json

echo ""
echo "Step 4: Sign genesis block with Root Sovereign"
python -m genesis_mesh.cli genesis sign \
  --genesis demo_genesis.json \
  --root-private-key demo_keys/root.key \
  --key-id rs-demo-2025 \
  --output demo_genesis.signed.json

echo ""
echo "Step 5: Verify genesis block"
python -m genesis_mesh.cli genesis verify \
  --genesis demo_genesis.signed.json

echo ""
echo "Step 6: Display genesis block info"
python -m genesis_mesh.cli info \
  --genesis demo_genesis.signed.json

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Start Network Authority:"
echo "   python -m genesis_mesh.na_service --genesis demo_genesis.signed.json --na-private-key demo_keys/na.key --port 8443"
echo ""
echo "2. In another terminal, start a node:"
echo "   python -m genesis_mesh.node --genesis demo_genesis.signed.json --bootstrap http://localhost:8443 --role role:anchor"
echo ""
