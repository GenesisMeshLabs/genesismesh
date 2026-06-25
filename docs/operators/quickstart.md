# Operator Quickstart

This page is the shortest supported path for standing up a named sovereign
Network Authority on a plain Ubuntu VM.

It assumes the VM already exists, Python and the Genesis Mesh package are
installed, and the operator wants one sovereign with its own genesis, Network
Authority key, operator key, and SQLite database.

## 1. Initialize a Named Sovereign

Choose a network name that identifies this sovereign. Do not reuse the default
`USG` unless this VM is intentionally the same sovereign as an existing `USG`
deployment.

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

Production-style path options require an explicit `--network-name`; the CLI
refuses to initialize those paths with the default name by accident.

## 2. Configure Operator Public Keys

The Network Authority accepts admin writes only from configured operator public
keys. Put the public key in the systemd environment file:

```bash
PUB=$(grep -v '^#' /etc/genesis-mesh/operator.pub | tr -d '\r\n')
printf 'OPERATOR_PUBLIC_KEYS_JSON={"operator-local":"%s"}\n' "$PUB" \
  | sudo tee /etc/genesis-mesh/operator-keys.env > /dev/null
sudo chmod 0640 /etc/genesis-mesh/operator-keys.env
```

Do not copy `/etc/genesis-mesh/keys/operator.key` to another sovereign unless
the same human operator is intentionally trusted by both authorities.

## 3. Start the Network Authority

If the provider-neutral bootstrap script installed the systemd unit, start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-na
sudo systemctl status genesis-mesh-na --no-pager --lines=30
```

For local development only, the same config can run through Flask:

```bash
genesis-mesh na start --config genesis-mesh.toml
```

Use Gunicorn and systemd for VM operation.

## 4. Verify Public Metadata

Health checks prove the service is alive. Sovereign metadata proves another
operator can discover the public trust material needed for recognition.

```bash
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS http://127.0.0.1:8443/readyz
curl -fsS http://127.0.0.1:8443/sovereign.json | python3 -m json.tool
genesis-mesh sovereign inspect --na http://127.0.0.1:8443
```

The metadata response must not contain private keys, operator private material,
database paths, or local filesystem paths.

## 5. Run the Two-Sovereign Proof

From a machine with operator credentials for both Network Authorities:

```bash
genesis-mesh proof remote \
  --acceptor https://na.genesismesh.connectorzzz.com \
  --issuer http://164.92.250.135:8443 \
  --acceptor-config ./sovereign-a.toml \
  --issuer-config ./sovereign-b.toml \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

For a first run where both authorities trust the same operator key:

```bash
genesis-mesh proof remote \
  --acceptor https://na.genesismesh.connectorzzz.com \
  --issuer http://164.92.250.135:8443 \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

The proof command creates live proof artifacts: one membership attestation, one
recognition treaty, one issuer revocation, and one imported revocation feed.

For external adoption evidence, use the
[Recognition Playbook](recognition-playbook.md) and include `--adoption-proof`
operator-control metadata in the proof bundle.

## 6. Clean Proof Artifacts

Stop the NA before editing its database. The cleanup command creates a backup
and deletes only proof tables.

```bash
sudo systemctl stop genesis-mesh-na
genesis-mesh proof cleanup \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup-dir /var/lib/genesis-mesh \
  --yes
sudo systemctl start genesis-mesh-na
```

Expected clean Connectome:

```bash
curl -fsS http://127.0.0.1:8443/connectome.json
```

The summary should show zero sovereigns, zero recognition edges, and zero
imported revocations.

## What Not To Share

- Do not share `na.key`.
- Do not share `operator.key`.
- Do not share the SQLite database unless it is part of an intentional backup
  or incident handoff.
- Do share `/sovereign.json`, `/genesis`, and `/sovereign-revocation-feed`.

Sovereignty means the operator owns the genesis identity, Network Authority
signing key, policy, database, and revocation decisions.

For a full checklist, see the
[Operator Security Checklist](security-checklist.md).
