# Network Authority VM Bootstrap

End-to-end commands to bring up the live Network Authority on a fresh Ubuntu
22.04 VM. The Terraform module at `infrastructure/azure/` provisions the VM
itself; everything below runs on the VM after it boots.

This runbook reflects the actual commands that built the live deployment at
[https://na.genesismesh.connectorzzz.com](https://na.genesismesh.connectorzzz.com).

## Provider-neutral bootstrap script

Use the Azure release deployment workflow when updating the existing Azure VM.
Use the provider-neutral bootstrap script when you already have a fresh Ubuntu
VM or VPS from another provider, such as DigitalOcean, Hetzner, Vultr, a local
hypervisor, or a second cloud used for independent-sovereign testing.

The script lives at:

```text
infrastructure/scripts/bootstrap-ubuntu-vm.sh
```

It installs Python, clones the repository, creates the virtual environment,
writes systemd units, and optionally configures Nginx and Let's Encrypt. It does
not create production secrets. Upload `genesis.signed.json`, `na.key`, and
operator public-key configuration separately.

For a Network Authority on a generic Ubuntu VM:

```bash
sudo GENESIS_ROLE=na \
  GENESIS_REF=main \
  GENESIS_USER=ubuntu \
  ENABLE_NGINX=true \
  GENESIS_DOMAIN=nb.genesismesh.connectorzzz.com \
  LETSENCRYPT_EMAIL=ops@example.com \
  OPERATOR_PUBLIC_KEYS_JSON='{"operator-local":"<BASE64_OPERATOR_PUBLIC_KEY>"}' \
  bash infrastructure/scripts/bootstrap-ubuntu-vm.sh
```

If the NA secrets are not present yet, the script stops with the exact `scp`,
`mv`, ownership, and `systemctl` commands needed to finish the setup.

For a fresh named sovereign, generate the VM artifacts with explicit paths so
the systemd unit and operator runbook agree on identity, keys, and database
location:

```bash
cd /opt/genesis-mesh
source .venv/bin/activate

sudo mkdir -p /etc/genesis /etc/genesis-mesh/keys /var/lib/genesis-mesh
sudo chown -R "$USER":"$USER" /etc/genesis /etc/genesis-mesh /var/lib/genesis-mesh

genesis-mesh init \
  --home /tmp/genesis-mesh-nb \
  --network-name USG-NB \
  --na-endpoint http://164.92.250.135:8443 \
  --genesis-file /etc/genesis/genesis.signed.json \
  --na-private-key-file /etc/genesis-mesh/keys/na.key \
  --operator-private-key-file /etc/genesis-mesh/keys/operator.key \
  --operator-public-key-file /etc/genesis-mesh/operator.pub \
  --db-path /var/lib/genesis-mesh/na.db \
  --na-host 0.0.0.0 \
  --na-port 8443 \
  --force

chmod 0644 /etc/genesis/genesis.signed.json
chmod 0600 /etc/genesis-mesh/keys/na.key /etc/genesis-mesh/keys/operator.key
```

After the service starts, verify the public sovereign metadata:

```bash
curl -fsS http://127.0.0.1:8443/sovereign.json | python3 -m json.tool
genesis-mesh sovereign inspect --na http://127.0.0.1:8443
```

For a router-only VM that connects to an existing NA, enrol the node configs
first, then run:

```bash
sudo GENESIS_ROLE=router \
  GENESIS_REF=main \
  GENESIS_USER=ubuntu \
  NA_ENDPOINT=https://na.genesismesh.connectorzzz.com \
  ROUTER_B_CONFIG=/home/ubuntu/.genesis-mesh-demo-node/config.toml \
  ROUTER_B_PORT=7443 \
  bash infrastructure/scripts/bootstrap-ubuntu-vm.sh
```

For a combined NA plus router demo host, set `GENESIS_ROLE=all`.

The rest of this page documents the manual live Azure setup for the current
`na.genesismesh.connectorzzz.com` deployment.

## Prerequisites

- Ubuntu 22.04 VM provisioned (Terraform: `infrastructure/azure/`)
- Public IP reachable on ports 22, 80, 443, 7443, 7444
- DNS `na.genesismesh.connectorzzz.com` → VM public IP (Cloudflare or equivalent)
- Locally generated artifacts to upload:
  - `genesis.signed.json` (from `genesis-mesh init`)
  - `na.key` (NA private key, from `genesis-mesh init`)
  - `operator.pub` contents (for `OPERATOR_PUBLIC_KEYS_JSON`)

## 1. Python 3.12 and base tools

Ubuntu 22.04 ships Python 3.10 — the project needs 3.12.

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y \
  python3.12 python3.12-venv python3-pip \
  git curl sqlite3
```

## 2. Clone and install the package

```bash
sudo git clone https://github.com/GenesisMeshLabs/genesismesh.git /opt/genesis-mesh
sudo chown -R azureuser:azureuser /opt/genesis-mesh
cd /opt/genesis-mesh

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .

# Verify
genesis-mesh --help
```

## 3. Mount the secrets

Upload from local machine via `scp`:

```bash
# From local machine
scp .genesis-mesh/genesis.signed.json azureuser@<VM_IP>:/tmp/
scp .genesis-mesh/keys/na.key         azureuser@<VM_IP>:/tmp/
```

On the VM, move them into place with correct permissions:

```bash
sudo mkdir -p /etc/genesis /etc/genesis-mesh/keys /var/lib/genesis-mesh
sudo mv /tmp/genesis.signed.json /etc/genesis/genesis.signed.json
sudo mv /tmp/na.key               /etc/genesis-mesh/keys/na.key
sudo chmod 0644 /etc/genesis/genesis.signed.json
sudo chmod 0600 /etc/genesis-mesh/keys/na.key
sudo chown azureuser:azureuser /etc/genesis-mesh/keys/na.key /var/lib/genesis-mesh
```

## 4. Operator public keys

```bash
sudo mkdir -p /etc/genesis-mesh
sudo tee /etc/genesis-mesh/operator-keys.env > /dev/null <<'EOF'
OPERATOR_PUBLIC_KEYS_JSON={"operator-local":"<BASE64_OPERATOR_PUBLIC_KEY>"}
EOF
sudo chmod 0640 /etc/genesis-mesh/operator-keys.env
```

Replace `<BASE64_OPERATOR_PUBLIC_KEY>` with the contents of `.genesis-mesh/keys/operator.pub`.

## 5. systemd: Network Authority

Copy the canonical unit from this repo:

```bash
# On the VM
sudo cp infrastructure/systemd/genesis-mesh-na.service \
        /etc/systemd/system/genesis-mesh-na.service

sudo mkdir -p /etc/systemd/system/genesis-mesh-na.service.d/
sudo cp infrastructure/systemd/genesis-mesh-na.override.conf \
        /etc/systemd/system/genesis-mesh-na.service.d/override.conf

sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-na
sudo systemctl status genesis-mesh-na
```

Verify the NA is up locally:

```bash
curl http://127.0.0.1:8443/healthz
curl http://127.0.0.1:8443/readyz
```

## 6. Nginx + TLS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

sudo tee /etc/nginx/sites-available/genesis-mesh-na > /dev/null <<'EOF'
server {
    listen 80;
    server_name na.genesismesh.connectorzzz.com;

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/genesis-mesh-na \
            /etc/nginx/sites-enabled/genesis-mesh-na

sudo nginx -t && sudo systemctl reload nginx

# Provision Let's Encrypt cert (after DNS has propagated)
sudo certbot --nginx \
  -d na.genesismesh.connectorzzz.com \
  --non-interactive --agree-tos \
  -m rebel.saidi.thaer@gmail.com
```

Verify externally:

```bash
curl https://na.genesismesh.connectorzzz.com/healthz
```

## 7. Router nodes (B on 7443, D on 7444)

Both routers run as separate systemd units against the same NA.

```bash
# Get an invite token from your local machine first
INVITE_B=$(genesis-mesh admin invite --role anchor \
  --na https://na.genesismesh.connectorzzz.com)
INVITE_D=$(genesis-mesh admin invite --role anchor \
  --na https://na.genesismesh.connectorzzz.com)
```

On the VM, enrol each router once so each has its own config + cert:

```bash
source /opt/genesis-mesh/.venv/bin/activate

# Node B
genesis-mesh join \
  --na https://na.genesismesh.connectorzzz.com \
  --token "$INVITE_B" \
  --config ~/.genesis-mesh-demo-node/config.toml

# Node D
genesis-mesh join \
  --na https://na.genesismesh.connectorzzz.com \
  --token "$INVITE_D" \
  --config ~/.genesis-mesh-node-d/config.toml
```

Install both unit files:

```bash
sudo cp infrastructure/systemd/genesis-mesh-node.service   /etc/systemd/system/
sudo cp infrastructure/systemd/genesis-mesh-node-d.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-node genesis-mesh-node-d
```

## 8. Healthchecks.io probe

Cron entry that probes `/readyz` and pings Healthchecks.io on success:

```bash
sudo tee /etc/cron.d/genesis-mesh-readyz > /dev/null <<'EOF'
# Probe NA /readyz every 5 minutes; ping Healthchecks.io only on success.
# If /readyz fails or times out, the second curl never fires and HC alerts.
*/5 * * * * azureuser /usr/bin/curl -fsS --max-time 10 https://na.genesismesh.connectorzzz.com/readyz > /dev/null && /usr/bin/curl -fsS --retry 3 --max-time 10 https://hc-ping.com/<YOUR_HC_UUID> > /dev/null
EOF
```

Replace `<YOUR_HC_UUID>` with your Healthchecks.io check ping UUID.

## 9. Verification

```bash
# Services
sudo systemctl status genesis-mesh-na genesis-mesh-node genesis-mesh-node-d

# Crash recovery
sudo kill -9 $(systemctl show -p MainPID --value genesis-mesh-na)
sleep 6
sudo systemctl status genesis-mesh-na | head -5    # → active (running)

# Public endpoint
curl -fsS https://na.genesismesh.connectorzzz.com/healthz
curl -fsS https://na.genesismesh.connectorzzz.com/readyz
curl -fsS https://na.genesismesh.connectorzzz.com/nodes | python3 -m json.tool
```

## Where things live

| Path | What |
|---|---|
| `/opt/genesis-mesh` | Source checkout + venv |
| `/etc/genesis/genesis.signed.json` | Signed genesis block |
| `/etc/genesis-mesh/keys/na.key` | NA private key |
| `/etc/genesis-mesh/operator-keys.env` | Operator public keys for admin auth |
| `/var/lib/genesis-mesh/na.db` | SQLite database |
| `/etc/systemd/system/genesis-mesh-na.service` | NA service unit |
| `/etc/systemd/system/genesis-mesh-na.service.d/override.conf` | Operator-keys drop-in |
| `/etc/systemd/system/genesis-mesh-node*.service` | Router service units |
| `/etc/cron.d/genesis-mesh-readyz` | Healthchecks probe cron |
| `/etc/nginx/sites-available/genesis-mesh-na` | Reverse proxy config |
| `/etc/letsencrypt/live/na.genesismesh.connectorzzz.com/` | TLS certificate |
