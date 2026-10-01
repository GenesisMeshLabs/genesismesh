# v0.60.0 Plan -- Optional High Availability for the Network Authority

## Context

The Network Authority runs as one process tree on one host, on one SQLite
file. That is right for simple deployments and stays the default, but an
organisation that depends on the NA for every boundary decision, revocation
and (since v0.59.0) evidence record needs it to survive losing an instance.

The current code assumes a single host:

- every store mixin (`na_service/db_*.py`) uses a `sqlite3` connection directly,
  with `?` placeholders and some SQLite-only SQL (`INSERT OR REPLACE`,
  `PRAGMA`, `sqlite_master`, SQLite date functions, the SQLite backup API);
- the rate limiter (`na_service/rate_limit.py`) is in-process memory, so even
  today's four gunicorn workers each enforce their own limit;
- the signing key is read from a local file (`NA_PRIVATE_KEY_FILE`);
- some "exactly once" operations are checked in the application, not the
  database: node-request nonces are checked (`has_nonce`) and then inserted
  (`add_nonce`), so two concurrent requests both pass the check and one fails
  with a database error instead of a clean replay rejection; the next CRL
  sequence is computed as `current.sequence + 1`.

This is a minor release: it changes the storage layer and deployment model,
while leaving the default deployment exactly as it is.

v0.60.0 should prove:

> With two or more NA instances sharing a SQL database behind a load balancer,
> one instance can be stopped and decisions, revocations and evidence keep
> working through the others, with no data loss or duplicates.

## Scope

### In scope
- A storage backend interface with two implementations: SQLite (default,
  unchanged) and PostgreSQL (Azure Database for PostgreSQL as the reference)
- Portable SQL across all store mixins and migrations
- Database-enforced "exactly once" semantics for policy activation, CRL and
  revocation sequences, evidence chains and nonces
- Shared rate limiting and a lease mechanism for single-runner jobs
- A signing-key provider interface: local file (default), Azure Key Vault
- Readiness that reflects database and key health, for load-balancer probes
- A migration tool from SQLite to PostgreSQL with verification
- Backup, restore and disaster-recovery documentation for the SQL option
- A two-instance HA test in CI

### Out of scope
- Multi-region active-active and cross-region write replication
- Replicating SQLite (for example Litestream) as an HA mode
- Automatic signing-key rotation
- Non-exportable (HSM) signing. It is a future hardening option; this
  release keeps the architecture ready for it (section 5) but does not
  implement it
- Terraform for the HA reference infrastructure (documented, not automated;
  a follow-up can add a module)
- Running the public reference overlay (`examples/public_dashboard`) in HA

## Design

### 1. Configuration and modes

| setting | default | effect |
|---|---|---|
| `DATABASE_URL` | unset (SQLite at the configured path) | `postgresql://…` selects PostgreSQL |
| `NA_HA_MODE` | `off` | `on` refuses to start unless `DATABASE_URL` is PostgreSQL and the key provider is not `file` |
| `NA_KEY_PROVIDER` | `file` | `file` or `azure-keyvault` |

With no new settings the NA behaves exactly as v0.59.0: same SQLite file,
same migrations, same key file. `NA_HA_MODE=on` is a guard rail so a
misconfigured "HA" deployment fails at start-up instead of silently running
per-instance state.

### 2. Storage backend

- `na_service/storage/` introduces a small backend interface used by every
  mixin: `execute`, `fetchone`, `fetchall`, `transaction()`, `backend_name`,
  and dialect helpers (`upsert`, `now()` handled in Python, not SQL).
- `SQLiteBackend` wraps today's connection and pragmas unchanged.
- `PostgresBackend` uses psycopg 3 with a connection pool; the driver is an
  optional extra (`pip install genesis-mesh[postgres]`) so SQLite users gain
  no dependency.
- Placeholders: mixins keep `?`; the Postgres backend translates them.
- SQLite-only SQL is replaced with portable forms supported by both
  (`INSERT … ON CONFLICT … DO UPDATE/NOTHING`, Python-computed timestamps,
  catalogue queries behind a backend method). The operator console queries
  (`dashboard.py`, `atlas.py`, `connectome.py`) move behind the same interface.
