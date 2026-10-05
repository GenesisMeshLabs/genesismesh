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
| `GENESIS_FILE` | yes | Path to the signed genesis block. `start.sh` defaults it to `genesis.signed.json` in the working directory. |
| `GENESIS_JSON` | no | `start.sh`: the signed genesis block itself, used when `GENESIS_FILE` does not exist. It is written to a private temporary directory. |
| `NA_PRIVATE_KEY_FILE` | with the `file` key provider | Path to the Network Authority private key. `start.sh` defaults it to `keys/na.key` in the working directory. |
| `NA_PRIVATE_KEY` | no | `start.sh`: the private key file's contents, used when `NA_PRIVATE_KEY_FILE` does not exist. Handled like `GENESIS_JSON`. Prefer a mounted file or the `env` provider with `NA_PRIVATE_KEY_SEED_FILE`. |
| `NA_KEY_PROVIDER` | no | `file` (default), `env` or `azure-keyvault`: where the signing key comes from (v0.60, see [High Availability](../operations/high-availability.md)). |
| `NA_PRIVATE_KEY_SEED` | with the `env` provider | Base64 Ed25519 seed injected by the platform's secret store. |
| `NA_PRIVATE_KEY_SEED_FILE` | with the `env` provider | Path to a file holding the base64 seed, for Docker and Kubernetes secrets. Set this or `NA_PRIVATE_KEY_SEED`, not both (v1.0.2). |
| `NA_KEY_SEED_ENV` | no | Name of the variable that holds the seed for the `env` provider (default `NA_PRIVATE_KEY_SEED`); the file variant is that name with `_FILE` appended. |
| `AZURE_KEY_VAULT_URL` / `NA_KEY_SECRET_NAME` | with the `azure-keyvault` provider | Vault URL and the secret holding the seed; read with the managed identity (`AZURE_CLIENT_ID` selects a user-assigned one). |
| `DATABASE_URL` | no | `postgresql://...` stores all state in shared PostgreSQL (v0.60); `sqlite:///path` names a SQLite file. Unset: SQLite at `DB_PATH`. |
| `NA_HA_MODE` | no | `off` (default) or `on`; `on` refuses to start without PostgreSQL, a non-file key provider and shared rate limits. |
| `RATE_LIMIT_STORE` | no | `memory` or `database`; defaults to `database` on PostgreSQL. |
| `NA_KEY_ID` | no | Key ID named in the NA's signatures. Defaults to `na-2025-q1`; set it to the ID recorded in the NA key file (`na-local` for keys from `genesis-mesh init`) and keep it stable, since trust bundles and gateway policies refer to it. |
| `DB_PATH` | no | SQLite database path. Defaults to `genesis_mesh_na.db`. |
| `PORT` | no | HTTP bind port. Defaults to `8443`. |
| `WEB_CONCURRENCY` | no | Gunicorn worker count. Defaults to `4`. |
| `OPERATOR_PUBLIC_KEYS_JSON` | yes for admin APIs | JSON object mapping operator key IDs to base64 public keys. |
| `BOUNDARY_POLICY_ENFORCEMENT` | no | `optional` (default) or `required`; `required` refuses the legacy `/admin/boundary/decide` route. |
| `EVIDENCE_STORE` | no | `off` (default) or `on`; `on` keeps an append-only record of decisions and execution evidence (v0.59). |
| `NA_MAX_REQUEST_BYTES` | no | Largest accepted request body in bytes (default 2097152, 2 MiB); larger requests get `413 request_entity_too_large` before they are parsed (v0.62). |
| `NA_RATE_LIMIT_ADMIN_PER_MINUTE` | no | Signed admin requests per minute per client address (default 30). Every governed action calls `/admin/boundary/evaluate`, so size this to the controllers behind one address (v0.63.1). |
| `NA_RATE_LIMIT_VERIFY_PER_MINUTE` | no | Public verification and proof requests per minute per client address (default 60). |
| `NA_RATE_LIMIT_EVIDENCE_PER_MINUTE` | no | Execution evidence submissions per minute per client address (default 120). |
| `NA_RATE_LIMIT_READ_PER_MINUTE` | no | Public policy reads per minute per client address (default 120). Enrollment (`/join`) limits are fixed anti-abuse controls. |
| `NA_PROXY_HOPS` | no | Number of reverse proxies in front of the NA whose `X-Forwarded-For` is trusted (default `1`). Set `0` when the NA is reached directly, so clients cannot choose the address rate limits apply to (v0.62). |
| `NA_ADMIN_LEGACY_SIGNATURES` | no | `reject` (default) refuses version 1 admin signatures, which do not cover the method, path, query or target NA. `accept` allows them during a client migration window and audits each use (`admin_legacy_signature_accepted`). Unset it once every client is on v1.0.2 or later (v1.0.2). |
| `OPERATOR_KEY_TIERS_JSON` | yes for admin APIs | JSON object mapping each operator key ID to `read`, `standard` or `privileged`. **Required for every configured key — the service refuses to start otherwise.** |

`start.sh` refuses to start the Network Authority when `GENESIS_FILE` is
missing, or when `NA_PRIVATE_KEY_FILE` is missing with the `file` key provider.
The Network Authority then refuses to start when the signing key does not
match the genesis block.

These variables configure the production entry point (`start.sh`, or Gunicorn
with `genesis_mesh.na_service.wsgi:app`). The local development server,
`genesis-mesh na start`, reads none of them: it takes the genesis block, the
keys, the database path and its one operator key (privileged tier) from the
config file, the evidence store setting from `--evidence-store` or the config,
and uses the defaults for everything else, including the rate limits and
`NA_ADMIN_LEGACY_SIGNATURES=reject`. Use the production entry point to run
with other settings.

## Node Environment

| Variable | Required | Description |
|---|---:|---|
| `SERVICE_ROLE` | yes | Set to `node` for node startup. |
| `GENESIS_FILE` | yes | Path to the signed genesis block. |
| `INVITE_TOKEN` | yes | Single-use enrollment token from the network's operator. |
| `BOOTSTRAP_URL` | no | Network Authority endpoint. Defaults to `http://localhost:8443`. |
| `NODE_ROLE` | no | Requested node role. Defaults to `anchor`. |
| `NODE_KEY_FILE` | no | Path to an existing node private key. Unset: the node generates a new key at every start. |
| `LISTEN_HOST` / `LISTEN_PORT` | no | Peer listener address. Default `0.0.0.0` and `0` (any free port). |
| `PERSISTENT` | no | Defaults to `true`: after enrolling, the node keeps running its peer runtime with heartbeats until stopped. `false` enrolls, prints its status and exits. |

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
