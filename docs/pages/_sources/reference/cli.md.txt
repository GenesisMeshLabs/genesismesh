# CLI Reference

Genesis Mesh installs a single primary command:

```bash
genesis-mesh --help
```

The command is intentionally persona-oriented instead of file-oriented. Operator
commands manage the Network Authority and admin actions, node commands join and
inspect the mesh, and developer commands run local verification workflows.

Compatibility entry points such as `python -m genesis_mesh.cli` and
`python -m genesis_mesh.node` still exist for direct module execution, but
documentation and day-to-day workflows should prefer `genesis-mesh`.

## Operator Commands

### `genesis-mesh init`

Creates local demo keys, an unsigned genesis file, a signed genesis file, and a
CLI config file.

```bash
genesis-mesh init
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to write. Defaults to `genesis-mesh.toml`. |
| `--home` | Directory for generated local artifacts. Defaults to `.genesis-mesh`. |
| `--network-name` | Network name embedded in genesis. |
| `--network-version` | Network version embedded in genesis. |
| `--na-endpoint` | Network Authority endpoint written to config. |
| `--anchor` | Optional peer bootstrap anchor in `id:endpoint` format. Do not use the NA HTTP endpoint. |
| `--force` | Replace an existing config and generated local artifacts. |

`init` is suitable for local development and demos. Production key generation
should happen through an explicit key-management ceremony.

### `genesis-mesh na start`

Starts a local Network Authority from config.

```bash
genesis-mesh na start
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read. |
| `--host` | Override configured bind host. |
| `--port` | Override configured bind port. |
| `--db-path` | Override SQLite database path. |

This command uses Flask's local server and is intended for development. Use the
container entry point and Gunicorn for production-style deployments.

If `genesis-mesh dev down` was run earlier, recreate local config first with
`genesis-mesh init`; `dev down` removes `genesis-mesh.toml` and `.genesis-mesh/`.

### `genesis-mesh admin invite`

Creates a single-use invite token through the operator-authenticated admin API.

```bash
genesis-mesh admin invite --role anchor
```

The command prints only the token ID, so shells can capture it:

```bash
INVITE_TOKEN=$(genesis-mesh admin invite --role anchor)
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read. |
| `--na` | Network Authority endpoint override. |
| `--role` | Role to assign. Can be repeated. |
| `--validity-hours` | Maximum certificate validity allowed by the invite. |
| `--token-expiry-hours` | Invite token lifetime. |

### `genesis-mesh admin revoke`

Revokes a certificate through the operator-authenticated admin API.

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise
```

Useful reasons are `key_compromise`, `cessation_of_operation`, `superseded`,
and `unspecified`.

## Node Operator Commands

### `genesis-mesh join`

Enrolls this machine as a node and persists local node config.

```bash
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN"
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read and update. |
| `--na` | Network Authority endpoint. |
| `--token` | Single-use invite token. Required only when no valid local certificate exists. |
| `--role` | Requested local role. The NA still assigns roles from the invite. |
| `--validity-hours` | Requested certificate validity. |
| `--persistent` | Start the peer runtime after enrollment. |
| `--listen-host` | Peer runtime bind host. |
| `--listen-port` | Peer runtime bind port; `0` requests an ephemeral port. |

`join` fetches the genesis block if needed, generates or reuses the local node
key, requests a join certificate, fetches policy, saves the certificate and
policy, and updates the CLI config. If a valid local certificate already exists,
`join` reuses it instead of spending another invite token. This lets
`genesis-mesh join --na <url> --persistent` start the runtime after a previous
enrollment.

### `genesis-mesh status`

Shows Network Authority health and local node certificate status from config.

```bash
genesis-mesh status
```

`status` is shared by operators and node operators. It detects available config
and prints the relevant Network Authority and node view.

## Developer Commands

### `genesis-mesh dev up`

Runs the local in-process smoke workflow:

```bash
genesis-mesh dev up
```

The smoke workflow starts a local Network Authority in process, creates
operator-authenticated invite tokens, enrolls nodes, fetches policy, and
validates node status.

### `genesis-mesh dev down`

Removes local artifacts created by `genesis-mesh init` in the current working
directory:

```bash
genesis-mesh dev down
```

Stop `genesis-mesh na start` and persistent node runtimes first. On Windows,
SQLite database files remain locked while the Network Authority process is
running, and `dev down` will report that cleanly instead of removing a live DB.

## Low-Level Compatibility Commands

The low-level key and genesis subcommands remain available:

```bash
genesis-mesh keygen root --output keys/root --key-id rs-2025-q1
genesis-mesh keygen network-authority --output keys/na --key-id na-2025-q1
genesis-mesh keygen node --output keys/node --key-id node-1

genesis-mesh genesis create \
  --network-name "USG" \
  --network-version "v0.1" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --na-valid-days 90 \
  --output genesis.json

genesis-mesh genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json

genesis-mesh genesis verify --genesis genesis.signed.json
genesis-mesh info --genesis genesis.signed.json
```
