#!/usr/bin/env bash
# =============================================================================
# PREPROD REFERENCE — NOT FOR PRODUCTION
# -----------------------------------------------------------------------------
# Worked example for maintainers: stand up a second Network Authority
# (MiraOS-NA on :8543) beside EPICAL-NA (:8443) and federate them with the live
# USG NA via recognition treaties.
#
# THROWAWAY PREPROD worked example. The genesis block and operator PUBLIC key
# below are public verification data and are safe to keep inline. The NA and
# operator PRIVATE keys are NOT committed — supply them at run time via env vars
# or a local, gitignored secrets file (see examples/preprod/README.md).
#   -> Do NOT reuse for production. Rotate all keys at prod cutover.
#   -> Host/IP and /etc paths are environment-specific; adjust as needed.
# =============================================================================
set -euo pipefail
GENESIS_USER="openclaw"
GENESIS_HOME="/opt/genesis-mesh"
EPICAL_ENDPOINT="http://127.0.0.1:8443"
MIRAOS_ENDPOINT="http://127.0.0.1:8543"
USG_ENDPOINT="https://na.genesismesh.connectorzzz.com"
log(){ printf '\n==> %s\n' "$*"; }

MIRAOS_GENESIS_B64='ew0KICAibmV0d29ya19uYW1lIjogIk1pcmFPUy1OQSIsDQogICJuZXR3b3JrX3ZlcnNpb24iOiAidjAuMSIsDQogICJyb290X3B1YmxpY19rZXkiOiAiaGQreHd5UlovMzROckVuYUxlRlZQZVd6NEtwcXQ0c280RGwwMU1RUDV1cz0iLA0KICAibmV0d29ya19hdXRob3JpdHkiOiB7DQogICAgInB1YmxpY19rZXkiOiAiL0pWVGJhR0dKQ1l2MTFzYXlHRWNXMTNQckh1R3ZURTYvMG9RWC9PUkppbz0iLA0KICAgICJ2YWxpZF9mcm9tIjogIjIwMjYtMDYtMDZUMDk6NTQ6MDEuNzU2NjY4WiIsDQogICAgInZhbGlkX3RvIjogIjIwMjYtMDktMDRUMDk6NTQ6MDEuNzU2NjY4WiINCiAgfSwNCiAgImFsbG93ZWRfY3J5cHRvX3N1aXRlcyI6IFsNCiAgICAiZWQyNTUxOSIsDQogICAgIngyNTUxOSINCiAgXSwNCiAgImFsbG93ZWRfdHJhbnNwb3J0cyI6IFsNCiAgICAicXVpYyIsDQogICAgIndpcmVndWFyZCINCiAgXSwNCiAgInBvbGljeV9tYW5pZmVzdCI6IHsNCiAgICAiaGFzaCI6ICJzaGEyNTY6cGxhY2Vob2xkZXIiLA0KICAgICJ1cmwiOiBudWxsDQogIH0sDQogICJib290c3RyYXBfYW5jaG9ycyI6IFtdLA0KICAic2lnbmF0dXJlcyI6IFsNCiAgICB7DQogICAgICAia2V5X2lkIjogInJzLWxvY2FsIiwNCiAgICAgICJzaWciOiAiby9aUUpYS2RqT1V0UXZmRklLcnlZZGsxTWxYT1UyMkJidnJhdFI3UFplTnpNSGFMUGZIZzNWSW9sTHQ4OUJiOGdyeGFJUkFrUWRwWGExZXpUS0ZpQ3c9PSINCiAgICB9DQogIF0NCn0K'
MIRAOS_OPERATOR_PUB_B64='IyBFZDI1NTE5IFB1YmxpYyBLZXkNCiMgS2V5IElEOiBvcGVyYXRvci1sb2NhbA0KL0FJUGZvRkpEREFTUm5oTUtlVzR2cldPcEFENHgwMk9vZUx6RnR0V1hyND0NCg=='

# --- Private key material (NOT committed) ------------------------------------
# Provide the Ed25519 PRIVATE keys (base64 of the key files) via the environment
# or a local, gitignored secrets file. See examples/preprod/README.md.
SECRETS_FILE="${MIRAOS_SECRETS_FILE:-$(dirname "$0")/miraos-na.secrets.sh}"
if [ -f "$SECRETS_FILE" ]; then
  # shellcheck source=/dev/null
  . "$SECRETS_FILE"
fi
: "${MIRAOS_NA_KEY_B64:?missing NA private key — set MIRAOS_NA_KEY_B64, see examples/preprod/README.md}"
: "${MIRAOS_OPERATOR_KEY_B64:?missing operator private key — set MIRAOS_OPERATOR_KEY_B64, see examples/preprod/README.md}"

log "Materializing MiraOS-NA files"
mkdir -p /tmp/miraos-upload /etc/genesis-mesh/miraos-na/keys /var/lib/genesis-mesh/evidence
printf '%s' "$MIRAOS_GENESIS_B64" | base64 -d >/tmp/miraos-upload/genesis.signed.json
printf '%s' "$MIRAOS_NA_KEY_B64" | base64 -d >/tmp/miraos-upload/na.key
printf '%s' "$MIRAOS_OPERATOR_KEY_B64" | base64 -d >/tmp/miraos-upload/operator.key
printf '%s' "$MIRAOS_OPERATOR_PUB_B64" | base64 -d >/tmp/miraos-upload/operator.pub
python3 -m json.tool /tmp/miraos-upload/genesis.signed.json >/dev/null

