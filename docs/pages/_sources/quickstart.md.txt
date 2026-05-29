# Genesis Mesh - Quick Start Guide

This guide creates a local Genesis Mesh development network. Production
deployments should use mounted secrets, the container entry point, and the
infrastructure guidance in [](operations/infrastructure.md).

```{mermaid}
flowchart TD
    keys["Generate root, NA, and operator keys"]
    genesis["Create and sign genesis block"]
    na["Start Network Authority"]
    invite["Create invite token"]
    node["Start node with invite"]
    smoke["Run smoke workflow"]

    keys --> genesis
    genesis --> na
    na --> invite
    invite --> node
    node --> smoke
```

## Prerequisites

Install dependencies:

```bash
pip install -r requirements.txt
```

## 1. Generate Authority Keys

The Root Sovereign key is the offline constitutional authority. Keep it offline
and secure.

```bash
python -m genesis_mesh.cli keygen root \
  --output keys/root \
  --key-id rs-2025-q1
```

The Network Authority key signs certificates, CRLs, and policies.

```bash
python -m genesis_mesh.cli keygen network-authority \
  --output keys/na \
  --key-id na-2025-q1
```

Generate a separate operator key for admin API calls:

```bash
python -m genesis_mesh.cli keygen node \
  --output keys/operator \
  --key-id operator-local
```

## 2. Create and Sign a Genesis Block

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

Sign the genesis block with the offline root key:

```bash
python -m genesis_mesh.cli genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json
```

Verify the signed genesis block:

```bash
python -m genesis_mesh.cli genesis verify \
  --genesis genesis.signed.json
```

## 3. Start the Network Authority

Validate the Network Authority configuration:

```bash
python -m genesis_mesh.na_service \
  --genesis genesis.signed.json \
  --na-private-key keys/na.key \
  --key-id na-2025-q1 \
  --operator-public-key operator-local=keys/operator.pub
```

Run the local development server through the WSGI app:

```bash
export GENESIS_FILE=genesis.signed.json
export NA_PRIVATE_KEY_FILE=keys/na.key
export NA_KEY_ID=na-2025-q1
export OPERATOR_PUBLIC_KEYS_JSON="{\"operator-local\":\"$(grep -v '^#' keys/operator.pub | tr -d '\r\n')\"}"
python -m flask --app genesis_mesh.na_service.wsgi run --host 127.0.0.1 --port 8443
```

For container or production-style startup, use `start.sh` with `GENESIS_FILE`
and `NA_PRIVATE_KEY_FILE` pointing at mounted secret files. The script runs
Gunicorn and defaults to port `8443`. Pass operator public keys to the WSGI app
with `OPERATOR_PUBLIC_KEYS_JSON`, for example
`{"operator-local":"<base64-public-key>"}`.

The Network Authority exposes:

- `GET /healthz` for liveness.
- `GET /readyz` for readiness.
- `GET /genesis` for the active genesis block.
- `GET /policy` for the active policy manifest.
- `GET /crl` for the active signed CRL.
- `POST /admin/invite` for operator-authenticated invite creation.
- `POST /join` for invite-token-backed certificate issuance.

## 4. Create an Invite Token

Node enrollment requires a single-use invite token. Admin requests are signed by
an operator key, not by the NA private key. Until a dedicated operator CLI is
added, use the admin API signing pattern shown in `examples/test_workflow.py`.

The invite controls the node roles and maximum certificate validity. The NA
ignores client-supplied roles during `/join` and assigns roles from the invite.

## 5. Start a Node

Start an anchor node with the invite token:

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:anchor \
  --validity-hours 168 \
  --invite-token "$INVITE_TOKEN" \
  --persistent
```

Start a client node with a separate invite token:

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:client \
  --validity-hours 24 \
  --invite-token "$CLIENT_INVITE_TOKEN" \
  --persistent
```

The node verifies the genesis block, requests a join certificate with its invite,
fetches policy, and starts the persistent runtime when `--persistent` is set.

## 6. Test the Workflow

Run the Python smoke workflow:

```bash
python examples/test_workflow.py
```

The shell quickstart creates keys and signed genesis artifacts:

```bash
bash examples/quickstart.sh
```

## Roles

- `role:anchor`: Gateway or relay node.
- `role:bridge`: Edge resiliency node.
- `role:client`: Endpoint node.
- `role:operator`: Policy or administrative operator.
- `role:service:<name>`: Service-specific identity.

## Security Notes

- Keep Root Sovereign private keys offline.
- Keep NA private keys inside the NA process, a secret manager, or an HSM.
- Use separate operator keys for admin API calls.
- Treat invite tokens as secrets; they are single-use enrollment credentials.
- Keep system time synchronized because certificates and admin signatures are
  time-bound.

## Troubleshooting

### Genesis block signature verification fails

- Confirm `keys/root.pub` matches the private key used for signing.
- Confirm the genesis block was not edited after signing.
- Re-run `python -m genesis_mesh.cli genesis verify`.

### Node cannot join

- Confirm the NA is reachable at the `--bootstrap` URL.
- Confirm the invite token exists, is unused, and has not expired.
- Confirm the invite allows the requested certificate validity.
- Check NA logs for `/join` errors.

### Certificate validation fails

- Confirm the NA public key in genesis matches the running NA private key.
- Confirm system clocks are synchronized.
- Confirm the certificate has not expired or been revoked.
