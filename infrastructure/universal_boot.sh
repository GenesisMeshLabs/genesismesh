#!/usr/bin/env sh
set -eu

BOOTSTRAP_ENDPOINT="${bootstrap_endpoint}"
GENESIS_URI="${genesis_uri}"

log() {
  printf '%s %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

ensure_genesis_file() {
  mkdir -p /etc/genesis

  if [ -f /etc/genesis/genesis.signed.json ]; then
    return
  fi

  if [ -n "$GENESIS_URI" ]; then
    log "Attempting to fetch genesis from ${GENESIS_URI}"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$GENESIS_URI" -o /etc/genesis/genesis.signed.json || true
    elif command -v wget >/dev/null 2>&1; then
      wget -qO /etc/genesis/genesis.signed.json "$GENESIS_URI" || true
    fi
  fi
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    log "Detected apt-based distro"
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      ca-certificates curl gnupg lsb-release \
      docker.io docker-compose-plugin \
      python3 python3-pip \
      wireguard
  elif command -v apk >/dev/null 2>&1; then
    log "Detected Alpine"
    apk update
    apk add --no-cache \
      ca-certificates curl \
      docker docker-cli-compose \
      python3 py3-pip \
      wireguard-tools
  elif command -v dnf >/dev/null 2>&1; then
    log "Detected dnf-based distro"
    dnf -y update
    dnf -y install \
      ca-certificates curl \
      docker docker-compose-plugin \
      python3 python3-pip \
      wireguard-tools
  else
    log "Unsupported distribution: no apt, apk, or dnf found"
    exit 1
  fi
}

configure_docker() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker
    systemctl start docker
  elif command -v service >/dev/null 2>&1; then
    service docker start || true
  fi
}

create_waiting_state_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    log "systemctl not available; skipping waiting-state service enablement"
    return
  fi

  cat <<'SERVICE' >/etc/systemd/system/genesis-waiting.service
[Unit]
Description=Genesis Mesh Waiting State
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/sh -c 'while [ ! -f /etc/genesis/genesis.signed.json ]; do sleep 5; done'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

  systemctl daemon-reload
  systemctl enable genesis-waiting.service
  systemctl start genesis-waiting.service
}

main() {
  log "Starting universal boot sequence"
  install_packages
  configure_docker
  ensure_genesis_file
  create_waiting_state_service
  log "Universal boot sequence complete"
  log "Bootstrap endpoint: ${BOOTSTRAP_ENDPOINT}"
}

main "$@"
