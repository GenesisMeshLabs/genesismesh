# CLI Reference

Genesis Mesh exposes three command families:

- `python -m genesis_mesh.cli` for key and genesis operations.
- `python -m genesis_mesh.na_service` for local Network Authority development.
- `python -m genesis_mesh.node` for node enrollment and runtime startup.

## Key Generation

```bash
python -m genesis_mesh.cli keygen root --output keys/root --key-id rs-2025-q1
python -m genesis_mesh.cli keygen network-authority --output keys/na --key-id na-2025-q1
python -m genesis_mesh.cli keygen node --output keys/node --key-id node-1
```

Each command writes a private key file and a public key file. Private key files
are ignored by Git and must be protected.

## Genesis Commands

Create an unsigned genesis block:

```bash
python -m genesis_mesh.cli genesis create \
  --network-name "USG" \
  --network-version "v0.1" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --na-valid-days 90 \
  --anchor anchor-local:127.0.0.1:8443 \
  --output genesis.json
```

Sign it:

```bash
python -m genesis_mesh.cli genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json
```

Verify it:

```bash
python -m genesis_mesh.cli genesis verify --genesis genesis.signed.json
```

Inspect it:

```bash
python -m genesis_mesh.cli info --genesis genesis.signed.json
```

## Network Authority CLI

The Network Authority CLI validates configuration and app-factory construction.
Run the HTTP service through the WSGI app with Flask locally or Gunicorn in
Linux/container environments.

```bash
python -m genesis_mesh.na_service \
  --genesis genesis.signed.json \
  --na-private-key keys/na.key \
  --key-id na-2025-q1 \
  --operator-public-key operator-local=keys/operator.pub
```

`--operator-public-key` can be repeated. The value can be either a base64 public
key or a path to a public key file.

Local WSGI server:

```bash
export GENESIS_FILE=genesis.signed.json
export NA_PRIVATE_KEY_FILE=keys/na.key
export NA_KEY_ID=na-2025-q1
export OPERATOR_PUBLIC_KEYS_JSON="{\"operator-local\":\"$(grep -v '^#' keys/operator.pub | tr -d '\r\n')\"}"
python -m flask --app genesis_mesh.na_service.wsgi run --host 127.0.0.1 --port 8443
```

## Node CLI

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:anchor \
  --invite-token "$INVITE_TOKEN" \
  --listen-host 0.0.0.0 \
  --listen-port 0 \
  --persistent
```

Important options:

| Option | Description |
|---|---|
| `--genesis` | Path to signed genesis block. |
| `--bootstrap` | Network Authority endpoint. |
| `--role` | Requested local role. The NA assigns roles from the invite. |
| `--invite-token` | Single-use enrollment token. |
| `--node-key` | Existing node private key path. |
| `--validity-hours` | Requested certificate validity. |
| `--persistent` | Start heartbeats and the peer runtime after join. |
| `--listen-host` | Peer runtime bind host. |
| `--listen-port` | Peer runtime bind port; `0` requests an ephemeral port. |
