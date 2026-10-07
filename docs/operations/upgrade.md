# Upgrade and Rollback

How to upgrade a Network Authority, and what a rollback can and cannot do.
The compatibility promise behind this procedure is in `DEPRECATION_POLICY.md`
(*Persisted database state* and *Signed artifacts*).

## Supported upgrade paths

Upgrades from the latest patch of each minor version from 0.59 on are
supported. CI rehearses each of them on every change
(`.github/workflows/upgrade.yml`, `scripts/upgrade_rehearsal.py`): a database
written by the past release, with a recognition treaty, partner attestations,
an imported revocation feed, a revoked NA attestation, an active boundary
policy, policy-bound decisions and a resource's execution chain, is upgraded
and every record is verified again. The same database is restored from backup
and verified, and migrated to PostgreSQL and verified.

| From | Status |
| --- | --- |
| 1.0.x | Supported and rehearsed in CI. Read *Upgrading to 1.1* below first, and *Upgrading to 1.0.2* when coming from 1.0.0 or 1.0.1 |
| 0.65.x, 0.64.x, 0.63.x, 0.62.x, 0.61.x, 0.60.x, 0.59.x | Supported and rehearsed in CI |
| 0.58.x and earlier | Not supported: upgrade to 0.59.1 first, or start fresh |

```{note}
Wheels published to PyPI before **v0.62.0** do not contain the database
migration files, so a Network Authority installed from them with `pip`
starts without its tables and fails on every admin request. Source
deployments and the container image were not affected. Install 0.62.0 or
later from PyPI; CI now runs a full Network Authority workload from the
built wheel before every release.
```

## Procedure

1. **Back up first.** Take an online backup (`genesis-mesh managed backup`,
   see {doc}`backup-restore`) or, on PostgreSQL, a `pg_dump`. Keep it until the
   upgrade is verified. Export the evidence store if you need records written
   after the upgrade to survive a rollback (`GET /admin/evidence/export`).
2. **Read the release notes** for signed artifact fields the new version
   emits (see *Mixed versions* below).
3. **Stop, upgrade, start.** The NA applies pending migrations on start. With
   several instances on PostgreSQL, upgrade one instance at a time: the first
   to start applies the migrations under a database lock; instances still on
   the old version report not ready on `/readyz` once the schema has moved,
   so the load balancer drains them until they are upgraded.
4. **Verify.** `genesis-mesh na verify-db` checks schema version, boundary
   policy digests, CRL continuity and the evidence chain. `/readyz` must
   report the expected schema version.

## Upgrading to 1.1

1.1 adds no database migration: the schema version stays the same, so a
1.1 Network Authority can be rolled back to 1.0.2 on the same database (see
*Rollback*). Admin signature version 2 arrived in 1.0.2: coming from 1.0.0
or 1.0.1, read *Upgrading to 1.0.2* first: 1.1 accepts only version 2 and no
longer has `NA_ADMIN_LEGACY_SIGNATURES`, so its client migration window must
be finished, or older clients upgraded together with the Network Authority.
What needs planning in 1.1 is the container image and the admin rate limits.

### Admin rate limits

Two rate-limit changes apply on upgrade:

- **The admin limit rises from 30 to 300** requests per minute per client
  address. A deployment that set `NA_RATE_LIMIT_ADMIN_PER_MINUTE` keeps its
  value. To keep the old limit, set it to `30`.
- **Failed admin authentications are limited to 30 per minute** per client
  address (`NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE`). After that, the
  address's admin requests get `429 admin_auth_throttled` for the rest of the
  minute, valid ones included, and the audit log records one
  `admin_auth_throttled` event instead of one `admin_auth_failed` per request.
  A client that retries a misconfigured key in a loop now locks its own
  address out for a minute: fix the key rather than raising the limit.

Every `429` now carries `Retry-After: 60`.

### Container image: hand the data volume to the new user

The 1.1 image (`ghcr.io/genesismeshlabs/genesis-mesh`) runs as user 10001 in
`/data`. Images built from the 1.0 Dockerfile ran as a system user (uid 100)
in `/app`, so:

- **Relative paths move.** `GENESIS_FILE`, `NA_PRIVATE_KEY_FILE` and `DB_PATH`
  default to files in the working directory, now `/data`. Mount the database
  volume at `/data`, or set `DB_PATH` to where it is mounted.
