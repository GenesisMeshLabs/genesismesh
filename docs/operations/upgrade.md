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
| 1.1.x | Supported and rehearsed in CI. Read *Upgrading to 1.1.1* below first |
| 1.0.x | Supported and rehearsed in CI. Read *Upgrading to 1.1.1* and *Upgrading to 1.1* below first, and *Upgrading to 1.0.2* when coming from 1.0.0 or 1.0.1 |
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

## Upgrading to 1.3 (unreleased)

1.3 adds migration 015. On SQLite it rebuilds the evidence table (to accept
the new entry kinds), so allow for one copy of the table on disk; on
PostgreSQL the table is altered in place. Entries, their digests and the
anchors are unchanged, and `genesis-mesh na verify-db` verifies them after
the upgrade. A 1.3 database cannot be opened by 1.2: roll back by restoring
the backup taken before the upgrade.

At its first start on 1.3 the NA:

- backfills the store's registry from the audit events (policy activations
  and deactivations, executor keys), marked `reconstructed`, and records how
  far back its policy history reaches; changes before that are judged
  `indeterminate`;
- records which holder each configured operator key belongs to, from
  `OPERATOR_KEY_HOLDERS_JSON` (a key without an entry is its own holder). Set
  it before that start: afterwards a holder changes only with a second
  holder's approval.

Controllers that want their changes matched to observations report the
version they produced as `execution_parameters.version_id`. See
{doc}`out-of-band-changes`.

## Upgrading to 1.2 (unreleased)

1.2 adds migration 014, the `evidence_anchors` table, so a 1.2 database cannot
be opened by 1.1: roll back by restoring the backup taken before the upgrade
(see *Rollback*). Once anchors have been copied out, such a rollback is an
evidence-loss event for their holders; follow *After a restore* in
{doc}`evidence-anchors`.

Right after upgrading, anchor the store and take the first copy
(`genesis-mesh evidence anchors fetch --anchor-now`): history stored before
1.2 is covered from that first copied anchor on, as it stands then. Then set
up the copy schedule described in {doc}`evidence-anchors`.

Two request-handling changes apply on upgrade:

- **Failed admin authentications count per address and key.** A failure that
  names an active operator key counts against that key at the client
  address, and throttles only that key. A failure that names no active key
  (none, an unknown or a revoked one) counts against the address and
  throttles only requests that name no active key. Behind a gateway or NAT,
  one operator's failures, or a mistyped key ID, no longer lock out the
  others. All failures from one address are capped at four times the limit
  (`NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE`, unchanged).
- **Advertised URLs.** `/sovereign.json` and `/swagger.json` take their
  scheme and host from `X-Forwarded-Proto` and `X-Forwarded-Host` only when
  they come from a trusted proxy. An NA that sets `NA_PROXY_HOPS=0` behind a
  proxy now advertises the scheme and host the proxy forwards it (`http`
  rather than `https` behind a TLS-terminating proxy). Set `NA_PUBLIC_URL` to
  the NA's public origin, which these documents then always advertise, and
  have nginx overwrite `X-Forwarded-Host`
  (`proxy_set_header X-Forwarded-Host $host;`, as in
  {doc}`vm-bootstrap`). SDKs read only the NA's public key from
  `/sovereign.json`, so they are not affected.

### Strict input and canonical records

- The Network Authority reads every JSON request body strictly: a duplicate
  key, `NaN` or `Infinity`, a number that overflows a float, an integer below
  `-2**63` or above `2**64 - 1`, the integer `-0`, a lone surrogate, arrays
  or objects nested more than 64 deep, or a body that is not UTF-8 is
  refused with `400 invalid_json`, the reason in `error.details.reason`. A
  UTF-8 byte order mark is still accepted; a UTF-16 or UTF-32 body, which
  Flask accepted before, is not. A client that sent such values (a boundary
  policy selector of `10**400`, say) must change them.
