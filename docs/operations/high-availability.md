# High Availability

> **Added in v0.60.0.** Optional. With none of the settings below, the Network
> Authority runs exactly as before: one host, one SQLite file, one key file.

A Network Authority (NA) that signs every boundary decision, publishes every
revocation and keeps the evidence store becomes a dependency of everything it
governs. High-availability (HA) mode lets two or more NA instances share one
PostgreSQL database behind a load balancer, so losing an instance loses no
service and no data.

## What HA mode guarantees

With two or more instances behind a load balancer:

- **Any instance can serve any request.** Instances keep no state of their
  own. Decisions, attestations, policies, CRLs, nonces, rate-limit counters,
  job leases and the evidence store all live in the shared database.
- **Losing an instance keeps the service up.** The load balancer stops sending
  traffic to an instance that fails its readiness probe. The others keep
  serving decisions, revocations and evidence.
- **Exactly-once operations stay exactly once.** The database enforces them,
  not the application, so they hold for any number of instances and workers
  (see [Exactly-once operations](#exactly-once-operations)).
- **One signing key.** Every instance signs with the same key, loaded from Key
  Vault (or the platform's secret store) into memory. It is never written to
  disk.

The release is verified by an integration test that runs decisions, execution
evidence and revocations continuously through nginx against two instances. It
kills one instance (`SIGKILL`, master and workers) mid-run, then checks that
every acknowledged decision, evidence record and revocation is stored exactly
once and that the whole store verifies.

What HA mode is **not**: multi-region active-active. Cross-region writes and
replicating SQLite (for example with Litestream) are out of scope. For
regional disasters, use the database's geo-redundant backups (see
[Backup, restore and disaster recovery](#backup-restore-and-disaster-recovery)).

## Architecture

```{mermaid}
flowchart LR
    C[Controllers, nodes, operators] --> LB[Load balancer<br/>probes /readyz]
    LB --> A[NA instance A]
    LB --> B[NA instance B]
    A --> DB[(PostgreSQL<br/>zone-redundant)]
    B --> DB
    KV[Key Vault secret<br/>NA signing seed] -. managed identity, at start-up .-> A
    KV -. managed identity, at start-up .-> B
```

| Component | Azure reference | Self-hosted reference |
|---|---|---|
| Database | Azure Database for PostgreSQL Flexible Server, zone-redundant HA | PostgreSQL 15+ with streaming replication |
| Instances | 2+ VMs or container replicas, each with a managed identity | 2+ containers (`infrastructure/ha/docker-compose.yml`) |
| Load balancer | Application Gateway or Load Balancer, probe `/readyz` | nginx (`infrastructure/ha/nginx.conf`) |
| Signing key | Key Vault secret, soft delete and purge protection on | platform secret store, injected as an environment variable |

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `DATABASE_URL` | unset (SQLite at `DB_PATH`) | `postgresql://user:pass@host/db` stores all state in PostgreSQL. `sqlite:///path` names a SQLite file explicitly. |
| `NA_HA_MODE` | `off` | `on` refuses to start unless `DATABASE_URL` is PostgreSQL, the key provider is not `file` and rate limits are shared. A misconfigured "HA" deployment fails at start-up instead of quietly keeping per-instance state. |
| `NA_KEY_PROVIDER` | `file` | `file` (`NA_PRIVATE_KEY_FILE`), `env` (`NA_PRIVATE_KEY_SEED`) or `azure-keyvault` |
| `AZURE_KEY_VAULT_URL` | | `https://<vault>.vault.azure.net` (for `azure-keyvault`) |
| `NA_KEY_SECRET_NAME` | | Key Vault secret holding the base64 Ed25519 seed |
| `AZURE_CLIENT_ID` | | Selects a user-assigned managed identity |
| `RATE_LIMIT_STORE` | `database` on PostgreSQL, `memory` on SQLite | `database` counts requests across every worker and instance |

Install the PostgreSQL driver with `pip install "genesis-mesh[postgres]"`. The
container image already includes it.

### Database

Create the database with **code-point collation**. The NA orders policies,
CRLs and evidence by identifier, and those orders feed signed digests. A
locale collation such as `en_US.utf8` would order some identifiers
differently, so the NA refuses to start on one.

```sql
CREATE DATABASE genesis_mesh
  TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C';
```

On Azure Database for PostgreSQL Flexible Server, run the same statement after
the server is created. Restrict access to the NA instances' network (private
access, no public endpoint) and require TLS (`sslmode=require` in
`DATABASE_URL`).

Migrations run automatically at start-up. Instances that start together queue
on a database lock: the first applies pending migrations and the rest find
them done.

### Signing key

All instances must sign with the key named in the genesis block. In HA mode
the key comes from a provider that never puts it in a file:

- **`azure-keyvault`**: store the base64 Ed25519 seed (the contents of the
  `na.key` file without comment lines) as a Key Vault **secret**. Grant each
  instance's managed identity *Key Vault Secrets User* on that secret. The NA
  reads it once at start-up with the managed identity (instance metadata
  service on VMs, `IDENTITY_ENDPOINT` on App Service and Container Apps) and
  keeps it in memory only. If the read fails, the instance does not start.
- **`env`**: the platform's secret store injects `NA_PRIVATE_KEY_SEED` into
  the process environment (Kubernetes secrets, Container Apps secret
  references, Docker secrets).

Azure Key Vault and Managed HSM do not offer Ed25519 *signing* keys, so the
seed is a secret rather than a non-exportable key. Every NA signature goes
through one `Signer` interface, so a remote-signing provider (an HSM with
Ed25519) can be added later without changing callers.

`/readyz` reports each instance's `key_id` and key fingerprint, never the key,
so a mismatch between instances is visible.

## Load balancing and readiness

`/healthz` reports process liveness only. `/readyz` is the load-balancer
probe. It returns 200 only when:

- the database is reachable and writable (a primary, not a read replica);
- the schema is at the version this release expects;
- the signing key is loaded;
- in HA mode, the shared rate limiter is in use.

Otherwise it returns 503 with the reason in `error.details`:

```json
{
  "status": "ready",
  "instance": "na-a-7f3c:1a2b3c4d",
  "ha_mode": "on",
  "database": {"backend": "postgres", "writable": true, "schema_version": 13, "expected_schema_version": 13},
  "signing_key": {"key_id": "na-prod", "provider": "azure-keyvault", "fingerprint": "5c1e…"},
  "rate_limiter": "database",
  "db_path": "postgresql://genesis:***@db.example/genesis_mesh"
}
```

Configure the load balancer to:

- probe `/readyz` every few seconds and remove an instance after one or two
  failures;
- pass a request on to another instance only when it could not reach the
  first (connection refused, timeout, 502 or 503), never after the request was
  delivered;
- forward the client address (`X-Forwarded-For`). The NA trusts one proxy hop.

`infrastructure/ha/nginx.conf` is a working example.

## Exactly-once operations

| Operation | How the database enforces it |
|---|---|
| Node and admin nonces | one atomic insert decides; a second use is a replay, even when two instances receive the same request |
| CRL publication | each sequence is written once; a concurrent revocation that loses the race rebuilds its CRL from the new active list and retries, so no revocation is lost and the active CRL is always the highest sequence |
| Boundary policy versions | `(policy_id, version)` is unique; a concurrent publish takes the next version |
| Boundary policy activation | one active version per policy (unique index); the losing concurrent activation gets `409 boundary_policy_activation_conflict` |
| Revocation feed import | `(issuer, sequence)` is unique |
| Evidence store (v0.59) | store, decision and resource chain positions are unique; appends serialize on a database lock |
| Invite tokens | consumed with a conditional update |
| Rate limits | one atomic counter per client and window, shared by every instance |
| Single-runner jobs | a lease row; evidence retention runs on one instance at a time (`409 retention_in_progress` elsewhere) |

## Migrating from SQLite

The SQLite file is opened read-only and never changed, so rollback is to keep
using it.

1. Stop the NA, or stop writes to it.
2. Back up the SQLite file:
   `genesis-mesh managed backup --db-path na.db --output na-before-ha.db`.
3. Start the v0.60 NA once on the SQLite file, so its schema is current, then
   stop it again.
4. Create the PostgreSQL database (C collation, as above).
5. Migrate and verify:

   ```bash
   genesis-mesh na migrate-db --from sqlite:///var/lib/genesis-mesh/na.db \
     --to "$DATABASE_URL" --genesis genesis.signed.json --report migration.json
   ```

   The command refuses a non-empty target or an out-of-date source. It copies
   every table and checks that each table's row count and content digest
   match. It then verifies the target: every boundary policy digest, CRL
   continuity, and the evidence store's hash chain and signatures. It writes a
   `database_migrated` audit event. It exits non-zero on any mismatch.
6. Set `DATABASE_URL`, the key provider and `NA_HA_MODE=on`, then start the
   instances.
7. Confirm `/readyz` on every instance and through the load balancer.

## Backup, restore and disaster recovery

With PostgreSQL, backups are the database service's job.
`genesis-mesh managed backup` and `restore` remain SQLite-only.

| | Azure Database for PostgreSQL Flexible Server |
|---|---|
| Zone failure | zone-redundant HA: automatic failover to the standby, RPO 0, typically under two minutes |
| Operator error or corruption | point-in-time restore to any second in the retention window (7 to 35 days) |
| Region loss | geo-redundant backup: restore in the paired region (RPO under an hour) |

**Restore drill** (run it before going to production, then periodically):

1. Restore the server to a new server at a chosen point in time.
2. Run `genesis-mesh na verify-db --database-url "$RESTORED_URL" --genesis
   genesis.signed.json`. It must report `"ok": true`.
3. Point a test instance at the restored server and check `/readyz` and a
   decision.
4. To fail over for real, switch `DATABASE_URL` on every instance and restart
   them one at a time.

**Signing key:** enable soft delete and purge protection on the vault. A
deleted secret can then be recovered (`az keyvault secret recover`) and
cannot be purged during the retention period. Keep an offline, access-controlled
copy of the seed under your key-ceremony procedure.

## Verifying a database

`genesis-mesh na verify-db` checks the invariants the NA relies on, on either
backend:

```bash
genesis-mesh na verify-db --database-url "$DATABASE_URL" --genesis genesis.signed.json
genesis-mesh na verify-db --db-path /var/lib/genesis-mesh/na.db
```

It checks that every boundary policy matches its stored digest, that CRL
sequences have no gaps with only the highest one active, and that the
evidence store is one unbroken hash chain. With `--genesis`, it also checks
every signature in the evidence store.

## Security notes

- The database holds everything except the signing key. Restrict it to the
  NA instances (private network, TLS, a dedicated role) and treat database
  credentials like operator keys.
- HA mode refuses the `file` key provider, so key files are not copied
  between hosts.
- The NA fails closed. If the database or key is unavailable, the instance
  reports not ready and serves no decisions. It never falls back to local
  state.
