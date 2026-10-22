#!/bin/bash
# Genesis Mesh P2P messaging demo
#
# Sends one encrypted message over Noise XX to a remote node you control, then
# reads the receiving node's journal over SSH.
#
# Prerequisites:
#   - genesis-mesh installed and this machine enrolled (a genesis-mesh.toml)
#   - A remote node running: genesis-mesh join --persistent --listen-port 7443,
#     as the systemd unit genesis-mesh-node
#
# Variables (set before running):
#   PEER_HOST       address of the remote node (required)
#   PEER_KEY        node public key of the remote node (required)
#   PEER_PORT       peer WebSocket port on the remote node (default 7443)
#   VM_USER         SSH user on the remote node (default azureuser)
#   SSH_KEY         SSH private key for the remote node (default ~/.ssh/id_rsa)
#   NA              Network Authority URL (default https://na.genesismesh.org)
#   GM_REPO         repository root (default: git rev-parse --show-toplevel)
#   GENESIS_CONFIG  CLI config (default $GM_REPO/genesis-mesh.toml)
#
# Record with: asciinema rec p2p-send.cast --command "bash docs/examples/assets/scripts/p2p-send-demo.sh"
# Convert with: agg p2p-send.cast docs/examples/assets/images/genesis-mesh-p2p-send.gif

PEER_HOST="${PEER_HOST:?set PEER_HOST to the remote node address}"
PEER_KEY="${PEER_KEY:?set PEER_KEY to the remote node public key}"
PEER_PORT="${PEER_PORT:-7443}"
VM_USER="${VM_USER:-azureuser}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
NA="${NA:-https://na.genesismesh.org}"

REPO="${GM_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
GENESIS_CONFIG="${GENESIS_CONFIG:-$REPO/genesis-mesh.toml}"

if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
elif [ -f "$REPO/.venv/bin/activate" ]; then
    source "$REPO/.venv/bin/activate"
fi

clear

# Without an operator signature, /nodes returns the active count only (v1.0.2).
echo "==> Active nodes on the network"
curl -s "$NA/nodes" | python3 -m json.tool
sleep 2

echo ""
echo "==> Sending encrypted message over Noise XX"
echo "    to:  $PEER_KEY"
echo "    via: ws://$PEER_HOST:$PEER_PORT"
sleep 1

echo ""
# cd to the repo so relative config paths resolve correctly
( cd "$REPO" && genesis-mesh send \
  --config "$GENESIS_CONFIG" \
  --to "$PEER_KEY" \
  --via "ws://$PEER_HOST:$PEER_PORT" \
  --message "hello from local" )
sleep 2

echo ""
echo "==> Receiving node logs ($VM_USER@$PEER_HOST):"
ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=no \
    -o IdentitiesOnly=yes \
    "$VM_USER@$PEER_HOST" \
    "sudo journalctl -u genesis-mesh-node -n 5 --no-pager 2>/dev/null | grep -E 'DATA|delivered|content'"
sleep 3
