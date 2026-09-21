#!/usr/bin/env bash
# Isolated reference-overlay deployment. Run as root with an exact reviewed SHA.
set -euo pipefail
BUILD=${1:?Pass the reviewed Git commit SHA}
[[ "$BUILD" =~ ^[0-9a-f]{40}$ ]] || exit 2
CODE=/opt/genesis-mesh-public
DATA=/var/lib/genesis-mesh-public
ARCHIVE=/var/backups/genesis-mesh-offline/$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$ARCHIVE"

# A consistent SQLite backup, not a copy of an open WAL database.
export ARCHIVE
/opt/genesis-mesh/.venv/bin/python - <<'PY'
import os, sqlite3
from pathlib import Path
archive = Path(os.environ['ARCHIVE'])
source = sqlite3.connect('file:/var/lib/genesis-mesh/na.db?mode=ro', uri=True)
with sqlite3.connect(archive / 'na.db') as target:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
source.close()
PY
tar -czf "$ARCHIVE/legacy-configuration.tar.gz" /etc/genesis /etc/genesis-mesh \
    /etc/systemd/system/genesis-mesh-na.service /etc/systemd/system/genesis-mesh-na.service.d \
    /etc/nginx/sites-available/genesis-mesh-na
cp /etc/nginx/sites-available/genesis-mesh-na "$ARCHIVE/nginx.conf"
chmod 0600 "$ARCHIVE"/*
(cd "$ARCHIVE" && sha256sum na.db legacy-configuration.tar.gz nginx.conf > SHA256SUMS)
systemctl stop genesis-mesh-public.service genesis-mesh-public-publisher.service 2>/dev/null || true
if ss -ltnH 'sport = :28443' | grep -q .; then
    echo 'Public reference port 28443 is already occupied; refusing deployment' >&2
    exit 1
fi

if [[ ! -d "$CODE/.git" ]]; then
    git clone https://github.com/GenesisMeshLabs/genesismesh.git "$CODE"
fi
# Fetch every branch so any reviewed SHA stays deployable once its branch is merged and deleted.
git -C "$CODE" fetch origin
git -C "$CODE" checkout --detach "$BUILD"
python3.12 -m venv "$CODE/.venv"
"$CODE/.venv/bin/python" -m pip install -r "$CODE/requirements.txt" -e "$CODE"
getent group gm-demo-read >/dev/null || groupadd --system gm-demo-read
id gm-demo-maint >/dev/null 2>&1 || useradd --system --gid gm-demo-read --home-dir "$DATA" --shell /usr/sbin/nologin gm-demo-maint
id gm-demo-web >/dev/null 2>&1 || useradd --system --gid gm-demo-read --home-dir /nonexistent --shell /usr/sbin/nologin gm-demo-web
cd "$CODE"
if [[ ! -e "$DATA" ]]; then
    "$CODE/.venv/bin/python" -m examples.public_dashboard.seed "$DATA"
fi
install -d -m 0750 "$DATA/published"
chown -R gm-demo-maint:gm-demo-read "$DATA"
chmod 0750 "$DATA" "$DATA/published"
chmod 0700 "$DATA/keys"
chmod 0640 "$DATA/public.db" "$DATA/root.pub"

cat >/etc/systemd/system/genesis-mesh-public-publisher.service <<EOF
[Unit]
Description=Genesis Mesh loopback signed demo publisher
After=network.target
[Service]
User=gm-demo-web
Group=gm-demo-read
WorkingDirectory=$CODE
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$CODE/.venv/bin/python -m examples.public_dashboard.publisher $DATA/published
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
InaccessiblePaths=$DATA/keys /var/backups/genesis-mesh-offline
RestrictAddressFamilies=AF_INET AF_UNIX
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/genesis-mesh-public.service <<EOF
[Unit]
Description=Genesis Mesh sanitized public reference dashboard
After=network.target
[Service]
User=gm-demo-web
Group=gm-demo-read
WorkingDirectory=$CODE
Environment=PUBLIC_DEMO_DIR=$DATA
Environment=GENESIS_BUILD_SHA=$BUILD
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$CODE/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:28443 --timeout 30 --max-requests 1000 'examples.public_dashboard.app:configured_app()'
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
InaccessiblePaths=$DATA/keys /var/backups/genesis-mesh-offline /var/lib/genesis-mesh /etc/genesis-mesh
RestrictAddressFamilies=AF_INET AF_UNIX
CapabilityBoundingSet=
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/genesis-mesh-public-maintenance.service <<EOF
[Unit]
Description=Genesis Mesh signed heartbeat import and daily canary
After=genesis-mesh-public-publisher.service
Requires=genesis-mesh-public-publisher.service
OnFailure=genesis-mesh-public-alert.service
[Service]
Type=oneshot
User=gm-demo-maint
Group=gm-demo-read
WorkingDirectory=$CODE
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/flock -n $DATA/maintenance.lock $CODE/.venv/bin/python -m examples.public_dashboard.maintenance $DATA
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA
UMask=0027
TimeoutStartSec=180
EOF
cat >/etc/systemd/system/genesis-mesh-public-maintenance.timer <<'EOF'
[Unit]
Description=Hourly signed demo heartbeat imports
[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=60
[Install]
WantedBy=timers.target
EOF
cat >/etc/systemd/system/genesis-mesh-public-alert.service <<'EOF'
[Unit]
Description=Local alert for failed public reference feed imports
[Service]
Type=oneshot
ExecStart=/usr/bin/logger -p daemon.err -t genesis-mesh-public PUBLIC_FEED_IMPORT_FAILED_check_systemctl_status_genesis-mesh-public-maintenance
EOF
systemctl daemon-reload
systemctl enable --now genesis-mesh-public-publisher.service
systemctl restart genesis-mesh-public-publisher.service
systemctl start genesis-mesh-public-maintenance.service
systemctl enable --now genesis-mesh-public.service
systemctl restart genesis-mesh-public.service
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:28443/readyz; then break; fi
    sleep 1
done
curl -fsS http://127.0.0.1:28443/sovereign.json | "$CODE/.venv/bin/python" -c 'import json,sys; assert json.load(sys.stdin)["sovereign_id"] == "gm-demo-public-na"'
curl -fsS http://127.0.0.1:28443/evidence.json > "$DATA/check-evidence.json"
"$CODE/.venv/bin/python" -m examples.public_dashboard.verify "$DATA/check-evidence.json" --root-key "$(cat "$DATA/root.pub")"
if runuser -u gm-demo-web -- test -r "$DATA/keys/gm-demo-public-na.key"; then
    echo 'Web user can read signing key; refusing cutover' >&2
    exit 1
fi

cat >/etc/nginx/conf.d/genesis-mesh-public.conf <<'EOF'
limit_req_zone $binary_remote_addr zone=gm_public:10m rate=2r/s;
proxy_cache_path /var/cache/nginx/gm-public levels=1:2 keys_zone=gm_public_cache:10m max_size=50m inactive=5m;
log_format gm_public_minimal '$time_iso8601 $request_method $status $body_bytes_sent';
EOF
install -d -o www-data -g www-data /var/cache/nginx/gm-public
cat >/etc/nginx/sites-available/genesis-mesh-na <<'EOF'
server {
    listen 443 ssl;
    server_name na.genesismesh.connectorzzz.com;
    ssl_certificate /etc/letsencrypt/live/na.genesismesh.connectorzzz.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/na.genesismesh.connectorzzz.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    server_tokens off;
    access_log /var/log/nginx/gm-public-access.log gm_public_minimal;
    error_log /var/log/nginx/gm-public-error.log warn;
    add_header Strict-Transport-Security 'max-age=31536000' always;
    add_header X-Content-Type-Options nosniff always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;
    location / {
        limit_except GET { deny all; }
        limit_req zone=gm_public burst=30 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:28443;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache gm_public_cache;
        proxy_cache_valid 200 15s;
        proxy_cache_key "$scheme$host$request_uri";
    }
}
server {
    listen 80;
    server_name na.genesismesh.connectorzzz.com;
    server_tokens off;
    access_log /var/log/nginx/gm-public-access.log gm_public_minimal;
    return 301 https://na.genesismesh.connectorzzz.com$request_uri;
}
EOF
# Use a distinct log directory to avoid overlap with Ubuntu's nginx wildcard.
install -d -o www-data -g adm -m 0750 /var/log/genesis-mesh-public
sed -i 's@/var/log/nginx/gm-public-@/var/log/genesis-mesh-public/@g' /etc/nginx/sites-available/genesis-mesh-na
cat >/etc/logrotate.d/genesis-mesh-public <<'EOF'
/var/log/genesis-mesh-public/*.log {
    daily
    rotate 1
    maxage 1
    missingok
    notifempty
    compress
    create 0640 www-data adm
    sharedscripts
    postrotate
        /usr/sbin/nginx -s reopen
    endscript
}
EOF
if ! nginx -t; then
    cp "$ARCHIVE/nginx.conf" /etc/nginx/sites-available/genesis-mesh-na
    exit 1
fi
systemctl reload nginx
systemctl enable --now genesis-mesh-public-maintenance.timer

# Keep the old evidence offline. No deletion or renaming of signed records.
systemctl stop genesis-mesh-trust-cycle-canary.timer genesis-mesh-trust-cycle-canary.service
systemctl disable genesis-mesh-trust-cycle-canary.timer
systemctl stop genesis-mesh-node genesis-mesh-node-d genesis-mesh-na genesis-mesh-canary-001-na genesis-mesh-canary-anonymous-na
systemctl disable genesis-mesh-node genesis-mesh-node-d genesis-mesh-na genesis-mesh-canary-001-na genesis-mesh-canary-anonymous-na
# Final stopped-state copy captures any writes since the first online backup.
tar -czf "$ARCHIVE/legacy-state.tar.gz" /var/lib/genesis-mesh
chmod 0600 "$ARCHIVE/legacy-state.tar.gz"
(cd "$ARCHIVE" && sha256sum legacy-state.tar.gz >> SHA256SUMS)
systemctl is-active genesis-mesh-public genesis-mesh-public-publisher
systemctl list-timers genesis-mesh-public-maintenance.timer --no-pager
printf 'Offline backup: %s\nBuild: %s\n' "$ARCHIVE" "$BUILD"
