# Network Authority Commands

Commands that create, run and administer a Network Authority.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Setup

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
| `--env-file` | Also write Network Authority settings for `na start --env-file` (v1.1.0): the genesis block, the NA key, the database, `PORT` from `--na-port`, the init operator key (`privileged`), `BOUNDARY_POLICY_ENFORCEMENT=required`, `EVIDENCE_STORE=on` and `NA_PROXY_HOPS=0`. Paths are written relative to the file; no private key material. Refuses an existing file unless `--force` is given. |
| `--force` | Replace an existing config and generated local artifacts. Refuses to delete the directory the command is running from. |

`init` is suitable for local development and demos. Production key generation
should happen through an explicit key-management ceremony.

For a named sovereign on a VM, keep the paths explicit:

```bash
genesis-mesh init \
  --network-name USG-NB \
  --na-endpoint https://na.example.org \
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

Starts a local Network Authority from config or, with `--env-file`, from a
settings file.

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
| `--evidence-store` | `on` keeps an append-only record of decisions and execution evidence (v0.59). Also read from `evidence_store` in the `[na]` config section; default `off`. |
| `--env-file` | Run with the production settings in this file instead of the config (v1.1.0). See below. |

From config, the NA has one operator key (privileged tier) and the default
settings. With `--env-file`, it is the production app (the one Gunicorn
serves) with the settings in the file: boundary policy enforcement, several
operator keys with their tiers, rate limits and every other variable in
{doc}`../configuration`. The NA's settings come only from the file, not from the
process environment (see {doc}`../configuration` for what is still read from
it).
`--config`, `--db-path` and `--evidence-store` are refused with `--env-file`.
The port is `PORT` from the file (default `8443`), the host `127.0.0.1`;
`--host` and `--port` override them. The command prints the settings that
matter for development, without key material:

```bash
genesis-mesh na start --env-file local/na.env
```

This command uses Werkzeug's development server. Use the container entry point
and Gunicorn for production-style deployments.

If `genesis-mesh dev down` was run earlier, recreate local config first with
`genesis-mesh init`; `dev down` removes `genesis-mesh.toml`, `.genesis-mesh/`,
and local `.node*/` smoke-test directories.

### `genesis-mesh keygen operator`

> **v1.1.0** — Local Governed Network Authority

Generates an operator (admin) key pair and, with `--env-file`, registers its
public key and tier in a Network Authority settings file
(`OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON`), keeping every
other line. The tier defaults to `standard`: what a controller needs for
`/admin/boundary/evaluate` and reads, without publishing policies, issuing
attestations or registering keys. The command refuses existing key files, and
a key ID already registered with another public key unless `--replace` is
given. Restart the NA to load a new key.

To rotate a key, remove its two files and run the command again with
`--replace`, then restart the NA.

```bash
genesis-mesh keygen operator \
    --output local/.genesis-mesh/keys/controller \
    --key-id controller \
    --tier standard \
    --env-file local/na.env
```

Exit code 0 on success; 1 on failure.

## Admin

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
| `--token-expiry-hours` | Invite token lifetime (the NA's default: 24 hours, one hour for an edge invite). |
| `--recipient-key` | Bind the invite to one node public key. |
| `--node-sovereign-id` | Beta (v1.7.0): make an edge invite for the edge node with this sovereign ID. Needs `--executor-resource-prefix`, a privileged operator key, and an NA with `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on` (both off by default; otherwise `409 edge_requires_evidence_store`). |
| `--executor-resource-prefix` | Beta (v1.7.0): the resource prefix of the edge node's executor key, such as `edge:site7-17/`; it ends with `/` or `:` and overlaps no active key's or outstanding edge invite's prefix. |

An edge invite is redeemed by the edge agent (`genesis-mesh-edge enroll`),
which registers its executor key at `/join`. Bind it to the device with
`--recipient-key` and the node key `genesis-mesh-edge init` prints; see
{doc}`../../operations/edge-agent`.

### `genesis-mesh admin edge-nodes`

*Beta (v1.7.0).* Lists edge nodes, newest enrolment first, as JSON
(`GET /admin/edge-nodes`, read tier).

```bash
genesis-mesh admin edge-nodes --status offline --limit 50
```

| Option | Description |
|---|---|
| `--status` | `online`, `offline` or `revoked`. |
| `--limit` | Edge nodes per page, 1 to 500 (default 100). |
| `--before` | The `next_before` of the previous page. |

### `genesis-mesh admin revoke`

Revokes a certificate through the operator-authenticated admin API.

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise
```

Useful reasons are `key_compromise`, `cessation_of_operation`, `superseded`,
and `unspecified`. For an edge node (v1.7.0) it revokes every certificate the
node holds, retires its executor key and revokes the grants that key bears;
the printed JSON has an `edge_node` block.

### `genesis-mesh admin revoke-operator-key`

Switches an **operator** key off immediately, without restarting the Network
Authority. Use this when an operator key is lost or stolen.

```bash
genesis-mesh admin revoke-operator-key operator-alice --reason key_compromise
```

This is a **privileged-tier** operation: a standard operator key receives
`403 insufficient_operator_tier`.

The key stops authenticating on the next request — no restart, no config edit.
Rejection happens before the signature is checked and before the nonce is
consumed, so a revoked key cannot act at all, including revoking other
operators.

```{warning}
Revocation is **terminal** for the life of the deployment. There is no
un-revoke endpoint, and the revocation is stored in the NA's database: the key
ID stays revoked across restarts and configuration edits, even with a new
public key. To replace the key, generate a new key under a new key ID
(`genesis-mesh keygen operator --env-file ...`) and restart the NA.
```

