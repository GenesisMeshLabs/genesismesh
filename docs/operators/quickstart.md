# Operator Quickstart

This page is the shortest supported path for standing up a named sovereign
Network Authority on a plain Ubuntu VM.

It assumes the VM already exists, Python and the Genesis Mesh package are
installed, and the operator wants one sovereign with its own genesis, Network
Authority key, operator key, and SQLite database.

This path keeps every key on one VM while you set it up. Before other
sovereigns rely on yours, work through the
{doc}`production-checklist`: it moves the root key offline, turns on the
evidence store and checks the host.

```{figure} ../examples/assets/images/genesis-mesh-operator-quickstart.gif
:alt: A terminal run of genesis-mesh init with --env-file, na doctor failing on the root key, the root key moved offline, na doctor passing, then na start and sovereign inspect.

A recorded run on a local machine, with every file in one directory instead
of `/etc` and `/var/lib`: `init --env-file`, `na doctor` before and after the
root key leaves the host, `na start --env-file` and `sovereign inspect`. The
transcript is `docs/examples/assets/images/genesis-mesh-operator-quickstart.txt`,
recorded by `docs/examples/assets/scripts/operator-quickstart-demo.py`.
```

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
  --na-endpoint https://na.example.org \
  --genesis-file /etc/genesis/genesis.signed.json \
  --na-private-key-file /etc/genesis-mesh/keys/na.key \
  --operator-private-key-file /etc/genesis-mesh/keys/operator.key \
  --operator-public-key-file /etc/genesis-mesh/operator.pub \
  --db-path /var/lib/genesis-mesh/na.db \
  --na-host 0.0.0.0 \
  --na-port 8443 \
  --env-file /etc/genesis-mesh/na.env \
  --force

chmod 0644 /etc/genesis/genesis.signed.json
chmod 0600 /etc/genesis-mesh/keys/na.key /etc/genesis-mesh/keys/operator.key
```

Production-style path options require an explicit `--network-name`; the CLI
refuses to initialize those paths with the default name by accident. Use the
address other sovereigns will reach for `--na-endpoint`.

`--env-file` also writes the NA's settings to `/etc/genesis-mesh/na.env`: the
genesis block, the NA key file, `NA_KEY_ID=na-local`, the database, the port,
the operator key with the `privileged` tier, `BOUNDARY_POLICY_ENFORCEMENT=required`,
`EVIDENCE_STORE=on` and `NA_PROXY_HOPS=0`. Its paths are relative to the
file, so it serves `genesis-mesh na start --env-file` and
`genesis-mesh na doctor --env-file`; the systemd unit below keeps its own
settings.

### Move the root key off the VM

`init` also writes the root private key to
`/tmp/genesis-mesh-nb/keys/root.key`, and warns about it. The root key signs
NA key successions: without it you can never replace the NA key while keeping
the sovereign's identity. `/tmp` is cleared on reboot, so copy the key now to
offline storage you control, then delete it from the VM:

```bash
# copy /tmp/genesis-mesh-nb/keys/root.key to offline media first
shred -u /tmp/genesis-mesh-nb/keys/root.key
```

See the root key ceremony in {doc}`../operations/key-succession`. For a
sovereign other parties rely on, generate the root key offline in the first
place.

## 2. Configure the Network Authority Service

The systemd unit the bootstrap script writes sets the genesis block, the NA
key file, the database, the port and `NA_PROXY_HOPS`, and reads
`/etc/genesis-mesh/operator-keys.env`. The Network Authority accepts admin
writes only from configured operator public keys, so put the operator key in
that file, with the settings the unit otherwise leaves at their defaults:

```bash
PUB=$(grep -v '^#' /etc/genesis-mesh/operator.pub | tr -d '\r\n')
{
  printf 'OPERATOR_PUBLIC_KEYS_JSON={"operator-local":"%s"}\n' "$PUB"
  printf 'OPERATOR_KEY_TIERS_JSON={"operator-local":"privileged"}\n'
  printf 'NA_KEY_ID=na-local\n'
  printf 'BOUNDARY_POLICY_ENFORCEMENT=required\n'
  printf 'EVIDENCE_STORE=on\n'
} | sudo tee /etc/genesis-mesh/operator-keys.env > /dev/null
sudo chmod 0640 /etc/genesis-mesh/operator-keys.env
```

Without the last three lines the NA signs under the default key ID
`na-2025-q1` (while `init` named the key `na-local`), keeps the legacy
`/admin/boundary/decide` route open, and records no evidence. Each
is a default, not an error. Behind a reverse proxy, also set `NA_PROXY_HOPS`
to the number of proxies and `NA_PUBLIC_URL` to the public address (see
{doc}`../reference/configuration`). The unit runs four Gunicorn workers, and
on SQLite each counts the rate limits on its own.

Add more operator keys with the lowest tier their work needs, for example
`genesis-mesh keygen operator --output <path> --key-id <id> --tier standard`,
and add each to both JSON objects.

Do not copy `/etc/genesis-mesh/keys/operator.key` to another sovereign unless
the same human operator is intentionally trusted by both authorities.

## 3. Start the Network Authority

If the provider-neutral bootstrap script installed the systemd unit, start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-na
sudo systemctl status genesis-mesh-na --no-pager --lines=30
```

For local development only, the settings file `init` wrote can run through
the development server (on `127.0.0.1`):

```bash
genesis-mesh na start --env-file /etc/genesis-mesh/na.env
```

Use Gunicorn and systemd for VM operation. To run the Network Authority as a
container instead, use the signed image with the same genesis block and keys:
see [Container Images](../operations/container-images.md).

## 4. Verify Public Metadata

Health checks prove the service is alive. Sovereign metadata proves another
operator can discover the public trust material needed for recognition.

```bash
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS http://127.0.0.1:8443/readyz
curl -fsS http://127.0.0.1:8443/sovereign.json | python3 -m json.tool
genesis-mesh sovereign inspect --na http://127.0.0.1:8443
genesis-mesh na doctor --env-file /etc/genesis-mesh/na.env
```

The metadata response must not contain private keys, operator private material,
database paths, or local filesystem paths. `/readyz` is different: it is public
and names the database path (`db_path`), so filter it at a proxy if that
matters to you.

`na doctor` checks the host against the settings file: no root private key
where the NA's files live, the NA key valid now, archives required before
retention. It searches only near the NA's files (the genesis, key and database
directories), so it does not see a copy in `/tmp`; delete that yourself.

## 5. Run the Two-Sovereign Proof

From a machine with operator credentials for both Network Authorities:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./sovereign-a.toml \
  --issuer-config ./sovereign-b.toml \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

For a first run where both authorities trust the same operator key:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
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

Stop the NA before editing its database. The cleanup command backs up the
SQLite file, then deletes **every** row in four tables: recognition treaties,
membership attestations, revocation feeds and imported revocations. That
includes treaties and attestations the proof did not create, so use it only
on a sovereign that holds nothing but proof state. It does not support
PostgreSQL.

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
- Do not keep `root.key` on the VM at all (see step 1).
- Do not share the SQLite database unless it is part of an intentional backup
  or incident handoff.
- Do share `/sovereign.json`, `/genesis`, and `/sovereign-revocation-feed`.

Sovereignty means the operator owns the genesis identity, Network Authority
signing key, policy, database, and revocation decisions.

For a full checklist, see the
[Operator Security Checklist](security-checklist.md).
