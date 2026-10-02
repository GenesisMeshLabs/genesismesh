# Compatibility and Deprecation Policy

## Scope

This policy covers every surface classified **stable** in the public
contract (`contract/public-surface.json`, rendered as
`docs/reference/public-contract.md`): HTTP routes, CLI commands, Python
symbols, signed artifacts and API error codes, plus the canonical signing
bytes, the evidence export schema, conformance vectors, configuration and
persisted database state described below.

**Beta** surfaces may change in a minor version with a CHANGELOG notice.
**Internal** surfaces, and anything not listed in the contract, carry no
guarantee. `genesis_mesh/tests/test_public_contract.py` fails when the code
and the contract disagree, so a change to a listed surface is always a
deliberate, reviewed change to the contract.

Within one major version (1.x), a stable surface is never removed or changed
incompatibly without the deprecation cycle below. Security fixes are the
exception (see *What is not covered*).

## Deprecation cycle

1. **Announce**: the surface is marked deprecated in the CHANGELOG and in its
   docstring, help text or API reference. Python symbols emit a
   `DeprecationWarning`; CLI flags print a visible warning; deprecated HTTP
   routes and fields are listed in the release notes.
2. **Maintenance window**: the surface keeps working for at least one minor
   version after the announcement (deprecated in 1.2.0, removed no earlier
   than 1.3.0). A stable **HTTP route, signed artifact field or error code**
   is never removed within 1.x: it can only be deprecated, and removed in the
   next major version.
3. **Removal**: listed in the CHANGELOG under "Removed".

## Python API and CLI

- Adding an optional keyword argument, or a model field with a default, is
  not breaking.
- Renaming, removing or reordering a positional parameter, making an
  optional parameter required, or changing a return type is breaking.
- CLI commands and flags follow the same rules. Output requested with
  `--format json` is a stable structure (fields may be added); human-readable
  output is not.

## HTTP routes

- **Requests.** A new request field is always optional. A field that becomes
  required, is removed or changes type is breaking. Clients send only
  documented fields: where a model forbids unknown fields (boundary policies,
  evidence-store records), the NA rejects them.
- **Responses.** Fields may be added at any time; **clients must ignore
  fields they do not know**. A stable response field is not removed, renamed
  or retyped within 1.x.
- **Status codes and error codes.** The HTTP status of a given failure, and
  its `error.code`, are stable. A code is never removed or given a new
  meaning; new codes may be added for new failures. `error.message` and
  `error.details` are for people and may change.
- **Authentication.** The admin signature scheme (`X-Admin-*` headers over
  the canonical `{body, key_id, timestamp, nonce}`) is stable.

## Canonical signing bytes

The bytes that are signed and hashed are defined in RFC-001, *Canonical JSON
and signatures*, and tested by the `interop` conformance vectors. They do not
change within a major version.

## Signed artifacts

A verifier parses a signed artifact into its model and recomputes the
canonical form. **A field the verifier does not know is dropped, so the
signature no longer verifies**: an artifact from a newer signer fails closed
on an older verifier; it is never accepted with the new field ignored.
Therefore, within 1.x:

1. A new field in a stable signed artifact is optional and **omitted from the
   canonical form when absent** (as `ExecutionEvidence.resource_id` and
   `BoundaryDecision.policy_binding` are). Artifacts without it verify on
   every 1.x verifier.
2. A signer emits the new field only once every verifier that must accept the
   artifact understands it. The release notes state the first version that
   reads it; mixed fleets upgrade verifiers first.
3. Existing fields are never removed, renamed, retyped or given a new meaning.
4. **Old artifacts stay verifiable**: an artifact signed by 0.59.0 or any
   later release verifies on every later 1.x release. Earlier artifacts are
   not covered. The upgrade rehearsal (`scripts/upgrade_rehearsal.py`) checks
   this against real databases written by 0.59.1, 0.60.0, 0.61.1 and 0.62.0.

Beta signed artifacts may change in a minor version; the CHANGELOG says how
artifacts from the previous version are handled.

## Evidence export schema

The export event envelope (`gm.evidence.event`, `schema_version` 1) is
stable. Readers reject a schema version they do not know. A new schema
version is introduced alongside the old one, and the NA keeps producing
version 1 throughout 1.x.

## Conformance vectors

Vector files in `conformance/vectors/` are append-only within 1.x: new
vectors may be added; an expected output changes only to correct a vector
that was itself wrong, and that change is announced in the CHANGELOG. The
SDKs carry byte-identical copies, which CI checks.

## Configuration

Environment variables and configuration keys documented in
`docs/reference/configuration.md` are stable. Unset values keep the previous
behaviour.

## Persisted database state

- **Upgrades** from the latest patch of each minor version from 0.59 on are
  supported and tested. The NA applies pending migrations on start (once,
  under a database lock with several instances) and keeps existing records
  valid: treaties, revocations, policies, evidence and their signatures.
- **Migrations are forward-only.** A release refuses to start on a database
  migrated by a newer release (`NewerSchemaError`). **Rollback means
  restoring the backup taken before the upgrade**; records written after the
  upgrade are lost unless exported first. See `docs/operations/upgrade.md`.
- SQLite to PostgreSQL migration (`genesis-mesh na migrate-db`) is supported
  for databases at the current schema.

## What is not covered

- Beta and internal surfaces, and anything not listed in the contract.
- Bug fixes that change previously incorrect behaviour, even if callers relied
  on it.
- Security fixes. These may change or remove behaviour immediately when
  keeping it would leave a known vulnerability in place; the CHANGELOG and
  the release notes say so.
- The Tamarin models in `ops/tamarin/`: they prove design properties, not
  compatibility between versions.