- Go's `encoding/json` and .NET's `System.Text.Json` write the float `-0.0`
  as `-0`, which is now refused as `negative_zero`. A Go or .NET client that
  can send a negative zero (a computed metadata value, say) must send `0`
  instead. The SDKs never write one in the records they build.
- Verifiers refuse a record signed over a form the reference does not write
  as `non_canonical_form`, and a record received in a form its signature does
  not cover as `invalid_signature`. Records the Network Authority signs are
  always in canonical form; a client that rewrites timestamps (`Z` to
  `+00:00`) before passing a record on breaks it. The routes that take an
  agreement (`/admin/boundary/evaluate`, `/admin/boundary/decide`,
  `/admin/disclosure/commit`) check it as received too, and refuse one
  that fails with `422 agreement_untrusted`. See
  {doc}`../reference/canonical-form`.

## Upgrading to 1.1.1

1.1.1 adds no database migration and can be rolled back to 1.1.0 on the same
database. Its security fixes refuse some requests that 1.1.0 accepted.

### Agreements: register both parties

The Network Authority now decides (`/admin/boundary/evaluate`,
`/admin/boundary/decide`) and commits (`/admin/disclosure/commit`) under an
agreement only if two different parties signed it with keys it trusts: its own
key for its own sovereign, and for any other sovereign the keys of an active
recognition treaty the NA issued to it that grants at least one role. The NA's
key never vouches for another sovereign, a sovereign cannot agree with itself,
and one key cannot sign for both parties. An agreement the NA offered and
accepted itself (`/admin/agreements/accept`, privileged) stays trusted when
its responder holds such a treaty.

Decisions under an attestation (`attestation_id`) are not affected: a Network
Authority that only decides under attestations needs nothing.

Before upgrading one that decides under agreements its parties signed, list
the sovereigns that sign them and issue each a treaty with the key it signs
with (`POST /admin/recognition-treaties`, privileged tier):

```json
{ "subject_sovereign_id": "bank-a",
  "subject_public_keys": ["<bank-a's agreement signing key>"],
  "scope": { "allowed_roles": ["role:client"] },
  "validity_hours": 8760 }
```

A treaty that expires or is revoked stops vouching for its sovereign: renew
treaties before they expire. Revoking the treaty is also the only way to stop
the NA deciding under that sovereign's agreements. A request under an
agreement the NA does not trust gets `422 agreement_untrusted` with
`details.reason` (`unknown_party`, `same_party`, `overlapping_party_keys`, or
the reason `verify_agreement` gives) and `details.party` when one party is at
fault; each refusal is audited as `agreement_untrusted`.

A treaty that names the NA's own key for another sovereign no longer vouches
for it. If an older setup did that to make NA-signed agreements usable, issue
the treaty with the sovereign's own key instead; agreements the NA offered and
accepted itself stay trusted.

### Countering an offer needs a privileged key

`POST /admin/agreements/counter` requires the privileged tier. A standard key
gets `403 insufficient_operator_tier`. Offers still accept a standard key.

### Requests may not name other parties

Under an agreement, the requester is the agreement's responder and the
provider its offerer. A context that names another `requester_sovereign_id`
or `provider_sovereign_id` gets `400 context_party_mismatch`; naming the
agreement's own parties, or neither, still works. Under an attestation a
supplied `provider_sovereign_id` must be this NA's sovereign.

### Execution evidence must be exactly its signed form

`POST /evidence/execution` refuses a record that is not exactly its
serialized form, for example one with an unsigned extra field, a number sent
as a string, or a timestamp that is not UTC, with `422 evidence_malformed`
naming the difference. The TypeScript and Rust SDKs and the Python reference
produce exact records; a client that builds records by hand must send the
fields it signed, with their types. Records already in the store are not
affected.

### Consensus proofs

`POST /admin/consensus/vote` and `POST /admin/consensus/proof` accept only
justification proofs this NA signed (`422 justification_untrusted`), and
`required_threshold` must be an integer from 1 to the number of distinct
validators (`400 invalid_threshold`).

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