- **The volume must be writable by uid 10001.** The image refuses to start
  otherwise:

  ```text
  ERROR: database /data/genesis_mesh_na.db is not writable by uid 10001. Give
  the data volume to this user (for example chown -R 10001:0 and chmod -R
  g+rwX on the volume). Refusing to start.
  ```

  With the Network Authority stopped and the backup taken, hand the volume
  over once, to user 10001 and group 0 as the image lays out `/data`:

  ```bash
  docker run --rm --user 0 --entrypoint sh -v na-data:/data \
    ghcr.io/genesismeshlabs/genesis-mesh:1.1.0 \
    -c 'chown -R 10001:0 /data && chmod -R u+rwX,g+rwX,o-rwx /data && chmod g+s /data'
  ```

- **Mounted secrets must be readable by uid 10001** (or group 0), for
  example a key file mounted read-only from the host.

See [Container Images](container-images.md) for the full runtime contract.

## Upgrading to 1.0.2

1.0.2 adds no database migration: the schema version stays the same, so a
1.0.2 Network Authority can be rolled back to 1.0.1 on the same database (see
*Rollback*). The admin signature change needs planning.

### Admin signatures: Network Authorities first, then clients

1.0.2 signs and verifies admin requests with signature version 2, which binds
each signature to the HTTP method, path, query and target Network Authority
(see the [Network Authority API](../reference/network-authority-api.md)).
A 1.0.2 Network Authority refuses version 1 signatures from 1.0.1 clients, and
a 1.0.1 Network Authority refuses version 2 signatures from 1.0.2 clients.
Upgrade in this order:

1. Upgrade the Network Authority with `NA_ADMIN_LEGACY_SIGNATURES=accept`.
   1.0.1 clients keep working, and each version 1 request is logged and
   audited as `admin_legacy_signature_accepted`.
2. Upgrade every admin client: the `genesis-mesh` CLI and the scripts that
   call it, applications using the TypeScript, Go, .NET or Rust SDK, and the
   gateway, whose console signs in the browser.
3. When the audit log shows no `admin_legacy_signature_accepted` events for
   a full cycle of your automation, remove the setting and restart.

Public routes (verification, metadata, feeds) are unchanged, so other
sovereigns do not need to upgrade at the same time. Two answers do change for
them: a Network Authority now reports a treaty that names
it as issuer as accepted only when it holds that treaty, and refuses any other
key supplied for such a treaty (`422 caller_keys_not_accepted`).

### The attestation list goes to operators

An unsigned `GET /attestations` now returns only the count, as `GET /nodes`
does. A dashboard or member directory that read the list without a signature
needs an operator key of the new `read` tier, which opens only the operator
views of `/nodes` and `/attestations`: add the key to
`OPERATOR_PUBLIC_KEYS_JSON` and `"<key-id>": "read"` to
`OPERATOR_KEY_TIERS_JSON`, and sign its reads. The gateway's mesh view does
this with its `mesh_reader` setting.

## Rollback

**Migrations are forward-only.** A release refuses to start on a database
migrated by a newer release:

```text
NewerSchemaError: database schema version 14 is newer than this release
supports (13); upgrade Genesis Mesh, or restore the backup taken before the
upgrade
```

So a rollback is: stop the NA, restore the backup taken in step 1, start the
previous version. Everything written after the upgrade (decisions,
revocations, evidence) is lost unless exported first. Revocations issued
after the upgrade **must be re-issued** on the restored version: losing a
revocation silently re-trusts the subject.

When an upgrade adds no migration (`/readyz` shows the same schema version
before and after), the previous binary can be started on the same database
without a restore. This is the case from 1.1 back to 1.0.2, and from 1.0.2
back to 1.0.1. 1.0.1 accepts only version 1 admin signatures and ignores
`NA_ADMIN_LEGACY_SIGNATURES`, so return the admin clients to 1.0.1 as well. A container is rolled back by
running the image it ran before (by digest when it came from a registry). A
volume handed to uid 10001 goes back to the 1.0 image's user with that
image's own `chown`:

```bash
docker run --rm --user 0 --entrypoint chown -v na-data:/data \
  <the 1.0 image> -R genesis:genesis /data
```

## Mixed versions

Within 1.x, an artifact signed by an older release verifies on a newer one.
The reverse is not guaranteed: a newer release may sign an artifact field an
older verifier does not know, and the older verifier then rejects the
signature (fail closed). Upgrade verifiers (other sovereigns, SDK clients)
before signers start emitting a new field; the release notes say when one is
introduced.
