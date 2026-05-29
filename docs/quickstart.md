# Quick Start

This guide creates a local Genesis Mesh development network through the
high-level `genesis-mesh` command. The command is organized around the three
people who operate the system: an operator who runs the Network Authority, a
node operator who joins the mesh, and a developer who wants a local smoke test.

```{mermaid}
flowchart TD
    init["genesis-mesh init"]
    na["genesis-mesh na start"]
    invite["genesis-mesh admin invite"]
    join["genesis-mesh join"]
    status["genesis-mesh status"]
    dev["genesis-mesh dev up"]

    init --> na
    na --> invite
    invite --> join
    join --> status
    init --> dev
```

![Genesis Mesh enrollment demo](../examples/assets/genesis-mesh-enrollment.gif)

## Prerequisites

Install the package in editable mode so the `genesis-mesh` console command is
available:

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

On Windows Git Bash, user-level Python installs commonly put console scripts
under `%APPDATA%\Python\Python314\Scripts`, which Git Bash may not have on
`PATH`. Prefer using the project virtual environment:

```bash
source .venv/Scripts/activate
python -m pip install -e .
genesis-mesh --help
```

Or add the user script directory to the current Git Bash session:

```bash
export PATH="$HOME/AppData/Roaming/Python/Python314/Scripts:$PATH"
genesis-mesh --help
```

## Operator Workflow

Initialize local keys, a signed genesis block, and `genesis-mesh.toml`:

```bash
genesis-mesh init
```

If you previously ran `genesis-mesh dev down`, run `genesis-mesh init` again
before `genesis-mesh na start`; `dev down` removes the local config and
generated artifacts, including local `.node*/` smoke-test directories.

Start the Network Authority from that config:

```bash
genesis-mesh na start
```

The command is blocking. Open `http://127.0.0.1:8443/` in a browser to see the
Network Authority landing page with links to health, policy, CRL, and node
routes. Keep the server running in one terminal, then create an invite token
from another terminal:

```bash
INVITE_TOKEN=$(genesis-mesh admin invite --role anchor)
```

PowerShell equivalent:

```powershell
$INVITE_TOKEN = genesis-mesh admin invite --role anchor
```

The invite controls the node's roles and maximum certificate validity. The
Network Authority assigns roles from the invite and ignores client-supplied
roles during `/join`.

## Node Operator Workflow

Join the mesh with one command:

```bash
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN"
```

PowerShell:

```powershell
genesis-mesh join --na http://127.0.0.1:8443 --token $INVITE_TOKEN
```

`join` enrolls the node, saves the join certificate and active policy, writes
the config, and keeps future commands from repeating genesis and bootstrap
paths. Add `--persistent` when you want the peer runtime to stay running after
enrollment:

```bash
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN" --persistent
```

Invite tokens are single-use. If you already joined once and only want to start
the persistent runtime, reuse the saved local certificate and omit the token:

```bash
genesis-mesh join --na http://127.0.0.1:8443 --persistent
```

Running that command in two terminals with the same `genesis-mesh.toml` starts
two runtimes for the same node identity. The Network Authority will still show
one active node because both processes use the same node key and certificate.
Use a separate config/home directory for each local node when testing multiple
identities.

Check local status:

```bash
genesis-mesh status
```

If `/nodes` or the Network Authority home page shows zero active nodes, check
that the node completed `join`, sent at least one heartbeat, and is using the
same NA endpoint that `status` is querying. A node started only as a peer
runtime, a node using a stale config, or a local cert whose NA database was
deleted will not appear as an active node.

`status` uses the config to show Network Authority health and local node
certificate information.

The local `init` workflow intentionally creates no peer bootstrap anchors. The
Network Authority HTTP API is not a peer WebSocket endpoint. Add a bootstrap
anchor only when you have another Genesis Mesh node listening on its peer
runtime port.

## Developer Workflow

Run the in-process smoke workflow:

```bash
genesis-mesh dev up
```

This starts a local Network Authority in process, creates operator-authenticated
invite tokens, enrolls nodes, fetches policy, and validates node status.

Clean local generated artifacts created by `genesis-mesh init`:

```bash
genesis-mesh dev down
```

Stop `genesis-mesh na start` and any persistent node runtime before running
`dev down`. On Windows, SQLite keeps `.genesis-mesh/na.db` locked while the
Network Authority process is running. The command also removes local `.node*/`
directories created by smoke tests.

## Config Files

By default, commands look for config in this order:

1. `--config <path>`
2. `GENESIS_MESH_CONFIG`
3. `./genesis-mesh.toml`
4. `~/.genesis-mesh/config.toml`

The config stores the Network Authority endpoint, genesis path, key paths,
certificate path, and policy path. Private keys and generated databases must not
be committed. Local CLI output is ignored by default through
`genesis-mesh.toml`, `.genesis-mesh/`, `keys/`, and SQLite database patterns.

## Roles

- `role:anchor`: gateway or relay node.
- `role:bridge`: edge resiliency node.
- `role:client`: endpoint node.
- `role:operator`: policy or administrative operator.
- `role:service:<name>`: service-specific identity.

Role arguments accept either `anchor` or `role:anchor`; the CLI normalizes the
short form.

## Security Notes

- Keep Root Sovereign private keys offline outside local demos.
- Keep NA private keys inside the NA process, a secret manager, or an HSM.
- Use separate operator keys for admin API calls.
- Treat invite tokens as secrets; they are single-use enrollment credentials.
- Keep system time synchronized because certificates and admin signatures are
  time-bound.

## Troubleshooting

### `genesis-mesh` is not found

Install the package in editable mode:

```bash
python -m pip install -e .
```

Then reopen the shell or activate the virtual environment that installed it. On
Windows user installs, Python may place scripts under
`%APPDATA%\Python\Python314\Scripts`; add that directory to `PATH` if pip warns
that installed scripts are not available.

### Node cannot join

- Confirm `genesis-mesh na start` is still running.
- Confirm the URL passed to `--na` matches the Network Authority endpoint.
- Confirm the invite token exists, is unused, and has not expired.
- Check Network Authority logs for `/join` errors.

### Genesis block signature verification fails

Run:

```bash
genesis-mesh genesis verify --genesis .genesis-mesh/genesis.signed.json
```

Confirm the genesis block was not edited after signing.
