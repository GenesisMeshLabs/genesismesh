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
| `--genesis-file` | Signed genesis output path. Useful for `/etc/genesis/genesis.signed.json`. |
| `--na-private-key-file` | Network Authority private key output path. |
| `--operator-private-key-file` | Operator private key output path. |
| `--operator-public-key-file` | Operator public key output path. |
| `--db-path` | Network Authority SQLite DB path to store in config. |
| `--na-host` | Network Authority bind host to store in config. |
| `--na-port` | Network Authority bind port to store in config. |
| `--anchor` | Optional peer bootstrap anchor in `id:endpoint` format. Do not use the NA HTTP endpoint. |
| `--force` | Replace an existing config and generated local artifacts. |

`init` is suitable for local development and demos. Production key generation
should happen through an explicit key-management ceremony.

For a named sovereign on a VM, keep the paths explicit:

```bash
genesis-mesh init \
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
```

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
`genesis-mesh init`; `dev down` removes `genesis-mesh.toml`, `.genesis-mesh/`,
and local `.node*/` smoke-test directories.

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

### `genesis-mesh sovereign inspect`

Fetches operator-safe public metadata from a Network Authority.

```bash
genesis-mesh sovereign inspect --na https://na.genesismesh.connectorzzz.com
genesis-mesh sovereign inspect --na http://164.92.250.135:8443 --format json
```

The command reads `/sovereign.json`, not private files. It prints the network
name, endpoint, NA public key prefix, validity window, and public trust
surfaces useful for recognition.

### `genesis-mesh proof remote`

Runs the direct-recognition proof against two live Network Authority endpoints:
issue attestation, issue treaty, verify acceptance, revoke attestation, import
revocation feed, verify rejection, and optionally write a redacted proof bundle.

```bash
genesis-mesh proof remote \
  --acceptor https://na.genesismesh.connectorzzz.com \
  --issuer http://164.92.250.135:8443 \
  --acceptor-config ./sovereign-a.toml \
  --issuer-config ./sovereign-b.toml \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

Use `--operator-key` when both endpoints trust the same operator key. Use the
endpoint-specific `--acceptor-operator-key` and `--issuer-operator-key` options
when each sovereign has its own operator key.

For adoption evidence, add `--adoption-proof` and operator-control metadata:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --issuer-config ./issuer.toml \
  --proof-bundle ./external-operator-proof.json \
  --adoption-proof \
  --acceptor-operator-label "Genesis Core" \
  --acceptor-operator-type maintainer \
  --issuer-operator-label "Example Maintainer" \
  --issuer-operator-type external \
  --issuer-controls-keys \
  --issuer-controls-infrastructure \
  --operator-assistance-note "Maintainer observed but did not handle issuer private keys."
```

In adoption-proof mode, the CLI refuses to write a passing proof unless the
issuer is marked external and confirms control of keys and infrastructure.

### `genesis-mesh proof cleanup`

Backs up a Network Authority SQLite database and removes only proof artifacts:
membership attestations, recognition treaties, sovereign revocation feeds, and
imported sovereign revocations.

```bash
genesis-mesh proof cleanup \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup-dir /var/lib/genesis-mesh \
  --yes
```

The command uses Python's SQLite library, so minimal Ubuntu VMs do not need the
`sqlite3` command-line tool.

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

### `genesis-mesh discover`

Lists agents registered in the Network Authority's service registry (v0.7+).
Supports filtering by capability tag and a JSON output mode for scripting.

```bash
# Find every agent advertising llm:chat
genesis-mesh discover --capability llm:chat

# Use a different NA than the one in config
genesis-mesh discover --capability llm:chat --na https://na.example.com

# JSON output for scripts
genesis-mesh discover --capability llm:chat --format json
```

Sample output:

```text
1 agent(s) matching capability=llm:chat:

  agent_id     : llm-1
  node_key     : EGk5lruaR7fveWfEyQsIuo7S2oevUOtKyrHR5sKKXqA=
  capabilities : llm:chat, llm:openai/gpt-4o-mini
  endpoint     : ws://127.0.0.1:7448
  expires_at   : 2026-06-01T14:12:03.713487Z
  metadata     : {'model': 'openai/gpt-4o-mini'}
```

Agents register themselves at startup using the helpers in
`genesis_mesh.node.discovery_client`. The bundled
`examples/agent-network/knowledge_base.py` and `llm_agent.py` auto-register
with sensible default capability tags; override or extend with their
`--capability` and `--announce-host` flags.

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

Removes local artifacts created by `genesis-mesh init` and smoke-test node
directories in the current working directory:

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
