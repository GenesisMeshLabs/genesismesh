# Node and Developer Commands

Commands that enroll a node, inspect and use the mesh, and run the local
smoke workflow.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

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
| `--na` | Network Authority endpoint (required). |
| `--token` | Single-use invite token. Required only when no valid local certificate exists. |
| `--role` | Requested local role. The NA still assigns roles from the invite. |
| `--validity-hours` | Requested certificate validity. |
| `--persistent` | Start the peer runtime after enrollment. |
| `--listen-host` | Peer runtime bind host. |
| `--listen-port` | Peer runtime bind port; `0` requests an ephemeral port. |
| `--peer` | Bootstrap peer endpoint (`host:port` or `ws://host:port`). Repeatable. |

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

*Beta.*

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

### `genesis-mesh send`

*Beta.*

Sends a message to another node through a peer WebSocket endpoint, using this
node's identity from its config. Both nodes must be running their peer runtime
(`genesis-mesh join --persistent`):

```bash
genesis-mesh send   --to <recipient-node-public-key>   --via ws://127.0.0.1:19001   --message "hello"   --config ./node-a/genesis-mesh.toml
```

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

*Beta.*

Removes local artifacts created by `genesis-mesh init` and smoke-test node
directories in the current working directory:

```bash
genesis-mesh dev down
```

Stop `genesis-mesh na start` and persistent node runtimes first. On Windows,
SQLite database files remain locked while the Network Authority process is
running, and `dev down` will report that cleanly instead of removing a live DB.