- Migrations stay numbered and shared; the rare statement that differs
  (triggers, partial-index syntax if needed) lives in a per-dialect file with
  the same number. The migration runner takes a database lock
  (`pg_advisory_lock` / SQLite's single writer) so two instances starting
  together cannot apply a migration twice.
- `backup()` remains SQLite-only; PostgreSQL backups are the managed
  service's job (section 8).

### 3. Exactly-once operations

Each rule is enforced by the database, so it holds for any number of
instances and workers, on both backends:

| operation | mechanism |
|---|---|
| Boundary policy activation | existing partial unique index (one active version per policy), inside a transaction |
| CRL sequence | `UNIQUE(sequence)` on CRL rows; allocate inside the write transaction; on conflict re-read and retry (bounded) |
| Sovereign revocation feed import | existing stale-sequence check moved into the transaction plus `UNIQUE(issuer, sequence)` |
| Evidence chains (v0.59.0) | `UNIQUE(decision_id, sequence_no)`, `UNIQUE(resource_id, resource_sequence)`, `UNIQUE(store_sequence)` |
| Node and admin nonces | single atomic claim: insert, and treat a unique-violation as replay (removes the check-then-insert race, which also affects today's multi-worker SQLite deployment) |
| Invite tokens, enrolment | consumed with a conditional update (`… WHERE used = 0`) checking the row count |

A concurrency test suite runs each operation from parallel workers against
both backends and asserts exactly one success.

### 4. Shared runtime state

- **Rate limiting**: `RateLimiter` gets a database-backed implementation
  (fixed windows per key, one upsert per request, expired windows pruned
  opportunistically). In-memory remains the SQLite default; HA mode requires
  the shared one. This also makes limits correct across gunicorn workers.
- **Single-runner jobs**: the NA has no in-process background jobs today
  (timers are systemd units). Any job that must run once (evidence retention,
  future CRL refresh) takes a lease row (`job_leases`: name, holder,
  expires_at) with an atomic claim; on PostgreSQL, `pg_try_advisory_lock`.
- Nothing that affects a trust decision is cached per instance. Caches that
  exist (for example parsed genesis block) are read-only configuration.

### 5. One signing key

- `KeyProvider` interface: `file` (today's behaviour) and `azure-keyvault`,
  which reads the Ed25519 seed from a Key Vault **secret** with the
  instance's managed identity at start-up and holds it in memory only.
- Azure Key Vault and Managed HSM do not, to our knowledge, offer Ed25519
  signing keys, so non-exportable HSM signing is not available on Azure for
  the current signature suite. The interface leaves room for a PKCS#11
  provider for an HSM that supports Ed25519; that provider is not part of
  v0.60.0.
- All instances therefore sign with the same key and `key_id`; `/readyz`
  reports the key id and fingerprint (never the key) so a mismatch across
  instances is visible.
- Every NA signature goes through one `Signer` interface (`sign(payload)`,
  `public_key`, `key_id`) instead of callers holding the `SigningKey`. Today
  routes and services pass `service.na_private_key` to `sign_model` directly;
  this release routes them through the signer. Non-exportable signing is a
  future hardening option: a remote-signing provider (an HSM with Ed25519, or
  a different signature suite) can then be added without changing any caller.

### 6. Health and failover

- `/healthz`: process up. `/readyz`: database reachable and writable (a cheap
  transaction), migrations at the expected version, key loaded, and in HA mode
  the shared rate limiter reachable. An instance failing `/readyz` returns 503.
- Instances are stateless, so a load balancer probe on `/readyz` removes a
  failed instance and the others keep serving. Documented for Azure
  Application Gateway / Load Balancer and for nginx in the reference compose
  setup.
- Graceful shutdown: stop accepting, finish in-flight requests, release
  leases.

### 7. Migration path (SQLite to PostgreSQL)

`genesis-mesh na migrate-db --from sqlite:///var/lib/genesis-mesh/na.db --to
$DATABASE_URL`:

1. refuses unless the target is empty and at the current schema version;
2. opens the source read-only and copies every table in dependency order,
   preserving identifiers, sequences and timestamps;
3. verifies before reporting success: row counts per table, every boundary
   policy's signature and stored digest, CRL sequence continuity, the evidence
   store chains (v0.59.0) and the audit event count;
4. writes a migration report and an audit event on the target.

The runbook covers the downtime window (stop writes, back up SQLite, migrate,
verify, switch `DATABASE_URL`, start instances) and rollback (the SQLite file
is untouched).

### 8. Backup and restore

Documented in `docs/operations/high-availability.md`:

- Azure Database for PostgreSQL Flexible Server with zone-redundant HA,
  automated backups and point-in-time restore; geo-redundant backup for
  disaster recovery; target RPO and RTO stated and tested.
- A restore drill: restore to a new server, run `genesis-mesh na verify-db`
  (the same checks as the migration tool), switch instances over.
- The signing key's Key Vault secret is covered by Key Vault soft delete and
  purge protection; the runbook includes recovering it.

## Security notes

- The database now holds everything an attacker would need to forge state
  except the signing key; access is restricted to the NA's managed identity
  over TLS, with no public network access in the reference setup.
- The signing seed is never written to disk on HA instances; it lives in Key
  Vault and process memory only.
- HA mode refuses a `file` key provider so a deployment cannot quietly copy
  key files between hosts.
- Fail closed: if the database or key is unavailable, the instance reports
  not ready and serves no decisions; it never falls back to local state.

## Tests

- The full existing suite runs twice in CI: on SQLite and on PostgreSQL
  (service container)
- Concurrency suite (section 3) on both backends
- Rate limiting shared across workers and instances
- Key provider: file and Key Vault (mocked) paths; HA mode refusals
- Every NA signature goes through the `Signer`: a test fails if NA code
  outside the key provider uses a `SigningKey` directly
- Migration tool: round trip on a populated SQLite database, verification
  failures detected (tampered policy, broken chain)
- **HA integration** (docker compose: PostgreSQL, two NA instances, nginx):
  decisions, revocations and evidence submitted continuously; instance A is
  killed mid-run; traffic continues through B; afterwards every decision,
  CRL sequence and evidence chain is present exactly once and verifies

## Documentation

- `docs/operations/high-availability.md` (architecture, configuration, load
  balancer, key provider, backup, restore, DR, migration runbook)
- `docs/operations/deployment.md` (link from the default single-VM path)
- `docs/api/trust-http.md` (`/readyz` fields), `docs/stability.md`,
  CHANGELOG, history, phase-j

## Success Criteria

- [x] With no new settings, behaviour is identical to v0.59.0 on SQLite
- [x] `DATABASE_URL` plus `NA_HA_MODE=on` runs the NA on PostgreSQL
- [x] Policies, attestations, revocation, audit and the evidence store behave
      the same on both backends (full suite passes on both)
- [x] Two or more instances serve behind a load balancer with shared data
- [x] Policy activation, CRL and revocation sequences, evidence chains and
      nonces are exactly-once under concurrency
- [x] Rate limits and single-runner jobs are shared, not per instance
- [x] All instances sign with one key from Key Vault
- [x] All NA signing goes through the `Signer` interface, ready for a future
      non-exportable provider
- [x] A failed instance is removed by its readiness probe; the others serve
- [x] Backup, restore and DR documented and drilled for PostgreSQL
- [x] SQLite to PostgreSQL migration documented and verified without loss
- [x] Stopping one instance keeps decisions, revocations and evidence working,
      with no data loss or duplicates

## Release Gate

- [x] Version bumped to `0.60.0`
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass on both backends, plus the HA integration test
- [x] `python scripts/check_release_train.py` passes
- [x] SECURITY.md supported versions updated for the new minor line
- [ ] Tag `v0.60.0`, push, GitHub release created

## Decisions

0. **Implementation notes (v0.60.0).** The PostgreSQL connection keeps the
   sqlite3 calling conventions (``?`` placeholders, ``with conn:``
   transactions, rows by name or index), so the store mixins carry no
   backend branches. Besides ``file`` and ``azure-keyvault``, an ``env`` key
   provider covers platforms whose secret store injects environment
   variables (Kubernetes, Container Apps); HA mode accepts it because the key
   is still never a file. The database must use code-point collation, since
   identifier ordering feeds signed digests.
1. **Non-exportable signing** is not a requirement for this release. It is a
   future hardening option; the `Signer` interface keeps the architecture
   ready for it without blocking HA on it.

## Open questions

1. **Database.** Azure Database for PostgreSQL is the reference. If another
   SQL database (for example Azure SQL) is required, it needs its own backend
   and doubles the test matrix.
2. **Rate-limit store.** The plan uses the database to avoid new
   infrastructure. Redis would scale further; it can be an optional backend
   later.
