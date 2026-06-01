#!/bin/bash
# Genesis Mesh multi-hop routing demo: Node A → Node B (Azure VM) → Node C
#
# A and C connect only to B. A message from A to C must be forwarded by B.
# This proves distance-vector routing and DATA frame forwarding.
#
# Record with:
#   asciinema rec multi-hop.cast --command "bash docs/examples/assets/scripts/multi-hop-demo.sh"
# Convert with:
#   agg multi-hop.cast docs/examples/assets/images/genesis-mesh-multi-hop.gif

set -e

NA="https://na.genesismesh.connectorzzz.com"
B_PEER="ws://4.223.130.190:7443"
OPERATOR_CONFIG="/mnt/c/Source/genesismesh/genesis-mesh.toml"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa_azure}"

SENDER_CONFIG="$HOME/.gm-demo-sender/config.toml"
RECEIVER_CONFIG="$HOME/.gm-demo-receiver/config.toml"

if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
fi

cleanup() {
    kill "$SENDER_PID" "$RECEIVER_PID" 2>/dev/null || true
    rm -rf "$HOME/.gm-demo-sender" "$HOME/.gm-demo-receiver"
}
trap cleanup EXIT

clear

echo "Multi-hop routing demo"
echo ""
echo "  Node A (sender)   — this machine, new identity"
echo "  Node B (router)   — Azure VM 4.223.130.190, already running"
echo "  Node C (receiver) — this machine, separate identity"
echo ""
echo "  A ── Noise XX ──> B ── Noise XX ──> C"
echo "  A and C do not connect to each other directly."
echo ""
sleep 3

# ── Enroll Node A ────────────────────────────────────────────────────────────

echo "==> Enrolling Node A (sender)"
INVITE_A=$(cd /mnt/c/Source/genesismesh && genesis-mesh admin invite \
  --role anchor --na "$NA" --config "$OPERATOR_CONFIG")
mkdir -p "$HOME/.gm-demo-sender"
genesis-mesh join --na "$NA" --token "$INVITE_A" --config "$SENDER_CONFIG"
sleep 1

# ── Enroll Node C ────────────────────────────────────────────────────────────

echo ""
echo "==> Enrolling Node C (receiver)"
INVITE_C=$(cd /mnt/c/Source/genesismesh && genesis-mesh admin invite \
  --role anchor --na "$NA" --config "$OPERATOR_CONFIG")
mkdir -p "$HOME/.gm-demo-receiver"
genesis-mesh join --na "$NA" --token "$INVITE_C" --config "$RECEIVER_CONFIG"
sleep 1

RECEIVER_KEY=$(python3 -c "
import json
cert = json.load(open('$HOME/.gm-demo-receiver/node.cert.json'))
print(cert['node_public_key'])
")

echo ""
echo "  Node C key: $RECEIVER_KEY"
sleep 1

# ── Start runtimes ────────────────────────────────────────────────────────────

echo ""
echo "==> Starting Node C runtime — peer: B only"
genesis-mesh join \
  --na "$NA" \
  --config "$RECEIVER_CONFIG" \
  --persistent \
  --peer "$B_PEER" > /tmp/gm-node-c.log 2>&1 &
RECEIVER_PID=$!
sleep 3

echo "==> Starting Node A runtime — peer: B only"
genesis-mesh join \
  --na "$NA" \
  --config "$SENDER_CONFIG" \
  --persistent \
  --peer "$B_PEER" > /tmp/gm-node-a.log 2>&1 &
SENDER_PID=$!

# ── Wait for routes ───────────────────────────────────────────────────────────

echo ""
echo "==> Waiting for B to propagate routes A <-> C ..."
sleep 10

echo ""
echo "  Node A routing log (routes learned via B):"
grep -i "neighbor\|route\|peer" /tmp/gm-node-a.log | tail -5
sleep 2

# ── Send message ──────────────────────────────────────────────────────────────

echo ""
echo "==> Node A sending to Node C — routed through B"
genesis-mesh send \
  --config "$SENDER_CONFIG" \
  --to "$RECEIVER_KEY" \
  --via "$B_PEER" \
  --message "hello from A via B to C"
sleep 2

# ── Show delivery ─────────────────────────────────────────────────────────────

echo ""
echo "==> Node C received:"
grep -i "DATA\|delivered\|content" /tmp/gm-node-c.log | tail -3
sleep 1

echo ""
echo "==> Node B forwarded (Azure VM logs):"
ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=no \
    -o IdentitiesOnly=yes \
    "azureuser@4.223.130.190" \
    "sudo journalctl -u genesis-mesh-node --since '30 seconds ago' --no-pager 2>/dev/null \
     | grep -E 'forward|route|DATA|Forwarding' | tail -5"
sleep 3
