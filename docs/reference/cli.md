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
| `--config` | Config path to write. Defaults to `genesis-mesh.toml` in the current directory, or `<home>/genesis-mesh.toml` when `--home` is supplied explicitly. |
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
| `--force` | Replace an existing config and generated local artifacts. Refuses to delete the directory the command is running from. |

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
| `--operator-key` | Operator private key path. Can be used instead of a config file. |
| `--operator-key-id` | Operator key ID. Defaults to `operator-local`. |
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
genesis-mesh sovereign inspect --endpoint https://na.genesismesh.connectorzzz.com
```

The command reads `/sovereign.json`, not private files. It prints the network
name, endpoint, NA public key prefix, validity window, and public trust
surfaces useful for recognition.

### `genesis-mesh federation bootstrap`

Reviews another sovereign's public trust material and optionally issues a
direct-recognition treaty from the accepting sovereign.

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --config ./acceptor.toml \
  --role service:maintainer \
  --claim proof=federation-bootstrap \
  --evidence ./federation-bootstrap-evidence.json \
  --yes
```

Use `--dry-run` to fetch `/healthz`, `/readyz`, `/genesis`,
`/sovereign.json`, `/recognition-policy`, and `/connectome.json` without
issuing a treaty. Without `--dry-run`, the command previews the treaty scope,
requires confirmation unless `--yes` is supplied, issues the treaty with the
acceptor operator key, and verifies the resulting trust path.

Use `--issuer-bundle` when the issuer has shared a trust bundle:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer-bundle ./issuer-trust-bundle.json \
  --config ./acceptor.toml \
  --role service:maintainer \
  --yes
```

The command still compares the bundle with the live issuer endpoint and still
requires explicit operator authorization before issuing trust. `--config` is an
alias for the acceptor operator config. `--acceptor-config` remains available
for scripts that prefer endpoint-specific names.

If treaty issuance succeeds but post-issue trust-path verification fails, the
command reports that the treaty was persisted, writes that state to the
evidence file when requested, and prints a cleanup hint using
`genesis-mesh treaty revoke`.

### `genesis-mesh fleet generate`

Scaffolds a fleet of independent sovereign Network Authorities — for each NA it
generates root/NA/operator keys, a signed genesis block, and a
`genesis-mesh.toml`, then writes a `fleet.toml` manifest listing them. Adding an
NA later is a one-line manifest edit.

```bash
genesis-mesh fleet generate \
  --output ./fleet \
  --count 4 \
  --prefix edge \
  --base-port 8443
# or name them explicitly:
genesis-mesh fleet generate --output ./fleet --name bos-na --name sas-na
```

Each NA is its own sovereign (distinct root key and genesis). Ports increment
from `--base-port`. The generated genesis blocks carry a placeholder policy
hash — replace it before production use.

### `genesis-mesh fleet mesh`

Issues recognition treaties across every ordered pair of NAs in the manifest so
the whole fleet trusts itself. It reviews each sovereign, issues the treaty with
the accepting NA's operator key, and verifies the resulting trust path. The
operation is **idempotent** — pairs that already have an active treaty are
skipped.

```bash
genesis-mesh fleet mesh --config ./fleet/fleet.toml
genesis-mesh fleet mesh --config ./fleet/fleet.toml --role role:operator --format json
```

### `genesis-mesh fleet verify`

Confirms a trust path resolves across every ordered pair. Exits non-zero if any
pair is untrusted.

```bash
genesis-mesh fleet verify --config ./fleet/fleet.toml
```

### `genesis-mesh fleet status`

Reports `healthz`/`readyz` for each NA in the manifest.

```bash
genesis-mesh fleet status --config ./fleet/fleet.toml
```

```{note}
The `fleet` commands are deterministic and API-driven (no host process
management). Production NAs run one-per-host under systemd or Kubernetes — see
the [Deployment](../operations/deployment-index.md) runbooks. For local
dev/demo orchestration (start/stop/tunnels on one host) use `ops/scripts/fleet.py`.
```

### `genesis-mesh trust-bundle export`

Exports public sovereign trust material into a reviewable JSON bundle.

```bash
genesis-mesh trust-bundle export \
  --na https://issuer.example.org \
  --output ./issuer-trust-bundle.json
