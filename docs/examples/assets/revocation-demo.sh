#!/bin/bash
# Genesis Mesh revocation demo
# Record with: asciinema rec revocation.cast --command "bash docs/examples/assets/revocation-demo.sh"
# Convert with: agg revocation.cast docs/examples/assets/genesis-mesh-revocation.gif

REPO=$(pwd)

# Activate venv -- try Linux home venv, then project-local venv
if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
elif [ -f "$REPO/.venv-linux/bin/activate" ]; then
    source "$REPO/.venv-linux/bin/activate"
elif [ -f "$REPO/.venv/bin/activate" ]; then
    source "$REPO/.venv/bin/activate"
fi

# ── Silent setup (not part of the story) ─────────────────────────────────────
DEMO=$(mktemp -d)
cd "$DEMO"
genesis-mesh init >/dev/null 2>&1
genesis-mesh na start >na.log 2>&1 &
until curl -sf http://127.0.0.1:8443/healthz >/dev/null; do sleep 0.3; done
INVITE=$(genesis-mesh admin invite --role anchor 2>/dev/null)
genesis-mesh join --na http://127.0.0.1:8443 --token $INVITE >/dev/null 2>&1
CERT=$(python3 "$REPO/docs/examples/assets/get-cert-id.py")

# ── Story starts here ─────────────────────────────────────────────────────────
clear

echo "--- 1 active node ---"
curl -s http://127.0.0.1:8443/nodes | python3 -m json.tool
sleep 2

echo ""
echo "==> genesis-mesh admin revoke $CERT --reason key_compromise"
genesis-mesh admin revoke $CERT --reason key_compromise
sleep 2

echo ""
echo "==> genesis-mesh join --na http://127.0.0.1:8443"
genesis-mesh join --na http://127.0.0.1:8443 || true
sleep 1

echo ""
grep 403 na.log | tail -1
sleep 2

echo ""
echo "--- 0 active nodes ---"
curl -s http://127.0.0.1:8443/nodes | python3 -m json.tool
sleep 2

kill %1 2>/dev/null