log "Installing MiraOS-NA beside existing EPICAL-NA"
install -o root -g root -m 0644 /tmp/miraos-upload/genesis.signed.json /etc/genesis-mesh/miraos-na/genesis.signed.json
install -o "$GENESIS_USER" -g "$GENESIS_USER" -m 0600 /tmp/miraos-upload/na.key /etc/genesis-mesh/miraos-na/keys/na.key
install -o "$GENESIS_USER" -g "$GENESIS_USER" -m 0600 /tmp/miraos-upload/operator.key /etc/genesis-mesh/miraos-na/keys/operator.key
install -o root -g "$GENESIS_USER" -m 0640 /tmp/miraos-upload/operator.pub /etc/genesis-mesh/miraos-na/operator.pub
chown -R "$GENESIS_USER:$GENESIS_USER" /var/lib/genesis-mesh
mira_pub="$(grep -v '^#' /tmp/miraos-upload/operator.pub | tr -d '\r\n')"
printf 'OPERATOR_PUBLIC_KEYS_JSON={"operator-local":"%s"}\n' "$mira_pub" >/etc/genesis-mesh/miraos-na/operator-keys.env
chown root:"$GENESIS_USER" /etc/genesis-mesh/miraos-na/operator-keys.env
chmod 0640 /etc/genesis-mesh/miraos-na/operator-keys.env

cat >/etc/systemd/system/genesis-mesh-miraos-na.service <<EOF
[Unit]
Description=Genesis Mesh MiraOS-NA Network Authority
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=${GENESIS_USER}
WorkingDirectory=${GENESIS_HOME}
Environment=SERVICE_ROLE=na
Environment=GENESIS_FILE=/etc/genesis-mesh/miraos-na/genesis.signed.json
Environment=NA_PRIVATE_KEY_FILE=/etc/genesis-mesh/miraos-na/keys/na.key
Environment=DB_PATH=/var/lib/genesis-mesh/miraos-na.db
Environment=PORT=8543
Environment=GENESIS_LOG_LEVEL=INFO
Environment=GENESIS_LOG_FORMAT=json
EnvironmentFile=/etc/genesis-mesh/miraos-na/operator-keys.env
ExecStart=${GENESIS_HOME}/.venv/bin/gunicorn --workers 2 --worker-class sync --timeout 30 --max-requests 1000 --bind 0.0.0.0:8543 genesis_mesh.na_service.wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

log "Starting MiraOS-NA"
systemctl daemon-reload
systemctl enable --now genesis-mesh-miraos-na

wait_health(){
  endpoint="$1"; label="$2"
  for i in $(seq 1 45); do
    if curl -fsS "$endpoint/healthz" >/tmp/"$label".health.json 2>/dev/null; then printf '%s ' "$label"; cat /tmp/"$label".health.json; printf '\n'; return 0; fi
    sleep 2
  done
  systemctl status genesis-mesh-na genesis-mesh-miraos-na --no-pager || true
  journalctl -u genesis-mesh-miraos-na -n 80 --no-pager || true
  return 1
}
wait_health "$EPICAL_ENDPOINT" epical
wait_health "$MIRAOS_ENDPOINT" miraos
wait_health "$USG_ENDPOINT" usg

issue_link(){
  acceptor="$1"; issuer="$2"; key="$3"; name="$4"; evidence_name="$5"; evidence="/var/lib/genesis-mesh/evidence/$evidence_name"
  log "Treaty: $name"
  "$GENESIS_HOME/.venv/bin/genesis-mesh" federation bootstrap \
    --acceptor "$acceptor" \
    --issuer "$issuer" \
    --operator-key "$key" \
    --operator-key-id operator-local \
    --claim link="$name" \
    --validity-hours 720 \
    --evidence "$evidence" \
    --format json \
    --yes >/tmp/"$evidence_name"
  python3 -c "import json; d=json.load(open('/tmp/$evidence_name')); p=d.get('trust_path') or {}; print(json.dumps({'to':p.get('to'),'trusted':p.get('trusted'),'treaty_id':(p.get('path') or [{}])[0].get('treaty_id'),'evidence':'$evidence'}, indent=2))"
}

issue_link "$MIRAOS_ENDPOINT" "$EPICAL_ENDPOINT" /etc/genesis-mesh/miraos-na/keys/operator.key MiraOS-NA-to-EPICAL-NA miraos-to-epical.json
issue_link "$MIRAOS_ENDPOINT" "$USG_ENDPOINT" /etc/genesis-mesh/miraos-na/keys/operator.key MiraOS-NA-to-USG miraos-to-usg.json
issue_link "$EPICAL_ENDPOINT" "$MIRAOS_ENDPOINT" /etc/genesis-mesh/keys/operator.key EPICAL-NA-to-MiraOS-NA epical-to-miraos.json
issue_link "$EPICAL_ENDPOINT" "$USG_ENDPOINT" /etc/genesis-mesh/keys/operator.key EPICAL-NA-to-USG epical-to-usg.json

log "MiraOS connectome"
curl -fsS "$MIRAOS_ENDPOINT/connectome.json" | python3 -m json.tool

log "EPICAL connectome"
curl -fsS "$EPICAL_ENDPOINT/connectome.json" | python3 -m json.tool

log "Services"
systemctl is-active genesis-mesh-na
systemctl is-active genesis-mesh-miraos-na
