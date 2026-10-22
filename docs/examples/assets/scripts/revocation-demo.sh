#!/bin/bash
# Genesis Mesh revocation demo
#
# Starts a temporary local Network Authority on 127.0.0.1:8443, enrolls one
# node silently, then revokes its certificate and shows the 403.
#
# Variables (all optional):
#   GM_REPO   repository root (default: git rev-parse --show-toplevel, else the
#             current directory); used to find a virtualenv to activate
#
# Record with: asciinema rec revocation.cast --command "bash docs/examples/assets/scripts/revocation-demo.sh"
# Convert with: agg revocation.cast docs/examples/assets/images/genesis-mesh-revocation.gif

REPO="${GM_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

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
CERT=$(python3 -c 'import json; print(json.load(open(".genesis-mesh/node.cert.json"))["cert_id"])')

# ── Story starts here ─────────────────────────────────────────────────────────
clear

# Without an operator signature, /nodes returns the active count only (v1.0.2).
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
