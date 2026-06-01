#!/bin/bash
# Genesis Mesh P2P messaging demo
# Record with: asciinema rec p2p-send.cast --command "bash docs/examples/assets/scripts/p2p-send-demo.sh"
# Convert with: agg p2p-send.cast docs/examples/assets/images/genesis-mesh-p2p-send.gif
#
# Prerequisites:
#   - genesis-mesh installed and configured (genesis-mesh.toml present)
#   - A remote node running: genesis-mesh join --persistent --listen-port 7443
#   - PEER_HOST and PEER_KEY set below

PEER_HOST="${PEER_HOST:-4.223.130.190}"
PEER_KEY="${PEER_KEY:-Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8=}"
PEER_PORT="${PEER_PORT:-7443}"
SSH_KEY="${SSH_KEY:-/mnt/c/Users/thaer/.ssh/id_rsa}"

# Config lives in the Windows repo — resolve from WSL2
GENESIS_CONFIG="${GENESIS_CONFIG:-/mnt/c/Source/genesismesh/genesis-mesh.toml}"

REPO=$(pwd)

if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
elif [ -f "$REPO/.venv/bin/activate" ]; then
    source "$REPO/.venv/bin/activate"
fi

clear

echo "==> Enrolled nodes on the network"
curl -s "https://na.genesismesh.connectorzzz.com/nodes" | python3 -m json.tool
sleep 2

echo ""
echo "==> Sending encrypted message over Noise XX"
echo "    to:  $PEER_KEY"
echo "    via: ws://$PEER_HOST:$PEER_PORT"
sleep 1

echo ""
# cd to the repo so relative config paths resolve correctly
( cd /mnt/c/Source/genesismesh && genesis-mesh send \
  --config "$GENESIS_CONFIG" \
  --to "$PEER_KEY" \
  --via "ws://$PEER_HOST:$PEER_PORT" \
  --message "hello from local" )
sleep 2

echo ""
echo "==> Receiving node logs (azureuser@$PEER_HOST):"
ssh -i "$SSH_KEY" \
    -o StrictHostKeyChecking=no \
    -o IdentitiesOnly=yes \
    "azureuser@$PEER_HOST" \
    "sudo journalctl -u genesis-mesh-node -n 5 --no-pager 2>/dev/null | grep -E 'DATA|delivered|content'"
sleep 3
