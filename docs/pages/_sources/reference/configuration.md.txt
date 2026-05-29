# Configuration Reference

Genesis Mesh uses command-line arguments for local development and environment
variables for container startup.

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

- `*.key`
- `*.pem`
- `keys/`
- `*.db`
- `*.sqlite`

Operator public keys are not private, but they are authorization data and should
be reviewed like any other security-sensitive configuration.
