#!/bin/bash
# Genesis Mesh Quickstart Demo
# This script demonstrates the complete workflow for setting up a Genesis Mesh network

set -e

echo "=== Genesis Mesh Quickstart Demo ==="
echo ""

# Clean up any previous runs
DEMO_DIR="examples/genesis/demo"
KEY_DIR="$DEMO_DIR/keys"
rm -rf "$DEMO_DIR"
mkdir -p "$KEY_DIR"

echo "Step 1: Generate Root Sovereign keys (offline authority)"
python -m genesis_mesh.cli keygen root \
  --output "$KEY_DIR/root" \
  --key-id rs-demo-2025

echo ""
echo "Step 2: Generate Network Authority keys"
python -m genesis_mesh.cli keygen network-authority \
  --output "$KEY_DIR/na" \
  --key-id na-demo-2025

echo ""
echo "Step 2b: Generate operator admin keys"
python -m genesis_mesh.cli keygen node \
  --output "$KEY_DIR/operator" \
  --key-id operator-demo

echo ""
echo "Step 3: Create genesis block"
python -m genesis_mesh.cli genesis create \
  --network-name "DEMO" \
  --network-version "v0.1" \
  --root-key "$KEY_DIR/root.pub" \
  --na-key "$KEY_DIR/na.pub" \
  --na-valid-days 90 \
  --anchor anchor-local:127.0.0.1:8443 \
  --output "$DEMO_DIR/genesis.json"

echo ""
echo "Step 4: Sign genesis block with Root Sovereign"
python -m genesis_mesh.cli genesis sign \
  --genesis "$DEMO_DIR/genesis.json" \
  --root-private-key "$KEY_DIR/root.key" \
  --key-id rs-demo-2025 \
  --output "$DEMO_DIR/genesis.signed.json"

echo ""
echo "Step 5: Verify genesis block"
python -m genesis_mesh.cli genesis verify \
  --genesis "$DEMO_DIR/genesis.signed.json"

echo ""
echo "Step 6: Display genesis block info"
python -m genesis_mesh.cli info \
  --genesis "$DEMO_DIR/genesis.signed.json"

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Validate Network Authority configuration:"
echo "   python -m genesis_mesh.na_service --genesis $DEMO_DIR/genesis.signed.json --na-private-key $KEY_DIR/na.key --operator-public-key operator-demo=$KEY_DIR/operator.pub"
echo ""
echo "2. Start Network Authority:"
echo "   export GENESIS_FILE=$DEMO_DIR/genesis.signed.json"
echo "   export NA_PRIVATE_KEY_FILE=$KEY_DIR/na.key"
echo "   export OPERATOR_PUBLIC_KEYS_JSON=\"{\\\"operator-demo\\\":\\\"$(grep -v '^#' \"$KEY_DIR/operator.pub\" | tr -d '\\r\\n')\\\"}\""
echo "   python -m flask --app genesis_mesh.na_service.wsgi run --host 127.0.0.1 --port 8443"
echo ""
echo "3. Create a single-use invite token with the operator-authenticated /admin/invite endpoint."
echo "   See examples/test_workflow.py for the admin request signing format."
echo ""
echo "4. In another terminal, start a node with the invite token:"
echo "   python -m genesis_mesh.node --genesis $DEMO_DIR/genesis.signed.json --bootstrap http://localhost:8443 --role role:anchor --invite-token \"\$INVITE_TOKEN\""
echo ""
