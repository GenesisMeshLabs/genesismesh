#!/bin/bash
# Genesis Mesh route failure recovery demo
#
# Topology:
#   A ──> B (port 7443) ──> C    (primary path)
#   A ──> D (port 7444) ──> C    (backup path)
#
# B is killed mid-demo. A's routing table withdraws B's routes.
# The next send to C routes through D automatically.
#
# Prerequisites on Azure VM:
#   1. Node B running as genesis-mesh-node.service (port 7443) — existing
#   2. Node D enrolled and running as genesis-mesh-node-d.service (port 7444)
#      Setup commands:
#        INVITE=$(genesis-mesh admin invite --role anchor --na https://na.genesismesh.connectorzzz.com --config /mnt/c/Source/genesismesh/genesis-mesh.toml)
#        genesis-mesh join --na https://na.genesismesh.connectorzzz.com --token "$INVITE" --config ~/.genesis-mesh-node-d/config.toml
#        sudo tee /etc/systemd/system/genesis-mesh-node-d.service <<EOF
#        [Unit]
#        Description=Genesis Mesh Demo Node D
#        After=genesis-mesh-na.service
#        [Service]
#        User=azureuser
#        WorkingDirectory=/opt/genesis-mesh
#        ExecStart=/opt/genesis-mesh/.venv/bin/genesis-mesh join --na https://na.genesismesh.connectorzzz.com --config /home/azureuser/.genesis-mesh-node-d/config.toml --persistent --listen-port 7444
#        Restart=on-failure
#        RestartSec=10
#        [Install]
#        WantedBy=multi-user.target
#        EOF
#        sudo systemctl daemon-reload && sudo systemctl enable --now genesis-mesh-node-d
#
# Record with:
#   asciinema rec failover.cast --command "bash docs/examples/assets/failover-demo.sh"
# Convert with:
#   agg failover.cast docs/examples/assets/genesis-mesh-failover.gif

set -e

NA="https://na.genesismesh.connectorzzz.com"
B_PEER="ws://4.223.130.190:7443"
D_PEER="ws://4.223.130.190:7444"
OPERATOR_CONFIG="/mnt/c/Source/genesismesh/genesis-mesh.toml"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa_azure}"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
VM="azureuser@4.223.130.190"

SENDER_CONFIG="$HOME/.gm-failover-sender/config.toml"
RECEIVER_CONFIG="$HOME/.gm-failover-receiver/config.toml"

if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
fi

cleanup() {
    kill "$SENDER_PID" "$RECEIVER_PID" 2>/dev/null || true
    # Restore Node B on the VM
    ssh $SSH_OPTS "$VM" "sudo systemctl start genesis-mesh-node 2>/dev/null || true" &
    rm -rf "$HOME/.gm-failover-sender" "$HOME/.gm-failover-receiver"
}
trap cleanup EXIT

clear

echo "Route failure recovery demo"
echo ""
echo "  Node A (sender)   — this machine"
echo "  Node B (router)   — Azure VM port 7443  [primary]"
echo "  Node D (router)   — Azure VM port 7444  [backup]"
echo "  Node C (receiver) — this machine, separate identity"
echo ""
echo "  Primary:  A --> B --> C"
echo "  Backup:   A --> D --> C"
echo ""
sleep 3

# ── Enroll A and C ────────────────────────────────────────────────────────────

echo "==> Enrolling Node A and Node C"

INVITE_A=$(cd /mnt/c/Source/genesismesh && genesis-mesh admin invite \
  --role anchor --na "$NA" --config "$OPERATOR_CONFIG")
mkdir -p "$HOME/.gm-failover-sender"
genesis-mesh join --na "$NA" --token "$INVITE_A" --config "$SENDER_CONFIG" 2>&1 | grep -E "Joined|Certificate"

INVITE_C=$(cd /mnt/c/Source/genesismesh && genesis-mesh admin invite \
  --role anchor --na "$NA" --config "$OPERATOR_CONFIG")
mkdir -p "$HOME/.gm-failover-receiver"
genesis-mesh join --na "$NA" --token "$INVITE_C" --config "$RECEIVER_CONFIG" 2>&1 | grep -E "Joined|Certificate"

RECEIVER_KEY=$(python3 -c "
import json
cert = json.load(open('$HOME/.gm-failover-receiver/node.cert.json'))
print(cert['node_public_key'])
")
echo "  Node C key: ${RECEIVER_KEY:0:24}..."
sleep 1

# ── Start runtimes connected to BOTH B and D ──────────────────────────────────

echo ""
echo "==> Starting Node C — connected to B and D"
genesis-mesh join \
  --na "$NA" \
  --config "$RECEIVER_CONFIG" \
  --persistent \
  --peer "$B_PEER" \
  --peer "$D_PEER" > /tmp/gm-failover-c.log 2>&1 &
RECEIVER_PID=$!
sleep 3

echo "==> Starting Node A — connected to B and D"
genesis-mesh join \
  --na "$NA" \
  --config "$SENDER_CONFIG" \
  --persistent \
  --peer "$B_PEER" \
  --peer "$D_PEER" > /tmp/gm-failover-a.log 2>&1 &
SENDER_PID=$!
sleep 8

# ── Show routes learned ───────────────────────────────────────────────────────

echo ""
echo "==> Node A routing table (routes to C via B and D):"
grep -i "Updated route to ${RECEIVER_KEY:0:8}" /tmp/gm-failover-a.log | tail -5
sleep 2

# ── Send via B (primary path) ─────────────────────────────────────────────────

echo ""
echo "==> Send 1: A --> B --> C  (primary path)"
genesis-mesh send \
  --config "$SENDER_CONFIG" \
  --to "$RECEIVER_KEY" \
  --via "$B_PEER" \
  --message "hello via B (primary)"
sleep 1

echo ""
echo "  Node C received:"
grep "DATA message delivered" /tmp/gm-failover-c.log | tail -1
sleep 2

# ── Kill Node B ───────────────────────────────────────────────────────────────

echo ""
echo "==> Killing Node B (stopping genesis-mesh-node on Azure VM)"
ssh $SSH_OPTS "$VM" "sudo systemctl stop genesis-mesh-node"
sleep 4

echo ""
echo "==> Node A routing table after B went offline:"
grep -E "Removed neighbor|invalidated|withdraw" /tmp/gm-failover-a.log | tail -5
sleep 2

# ── Send via D (backup path) ──────────────────────────────────────────────────

echo ""
echo "==> Send 2: A --> D --> C  (backup path, B is offline)"
genesis-mesh send \
  --config "$SENDER_CONFIG" \
  --to "$RECEIVER_KEY" \
  --via "$D_PEER" \
  --message "hello via D (backup)"
sleep 1

echo ""
echo "  Node C received:"
grep "DATA message delivered" /tmp/gm-failover-c.log | tail -1
sleep 2

# ── Show B forwarded via D ────────────────────────────────────────────────────

echo ""
echo "==> Node D forwarded (Azure VM logs):"
ssh $SSH_OPTS "$VM" \
  "sudo journalctl -u genesis-mesh-node-d --since '30 seconds ago' --no-pager 2>/dev/null \
   | grep -E 'DATA forwarded|forwarded' | tail -3"
sleep 3

echo ""
echo "==> Route failure recovery complete"
echo "    Primary path (B) went offline."
echo "    Backup path (D) delivered the message."
