# Configuration Reference

Genesis Mesh uses `genesis-mesh.toml` for local CLI workflows and environment
variables for container startup.

## CLI Config Discovery

The `genesis-mesh` command looks for config in this order:

1. `--config <path>`
2. `GENESIS_MESH_CONFIG`
3. `./genesis-mesh.toml`
4. `~/.genesis-mesh/config.toml`

`genesis-mesh init` writes a local config by default. Without an explicit
`--home`, the config is `./genesis-mesh.toml`. With an explicit `--home` and no
`--config`, the config is written to `<home>/genesis-mesh.toml` so generated
keys, genesis material, and the pointer file stay together. `genesis-mesh join`
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
| `NA_PRIVATE_KEY_FILE` | with the `file` key provider | Path to the Network Authority private key. |
| `NA_KEY_PROVIDER` | no | `file` (default), `env` or `azure-keyvault`: where the signing key comes from (v0.60, see [High Availability](../operations/high-availability.md)). |
| `NA_PRIVATE_KEY_SEED` | with the `env` provider | Base64 Ed25519 seed injected by the platform's secret store. |
| `AZURE_KEY_VAULT_URL` / `NA_KEY_SECRET_NAME` | with the `azure-keyvault` provider | Vault URL and the secret holding the seed; read with the managed identity (`AZURE_CLIENT_ID` selects a user-assigned one). |
| `DATABASE_URL` | no | `postgresql://...` stores all state in shared PostgreSQL (v0.60); `sqlite:///path` names a SQLite file. Unset: SQLite at `DB_PATH`. |
| `NA_HA_MODE` | no | `off` (default) or `on`; `on` refuses to start without PostgreSQL, a non-file key provider and shared rate limits. |
| `RATE_LIMIT_STORE` | no | `memory` or `database`; defaults to `database` on PostgreSQL. |
| `NA_KEY_ID` | no | Key identifier used when signing NA objects. |
| `DB_PATH` | no | SQLite database path. Defaults to `genesis_mesh_na.db`. |
| `PORT` | no | HTTP bind port. Defaults to `8443`. |
| `WEB_CONCURRENCY` | no | Gunicorn worker count. Defaults to `4`. |
| `OPERATOR_PUBLIC_KEYS_JSON` | yes for admin APIs | JSON object mapping operator key IDs to base64 public keys. |
| `BOUNDARY_POLICY_ENFORCEMENT` | no | `optional` (default) or `required`; `required` refuses the legacy `/admin/boundary/decide` route. |
| `EVIDENCE_STORE` | no | `off` (default) or `on`; `on` keeps an append-only record of decisions and execution evidence (v0.59). |
| `OPERATOR_KEY_TIERS_JSON` | yes for admin APIs | JSON object mapping each operator key ID to `standard` or `privileged`. **Required for every configured key — the service refuses to start otherwise.** |

`start.sh` refuses to start the Network Authority when `GENESIS_FILE` is
missing, or when `NA_PRIVATE_KEY_FILE` is missing with the `file` key provider.

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
