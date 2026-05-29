# Configuration Reference

Genesis Mesh uses `genesis-mesh.toml` for local CLI workflows and environment
variables for container startup.

## CLI Config Discovery

The `genesis-mesh` command looks for config in this order:

1. `--config <path>`
2. `GENESIS_MESH_CONFIG`
3. `./genesis-mesh.toml`
4. `~/.genesis-mesh/config.toml`

`genesis-mesh init` writes a local config by default. `genesis-mesh join`
updates that config with node certificate and policy paths.

Example:

```toml
[network]
name = "USG"
version = "v0.1"
na_endpoint = "http://127.0.0.1:8443"

[paths]
home = ".genesis-mesh"
genesis = ".genesis-mesh/genesis.signed.json"
na_private_key = ".genesis-mesh/keys/na.key"
operator_private_key = ".genesis-mesh/keys/operator.key"
operator_public_key = ".genesis-mesh/keys/operator.pub"
node_private_key = ".genesis-mesh/keys/node.key"
node_certificate = ".genesis-mesh/node.cert.json"
policy = ".genesis-mesh/policy.json"

[na]
key_id = "na-local"
host = "127.0.0.1"
port = 8443

[operator]
key_id = "operator-local"
```

Private-key paths in this file are local secrets and must not be committed.

## Network Authority Environment

| Variable | Required | Description |
|---|---:|---|
| `SERVICE_ROLE` | no | Set to `na` for Network Authority startup. Defaults to `na`. |
| `GENESIS_FILE` | yes | Path to the signed genesis block. |
| `NA_PRIVATE_KEY_FILE` | yes | Path to the Network Authority private key. |
| `NA_KEY_ID` | no | Key identifier used when signing NA objects. |
| `DB_PATH` | no | SQLite database path. Defaults to `genesis_mesh_na.db`. |
| `PORT` | no | HTTP bind port. Defaults to `8443`. |
| `WEB_CONCURRENCY` | no | Gunicorn worker count. Defaults to `4`. |
| `OPERATOR_PUBLIC_KEYS_JSON` | yes for admin APIs | JSON object mapping operator key IDs to base64 public keys. |

`start.sh` refuses to start the Network Authority when `GENESIS_FILE` or
`NA_PRIVATE_KEY_FILE` is missing.

## Node Environment

| Variable | Required | Description |
|---|---:|---|
| `SERVICE_ROLE` | yes | Set to `node` for node startup. |
| `BOOTSTRAP_URL` | no | Network Authority endpoint. Defaults to `http://localhost:8443`. |
| `NODE_ROLE` | no | Requested node role. Defaults to `anchor`. |
| `PERSISTENT` | no | Set to `true` to run in persistent mode. |

For production node deployments, prefer explicit command arguments so the
genesis path, node key path, invite token, listen host, and listen port are clear
in deployment manifests.

## Files and Secrets

Private keys and databases should not be committed. The repository ignores:

- `genesis-mesh.toml`
- `.genesis-mesh/`
- `*.key`
- `*.pem`
- `keys/`
- `*.db`
- `*.db-shm`
- `*.db-wal`
- `*.sqlite`

Operator public keys are not private, but they are authorization data and should
be reviewed like any other security-sensitive configuration.
