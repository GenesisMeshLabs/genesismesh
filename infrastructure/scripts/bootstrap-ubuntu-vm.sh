#!/usr/bin/env bash
set -euo pipefail

# Provider-neutral Genesis Mesh installer for a fresh Ubuntu VM/VPS.
# It installs the package, writes systemd units, and optionally configures
# Nginx/TLS. It deliberately does not create production secrets.

GENESIS_REPO_URL="${GENESIS_REPO_URL:-https://github.com/thaersaidi/genesismesh.git}"
GENESIS_REF="${GENESIS_REF:-main}"
GENESIS_ROLE="${GENESIS_ROLE:-na}" # na, router, all
GENESIS_USER="${GENESIS_USER:-${SUDO_USER:-genesis}}"
GENESIS_HOME="${GENESIS_HOME:-/opt/genesis-mesh}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

GENESIS_FILE="${GENESIS_FILE:-/etc/genesis/genesis.signed.json}"
NA_PRIVATE_KEY_FILE="${NA_PRIVATE_KEY_FILE:-/etc/genesis-mesh/keys/na.key}"
DB_PATH="${DB_PATH:-/var/lib/genesis-mesh/na.db}"
NA_PORT="${NA_PORT:-8443}"
NA_ENDPOINT="${NA_ENDPOINT:-http://127.0.0.1:${NA_PORT}}"
OPERATOR_PUBLIC_KEYS_JSON="${OPERATOR_PUBLIC_KEYS_JSON:-}"

START_SERVICES="${START_SERVICES:-true}"
ENABLE_NGINX="${ENABLE_NGINX:-false}"
GENESIS_DOMAIN="${GENESIS_DOMAIN:-}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"

ROUTER_B_CONFIG="${ROUTER_B_CONFIG:-/home/${GENESIS_USER}/.genesis-mesh-demo-node/config.toml}"
ROUTER_B_PORT="${ROUTER_B_PORT:-7443}"
ROUTER_D_CONFIG="${ROUTER_D_CONFIG:-/home/${GENESIS_USER}/.genesis-mesh-node-d/config.toml}"
ROUTER_D_PORT="${ROUTER_D_PORT:-7444}"

log() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf 'WARNING: %s\n' "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

as_bool() {
  case "${1,,}" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "run this script as root, for example: sudo bash infrastructure/scripts/bootstrap-ubuntu-vm.sh"
  fi
}

role_includes() {
  local role="$1"
  [ "$GENESIS_ROLE" = "$role" ] || [ "$GENESIS_ROLE" = "all" ]
}

run_as_genesis_user() {
  sudo -H -u "$GENESIS_USER" bash -lc "$*"
}

ensure_user() {
  if id "$GENESIS_USER" >/dev/null 2>&1; then
    return
  fi

  log "Creating system user ${GENESIS_USER}"
  useradd --system --create-home --shell /bin/bash "$GENESIS_USER"
}

install_packages() {
  log "Installing base packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    ca-certificates \
    curl \
    git \
    sqlite3 \
    software-properties-common

  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    log "Installing Python 3.12"
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update
    apt-get install -y python3.12 python3.12-venv python3.12-dev
  else
    apt-get install -y python3.12-venv || true
  fi

  if as_bool "$ENABLE_NGINX"; then
    apt-get install -y nginx certbot python3-certbot-nginx
  fi
}

checkout_repo() {
  log "Checking out ${GENESIS_REPO_URL} at ${GENESIS_REF}"
  mkdir -p "$(dirname "$GENESIS_HOME")"

  if [ -d "$GENESIS_HOME/.git" ]; then
    git -C "$GENESIS_HOME" fetch --tags origin
  else
    git clone "$GENESIS_REPO_URL" "$GENESIS_HOME"
  fi

  if git -C "$GENESIS_HOME" show-ref --verify --quiet "refs/tags/${GENESIS_REF}"; then
    git -C "$GENESIS_HOME" checkout --force "tags/${GENESIS_REF}"
  elif git -C "$GENESIS_HOME" show-ref --verify --quiet "refs/remotes/origin/${GENESIS_REF}"; then
    git -C "$GENESIS_HOME" checkout --force "origin/${GENESIS_REF}"
  else
    git -C "$GENESIS_HOME" checkout --force "$GENESIS_REF"
  fi

  chown -R "$GENESIS_USER:$GENESIS_USER" "$GENESIS_HOME"
}