```

The bundle packages existing public surfaces such as `/sovereign.json`,
`/genesis`, `/connectome.json`, `/recognition-policy`, and
`/sovereign-revocation-feed`. It does not include private keys, invite tokens,
database paths, or operator credentials.

### `genesis-mesh trust-bundle inspect`

Inspects a bundle offline:

```bash
genesis-mesh trust-bundle inspect \
  --bundle ./issuer-trust-bundle.json
```

The output shows identity, endpoint, public-key fingerprints, validity, policy,
revocation feed status, and Connectome counts.

### `genesis-mesh trust-bundle validate`

Validates bundle structure and optionally compares it with a live endpoint:

```bash
genesis-mesh trust-bundle validate \
  --bundle ./issuer-trust-bundle.json \
  --na https://issuer.example.org
```

Use live validation before feeding a bundle into federation bootstrap.

### `genesis-mesh trust-bundle import`

Imports a bundle into local review evidence without granting trust:

```bash
genesis-mesh trust-bundle import \
  --bundle ./issuer-trust-bundle.json \
  --na https://issuer.example.org \
  --output ./issuer-trust-bundle-receipt.json
```

The receipt records `trust_granted: false`. Trust is created only by an explicit
operator-signed federation bootstrap or treaty issue.

### `genesis-mesh treaty list`

Lists direct-recognition treaties with persisted status, derived lifecycle
state, and expiry risk:

```bash
genesis-mesh treaty list \
  --na https://na.genesismesh.connectorzzz.com
```

### `genesis-mesh treaty inspect`

Inspects one treaty's scope, lifecycle state, validity window, metadata, and
revocation context:

```bash
genesis-mesh treaty inspect \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id>
```

### `genesis-mesh treaty renew`

Issues a successor treaty with the same scope, then retires the old treaty with
a `renewed_by:<new-id>` revocation reason:

```bash
genesis-mesh treaty renew \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --yes
```

### `genesis-mesh treaty replace`

Issues a successor treaty with updated scope, then retires the old treaty with
a `replaced_by:<new-id>` revocation reason:

```bash
genesis-mesh treaty replace \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --role service:observer \
  --claim reason=scope-tightening \
  --yes
```

### `genesis-mesh treaty revoke`

Revokes a treaty through the existing operator-signed admin endpoint:

```bash
genesis-mesh treaty revoke \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --reason relationship_ended \
  --yes
```

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

### `genesis-mesh supply-chain verify`

Verifies whether a portable maintainer attestation authorizes a CI or release
gate under a signed recognition treaty.

```bash
genesis-mesh supply-chain verify \
  --attestation docs/examples/assets/supply-chain-trust-gate/maintainer-attestation.json \
  --treaty docs/examples/assets/supply-chain-trust-gate/recognition-treaty.json \
  --treaty-issuer-public-key "$(cat docs/examples/assets/supply-chain-trust-gate/treaty-issuer-public-key.txt)" \
  --project-id pypi:demo-package \
  --repository https://github.com/example/demo-package \
  --proof-bundle supply-chain-trust-gate-proof.json
```

Stable exit codes:

- `0`: allow.
- `10`: deny.
- `2`: verifier error.

The command emits compact audit output and does not print private keys,
signatures, or full signed payload bodies. Add `--revocation-feed` to deny the
same attestation after an issuer publishes a signed revocation feed.

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

### `genesis-mesh managed backup`

Creates a consistent online backup of a Network Authority SQLite database.

```bash
genesis-mesh managed backup \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /backups/genesis-mesh-na-YYYYMMDDHHMMSS.db
```

### `genesis-mesh managed restore`

Restores a Network Authority database from a backup. Stop the Network Authority
before running it.

```bash
genesis-mesh managed restore \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup /backups/genesis-mesh-na-known-good.db \
  --pre-restore-backup /backups/na-before-restore.db \
  --yes
