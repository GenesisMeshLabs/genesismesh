# Public API Stability

Genesis Mesh classifies every public surface as **stable**, **beta** or
**internal**. Since v0.62.0 the classification is the machine-checked
{doc}`reference/public-contract`: every HTTP route of the Network Authority,
every CLI command, the public Python API with its exact signatures, every
signed artifact and every API error code. The source of truth is
`contract/public-surface.json`, and `genesis_mesh/tests/test_public_contract.py`
fails when the code and the contract disagree.

Earlier versions of this page listed stable symbols by hand. That list had
drifted from the code (it named CLI commands that no longer exist and
documented `verify_agreement` and `sign_model` with the wrong parameters), so
it was replaced by the generated contract.

## Stability levels

| Level | Meaning |
|-------|---------|
| **stable** | Will not break within 1.x. Removed or changed incompatibly only after the deprecation cycle in `DEPRECATION_POLICY.md`. |
| **beta** | Shipped and supported; may change in a minor version with a CHANGELOG notice. |
| **internal** | No compatibility promise. May change or disappear in any release. |

Symbols not listed in the contract are internal.

## What compatibility means for each surface

`DEPRECATION_POLICY.md` at the repository root defines it for Python symbols,
CLI commands, HTTP requests and responses, error codes, canonical signing
bytes, signed artifact formats, the evidence export schema, conformance
vectors and persisted database state.

## Conformance vectors

The reference implementation produces deterministic output for every stable
signed artifact. Vector files live in `conformance/vectors/` and are run by
`python conformance/runner.py`. The TypeScript, Go and .NET SDKs run the
`interop`, `consensus`, `admin_auth`, `field_registry` and `canonical` suites
in their own tests, and the Rust SDK the `admin_auth`, `field_registry` and
`canonical` suites; the TypeScript and Rust SDKs, which verify evidence
exports, also run the `out_of_band` suite (1.3.0), the `remediation`
suite (1.4.0), the `audit` suite (1.5.0: key histories, records across an
NA key succession, audit packs and the completeness check) and the `grants`
suite (1.6.0: grant records, envelopes, the use rules and stores holding
grants; its issuance vectors are the NA's, which an SDK may skip). The Rust
SDK also runs the `node` suite (1.7.0: node request signatures, the edge
join's executor co-signature, join certificates and CRLs). The
interoperability workflow checks that every copy matches the reference's.

## Audit packs and the NA key history

The audit pack format (`gm.audit.pack` version 1,
{doc}`reference/audit-pack-format`), the signed forms of
`KeySuccessionRecord`, `ArchiveRecord` and `AuditPackManifest`, and the
verification reason codes are stable from 1.5.0: packs sit in archives for
years, and a pack written by 1.5.0 verifies with every later release. The
frozen 1.5.0 pack (`conformance/fixtures/audit-pack-1.5.0`) is verified by
every release's tests. The routes and commands that write packs, archives and
successions are beta; the Stage 2 and 3 routes (observations, break-glass,
judgements, holders, remediations and reviews) are stable from 1.5.0.
`scripts/export_reference_corpus.py --suite verification` writes the corpus a
second verifier runs.

## Pre-issued grants

The signed forms of `CapabilityGrant`, `GrantExecutionEvidence`,
`GrantRevocationRecord` and `TimeToken`, and the grant reason codes, are
stable from 1.6.0: grants and their uses sit in audit packs for years. The
grant routes (`/admin/grants`, `/grants/time-tokens`,
`/evidence/grant-executions`) and `TimeTokenRequest` are beta, as is the
rule every SDK acting under a grant follows (fall back to break-glass when the
grant has ended, is spent or revoked and the NA cannot be reached). See
{doc}`operations/grants`.

## Edge agent

The edge agent (`genesis-mesh-edge`, released with the Rust SDK, and its
image `ghcr.io/genesismeshlabs/genesis-mesh-edge`, tagged `X.Y.Z` only) is
beta from 1.7.0: its configuration, local API, state directory and exit codes
may change in a minor release. So are the routes it calls
(`/node/boundary/evaluate`, `/node/state`, `/node/evidence/resource-head`),
`GET /admin/edge-nodes`, `genesis-mesh admin edge-nodes`, the node request
fields `purpose` and `audience`, and `genesis_mesh.crypto.node_auth`.
`/join`, `/heartbeat`, `/renew`, `/admin/invite` and `/admin/revoke` stay
stable; their edge additions (the edge invite fields, the executor key at
`/join`, the `edge` block of `/join` and `/renew`, the heartbeat's `agent`
block and `/admin/revoke`'s `edge_node` block) are beta. The error codes they
add are stable, as every error code is. No signed record changes. See
{doc}`operations/edge-agent`.

Alternative implementations must pass all vectors to claim conformance.
See `conformance/CONFORMANCE.md` for instructions.