The service **refuses to revoke the last usable operator key**
(`409 last_active_operator_key`) — otherwise this command could cause exactly
the outage it exists to avoid. Configure a second operator key first.

A caller presenting a revoked key is told only `Unknown admin key`, identical to
an unrecognised key: whoever holds a stolen key learns nothing about whether the
compromise was noticed. The real reason is recorded in the audit log as
`admin_auth_failed` with `reason: revoked_key`, alongside the
`operator_key_revoked` event.

## Database

### `genesis-mesh na migrate-db`

> **v0.60**: High Availability

Copy a Network Authority SQLite database into an empty PostgreSQL database and
verify it. Stop the NA first. The source is opened read-only and left
untouched; `--from` takes a path or `sqlite:///path`. The target must be
empty, and the source must be at the current schema version (start this
release on it once).

```bash
genesis-mesh na migrate-db \
    --from sqlite:///var/lib/genesis-mesh/na.db \
    --to "$DATABASE_URL" \
    --genesis genesis.signed.json \
    --report migration.json
```

Every table's row count and content digest must match the source, and the
target must pass `na verify-db`; otherwise the command exits non-zero. A
`database_migrated` audit event is written to the target. See
[High Availability](../../operations/high-availability.md).

### `genesis-mesh na verify-db`

> **v0.60**: High Availability

Verify a Network Authority database (SQLite or PostgreSQL) after a restore or
migration. It checks that boundary policies match their stored digests, that
CRL sequences have no gaps with only the highest one active, and that the
evidence store is an unbroken hash chain. With `--genesis` it also checks
every evidence signature, each NA signature with the key valid at the
entry's time: the NA key history in the database is verified from the
genesis block's root key, never taken from its rows alone (v1.5.0).

```bash
genesis-mesh na verify-db --database-url "$DATABASE_URL" --genesis genesis.signed.json
genesis-mesh na verify-db --db-path /var/lib/genesis-mesh/na.db
```

Prints a JSON report; exit code 0 when every check passes, 1 otherwise.

## Managed Operations

### `genesis-mesh managed backup`

*Beta.*

Creates a consistent online backup of a Network Authority SQLite database.
For PostgreSQL, use `pg_dump`.

```bash
genesis-mesh managed backup \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /backups/genesis-mesh-na-YYYYMMDDHHMMSS.db
```

### `genesis-mesh managed restore`

*Beta.*

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

*Beta.*

Exports redacted Network Authority audit events as JSON Lines or JSON, from a
SQLite database. The audit log is plain rows in the NA database, not signed or
chained; for records whose changes are detectable, use the evidence store
({doc}`evidence-audit`).

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /var/log/genesis-mesh/audit-events.jsonl
```

Use `--event-type recognition_treaty_issued` to export one event class and
`--format json` when a JSON array is easier to ingest.

## Key and Genesis Commands

These are the stable commands of a key ceremony: generate the root and NA
keys, write the genesis block, and sign it with the root key on an offline
machine. `genesis-mesh init` does all of this in one step for local use and
writes every key, the root key included, to one directory. For a sovereign
that other parties rely on, follow the root key ceremony in
{doc}`../../operations/key-succession`.

### `genesis-mesh keygen root`, `keygen network-authority` and `keygen node`

Write an Ed25519 key pair: the private key to `<output>.key` and the public
key to `<output>.pub`.

```bash
genesis-mesh keygen root --output keys/root --key-id rs-2025-q1
genesis-mesh keygen network-authority --output keys/na --key-id na-2025-q1
genesis-mesh keygen node --output keys/node --key-id node-1
```

| Option | Description |
|---|---|
| `--output` | Output path without extension (required). |
| `--key-id` | Key identifier. Defaults to `rs-2025-q1` for `root` and `na-2025-q1` for `network-authority`; optional for `node`. |

### `genesis-mesh genesis create`

Write an unsigned genesis block.

```bash
genesis-mesh genesis create \
  --network-name "USG" \
  --network-version "v0.1" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --output genesis.json
```

| Option | Description |
|---|---|
| `--network-name` | Network name (required). |
| `--network-version` | Network version (default `v0.1`). |
| `--root-key` | Path to the root public key (required). |
| `--na-key` | Path to the NA public key (required). |
| `--na-valid-days` | The NA key's `valid_to`, in days from now (default 90). Since 1.5.0 the genesis key's `valid_to` is shown, not enforced; a key succession replaces the key. |
| `--anchor` | Bootstrap peer anchor in `id:endpoint` form. Repeatable. |
| `--output` | Output path (required). |

### `genesis-mesh genesis sign`

Sign a genesis block with the root private key. Run it on the offline machine
that holds the root key.

```bash
genesis-mesh genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json
```

| Option | Description |
|---|---|
| `--genesis` | Unsigned genesis block (required). |
| `--root-private-key` | Root private key (required). |
| `--key-id` | Root key identifier (default `rs-2025-q1`). |
| `--output` | Signed genesis block path (required). |

### `genesis-mesh genesis verify` and `genesis-mesh info`

`genesis verify` checks the genesis block's signatures against the root public
key the block itself names, and exits 1 when one fails. It does not tell you
whether that root key is the one you expect: compare `root_public_key` with a
copy you obtained out of band. `info` (beta) prints the block's network, keys,
validity and allowed suites.

```bash
genesis-mesh genesis verify --genesis genesis.signed.json
genesis-mesh info --genesis genesis.signed.json
```