install_python_env() {
  log "Installing Genesis Mesh Python environment"
  run_as_genesis_user "
    cd '$GENESIS_HOME' &&
    '$PYTHON_BIN' -m venv .venv &&
    . .venv/bin/activate &&
    python -m pip install --upgrade pip &&
    python -m pip install -r requirements.txt &&
    python -m pip install -e . &&
    python -m compileall genesis_mesh -q
  "
}

prepare_directories() {
  log "Preparing directories"
  mkdir -p \
    "$(dirname "$GENESIS_FILE")" \
    "$(dirname "$NA_PRIVATE_KEY_FILE")" \
    "$(dirname "$DB_PATH")" \
    /etc/genesis-mesh

  chown -R "$GENESIS_USER:$GENESIS_USER" \
    "$(dirname "$NA_PRIVATE_KEY_FILE")" \
    "$(dirname "$DB_PATH")"

  chmod 0755 "$(dirname "$GENESIS_FILE")"
  chmod 0750 "$(dirname "$NA_PRIVATE_KEY_FILE")" "$(dirname "$DB_PATH")"

  if [ -n "$OPERATOR_PUBLIC_KEYS_JSON" ]; then
    log "Writing operator public-key environment"
    cat >/etc/genesis-mesh/operator-keys.env <<EOF
OPERATOR_PUBLIC_KEYS_JSON=${OPERATOR_PUBLIC_KEYS_JSON}
EOF
    chmod 0640 /etc/genesis-mesh/operator-keys.env
    chown root:"$GENESIS_USER" /etc/genesis-mesh/operator-keys.env
  elif [ ! -f /etc/genesis-mesh/operator-keys.env ]; then
    warn "OPERATOR_PUBLIC_KEYS_JSON was not provided; admin endpoints will reject operator requests until configured"
  fi
}

