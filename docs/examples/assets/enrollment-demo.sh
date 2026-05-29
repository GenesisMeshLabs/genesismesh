#!/bin/bash
# Genesis Mesh enrollment demo
# Record with: asciinema rec enrollment.cast --command "bash docs/examples/assets/enrollment-demo.sh"
# Convert with: agg enrollment.cast docs/examples/assets/genesis-mesh-enrollment.gif

set -e

REPO=$(pwd)

# Activate venv -- try Linux home venv, then project-local venv
if [ -f "$HOME/gm-venv/bin/activate" ]; then
    source "$HOME/gm-venv/bin/activate"
elif [ -f "$REPO/.venv-linux/bin/activate" ]; then
    source "$REPO/.venv-linux/bin/activate"
elif [ -f "$REPO/.venv/bin/activate" ]; then
    source "$REPO/.venv/bin/activate"
fi

DEMO=$(mktemp -d)
cd "$DEMO"

echo "==> genesis-mesh init"
genesis-mesh init
sleep 1

echo ""
echo "==> starting Network Authority"
genesis-mesh na start >na.log 2>&1 &
until curl -sf http://127.0.0.1:8443/healthz >/dev/null; do sleep 0.3; done
echo "Network Authority ready"
sleep 1

echo ""
echo "==> creating invite token"
INVITE=$(genesis-mesh admin invite --role anchor)
echo "Token: $INVITE"
sleep 1

echo ""
echo "==> joining network"
genesis-mesh join --na http://127.0.0.1:8443 --token $INVITE
sleep 1

echo ""
echo "--- active nodes before revoke ---"
curl -s http://127.0.0.1:8443/nodes | python3 -m json.tool
sleep 1

echo ""
echo "==> revoking certificate"
CERT=$(python3 "$REPO/docs/examples/assets/get-cert-id.py")
echo "Certificate: $CERT"
genesis-mesh admin revoke $CERT --reason key_compromise
sleep 1

echo ""
echo "--- heartbeat attempt with revoked identity ---"
genesis-mesh join --na http://127.0.0.1:8443 || true
sleep 1

echo ""
echo "--- NA rejected with 403 ---"
grep 403 na.log | tail -3
sleep 1

echo ""
echo "--- active nodes after revoke ---"
curl -s http://127.0.0.1:8443/nodes | python3 -m json.tool
sleep 1

kill %1 2>/dev/null
echo ""
echo "done"