```

The command validates that the backup looks like a Genesis Mesh NA database and
requires `--yes` before replacing the DB file.

### `genesis-mesh managed audit-export`

Exports redacted Network Authority audit events as JSON Lines or JSON.

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /var/log/genesis-mesh/audit-events.jsonl
```

Use `--event-type recognition_treaty_issued` to export one event class and
`--format json` when a JSON array is easier to ingest.

## Atlas Commands

The `genesis-mesh atlas` group builds a read-only trust graph explorer from a
recognition-graph export. It surfaces sovereigns, relationships, treaty scope,
and verified TrustEvidence records without write paths or ranking.

### `genesis-mesh atlas build`

Reads a recognition-graph JSON export, optionally verifies TrustEvidence
records against it, and writes a self-contained `atlas.json` + `atlas.html` to
the output directory.

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/
```

With TrustEvidence overlay:

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/ \
  --evidence ./evidence/ \
  --public-key <sovereign-a-public-key-base64> \
  --public-key <sovereign-b-public-key-base64>
```

| Option | Description |
|---|---|
| `--graph` | Recognition graph JSON export path (required). |
| `--output` | Directory to write `atlas.json` and `atlas.html` (required). |
| `--evidence` | Directory of TrustEvidence JSON files to overlay (optional). |
| `--public-key` | Issuer public key (base64) for signature verification. Repeatable. |

Exit codes:
- `0` — Build succeeded (all supplied evidence verified or none supplied).
- `1` — One or more evidence files could not be parsed or signature verification failed.

The operator console also exposes a live `/atlas` page and `/atlas.json` endpoint
generated from the NA's live recognition graph.

## Trust Decision Commands

The `genesis-mesh trust` group evaluates trust decisions over a recognition-graph
export and issues signed TrustEvidence records that a second sovereign can verify
offline, without sharing a backend, database, or identity provider.

All commands operate over a graph export file produced by
`proof export-graph`, `federation bootstrap --evidence`, or the live
`/trust/graph` Network Authority endpoint.

### `genesis-mesh trust decide`

Evaluates a trust decision from one sovereign toward another and prints the
verdict, justifying signals, and trust path.

```bash
genesis-mesh trust decide \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer
```

The verdict is one of `allow`, `warn`, `block`, or `escalate`:

| Verdict | Meaning |
|---|---|
| `allow` | Active treaty path with no risk signals. |
| `warn` | Active path, but one or more treaties are expiring soon. |
| `escalate` | Active path, but a revocation feed targets a sovereign on the path. |
| `block` | No active path, or requested roles are outside treaty scope. |

The exit code mirrors the verdict: `0`=allow, `1`=warn, `2`=escalate, `3`=block.
Use `--format json` for machine-readable output.

### `genesis-mesh trust evidence`

Evaluates trust and emits a signed TrustEvidence record. The evidence binds
the verdict to the recognition-graph state via a SHA-256 digest so a second
sovereign can independently verify it later.

```bash
genesis-mesh trust evidence \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer \
  --issuer-sovereign sovereign-a \
  --signing-key keys/na.key \
  --key-id na-2026-q1 \
  --output evidence-a-b.json
```

The output file is a signed JSON record containing the verdict, signals,
trust path, graph digest, and issuer Ed25519 signature.

### `genesis-mesh trust verify-evidence`

Verifies the signature on a TrustEvidence record. Without `--graph`, checks
only the Ed25519 signature. With `--graph`, also re-derives the graph digest
and confirms the evidence was produced over the same graph state.

```bash
# Signature check only
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key>

# Strict: signature + graph-state binding
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key> \
  --graph fleet-graph.json
```

Exits `0` on success, `1` on any verification failure. Use `--format json`
for machine-readable output.

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