write_na_unit() {
  log "Writing genesis-mesh-na.service"
  cat >/etc/systemd/system/genesis-mesh-na.service <<EOF
[Unit]
Description=Genesis Mesh Network Authority
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=${GENESIS_USER}
WorkingDirectory=${GENESIS_HOME}
Environment=SERVICE_ROLE=na
Environment=GENESIS_FILE=${GENESIS_FILE}
Environment=NA_PRIVATE_KEY_FILE=${NA_PRIVATE_KEY_FILE}
Environment=DB_PATH=${DB_PATH}
Environment=PORT=${NA_PORT}
EnvironmentFile=-/etc/genesis-mesh/operator-keys.env
ExecStart=${GENESIS_HOME}/.venv/bin/gunicorn --workers 4 --worker-class sync --timeout 30 --max-requests 1000 --bind 0.0.0.0:${NA_PORT} genesis_mesh.na_service.wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

write_router_unit() {
  local name="$1"
  local config="$2"
  local port="$3"

  log "Writing ${name}.service"
  cat >"/etc/systemd/system/${name}.service" <<EOF
[Unit]
Description=Genesis Mesh Router (${name})
After=network-online.target genesis-mesh-na.service
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=${GENESIS_USER}
WorkingDirectory=${GENESIS_HOME}
ExecStart=${GENESIS_HOME}/.venv/bin/genesis-mesh join --na ${NA_ENDPOINT} --config ${config} --persistent --listen-port ${port}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
}

configure_nginx() {
  if ! as_bool "$ENABLE_NGINX"; then
    return
  fi
  [ -n "$GENESIS_DOMAIN" ] || die "ENABLE_NGINX=true requires GENESIS_DOMAIN"

  log "Configuring Nginx reverse proxy for ${GENESIS_DOMAIN}"
  cat >/etc/nginx/sites-available/genesis-mesh-na <<EOF
server {
    listen 80;
    server_name ${GENESIS_DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${NA_PORT};
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

  ln -sf /etc/nginx/sites-available/genesis-mesh-na /etc/nginx/sites-enabled/genesis-mesh-na
  nginx -t
  systemctl reload nginx

  if [ -n "$LETSENCRYPT_EMAIL" ]; then
    log "Requesting Let's Encrypt certificate for ${GENESIS_DOMAIN}"
    certbot --nginx \
      -d "$GENESIS_DOMAIN" \
      --non-interactive \
      --agree-tos \
      -m "$LETSENCRYPT_EMAIL"
  else
    warn "LETSENCRYPT_EMAIL not set; Nginx is configured for HTTP only"
  fi
}

start_services() {
  systemctl daemon-reload

  if role_includes "na"; then
    if [ ! -f "$GENESIS_FILE" ] || [ ! -f "$NA_PRIVATE_KEY_FILE" ]; then
      cat >&2 <<EOF
ERROR: NA secrets are missing.

Upload them before starting the Network Authority:

  scp .genesis-mesh/genesis.signed.json ${GENESIS_USER}@<vm-ip>:/tmp/
  scp .genesis-mesh/keys/na.key         ${GENESIS_USER}@<vm-ip>:/tmp/

Then on the VM:

  sudo mv /tmp/genesis.signed.json ${GENESIS_FILE}
  sudo mv /tmp/na.key ${NA_PRIVATE_KEY_FILE}
  sudo chown root:root ${GENESIS_FILE}
  sudo chown ${GENESIS_USER}:${GENESIS_USER} ${NA_PRIVATE_KEY_FILE}
  sudo chmod 0644 ${GENESIS_FILE}
  sudo chmod 0600 ${NA_PRIVATE_KEY_FILE}
  sudo systemctl enable --now genesis-mesh-na
EOF
      exit 1
    fi

    if as_bool "$START_SERVICES"; then
      log "Starting Network Authority"
      systemctl enable --now genesis-mesh-na
    fi
  fi

  if role_includes "router"; then
    if [ ! -f "$ROUTER_B_CONFIG" ]; then
      warn "Router B config not found at ${ROUTER_B_CONFIG}; enrol it before starting genesis-mesh-node"
    elif as_bool "$START_SERVICES"; then
      systemctl enable --now genesis-mesh-node
    fi

    if [ ! -f "$ROUTER_D_CONFIG" ]; then
      warn "Router D config not found at ${ROUTER_D_CONFIG}; enrol it before starting genesis-mesh-node-d"
    elif as_bool "$START_SERVICES"; then
      systemctl enable --now genesis-mesh-node-d
    fi
  fi
}

print_summary() {
  log "Bootstrap complete"
  cat <<EOF
Repository: ${GENESIS_HOME}
Ref:        ${GENESIS_REF}
User:       ${GENESIS_USER}
Role:       ${GENESIS_ROLE}

Important paths:
  Genesis block: ${GENESIS_FILE}
  NA key:        ${NA_PRIVATE_KEY_FILE}
  NA database:   ${DB_PATH}

Useful checks:
  sudo systemctl status genesis-mesh-na
  curl http://127.0.0.1:${NA_PORT}/healthz
  curl http://127.0.0.1:${NA_PORT}/readyz
EOF
}

main() {
  need_root
  ensure_user
  install_packages
  checkout_repo
  install_python_env
  prepare_directories

  if role_includes "na"; then
    write_na_unit
  fi

  if role_includes "router"; then
    write_router_unit "genesis-mesh-node" "$ROUTER_B_CONFIG" "$ROUTER_B_PORT"
    write_router_unit "genesis-mesh-node-d" "$ROUTER_D_CONFIG" "$ROUTER_D_PORT"
  fi

  configure_nginx
  start_services
  print_summary
}

main "$@"
