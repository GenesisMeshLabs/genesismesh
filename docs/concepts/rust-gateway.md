# Rust Trust Gateway

Genesis Mesh has a companion Rust service at
[GenesisMeshLabs/gateway](https://github.com/GenesisMeshLabs/gateway). It is a
concurrent trust-verification gateway and API console built on the same portable
trust data model as the Python implementation.

The Rust gateway is an interoperability and deployment surface, not a second
Network Authority. The Python Genesis Mesh implementation remains the protocol
authority for issuing credentials, maintaining authority state, and publishing
signed revocation material. The gateway consumes that material, verifies it
locally, and exposes narrowly scoped services to relying applications.

## Version status

The gateway ships with each Genesis Mesh release, at the same version (1.8.1
today). It is beta: see the {doc}`../reference/public-contract`. The
interoperability contract is protected by canonical-JSON and signature
fixtures shared with the Python implementation.

The gateway crate, `genesis-mesh-gateway`, requires Rust 1.88 or newer. It is
not on crates.io; it ships as a container image and release binaries (see
[Distribution and operations](#distribution-and-operations)). It contains
three binaries:

- `genesis-mesh-gateway`: the HTTP trust gateway and embedded console.
- `genesis-mesh`: local signing and interoperability CLI.
- `genesis-mesh-operator`: read-only preflight of a peer authority, which
  writes a policy fragment for the gateway. It holds no signing key.

## Trust verification

The gateway validates signed Genesis Mesh join certificates using pinned
Ed25519 authority keys, required roles, certificate freshness, and signed CRL
sequence and revocation checks. It supports single and bounded batch
verification:

```text
POST /verify
POST /verify/batch
```

Production callers provide a scoped bearer credential. The gateway supplies the
anchors and revocation state from operator policy; callers cannot replace those
trust inputs. A successful HTTP response does not itself grant trust: callers
must inspect `trusted` and its reason list, then bind the certificate identity
to their own authenticated session and authorization decision.

The gateway also serves:

| Route | Access |
| --- | --- |
| `/` | The embedded console and endpoint explorer |
| `/api`, `/openapi.json` | Public service metadata and the OpenAPI document |
| `/health`, `/ready` | Liveness and trust readiness |
| `/v1/services` | The public operation catalog with request examples |
| `/v1/networks` | The networks the calling client may use |
| `/v1/demo` | Public demo access (read and verify only), when configured |
| `/v1/mesh` | The read-only live mesh view, when published (below) |
| `/metrics` | A bearer token with the metrics permission |

`/ready` answers `503` when a configured network's CRL has expired, when the
durable state store has failed a write, or when the shared quota backend is
unreachable.

## Authority service proxy

The gateway exposes a reviewed, allowlisted proxy for the Network Authority:

```text
GET|POST|DELETE /v1/networks/{network}/services/{operation}
```

The catalog lists about 110 authority operations, in service groups; the
gateway's
[service catalog](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/services.md)
lists each one. A client is given networks and service groups, so the group an
operation sits in decides who can reach it:

| Area (group) | Workflows |
| --- | --- |
| Agreement (`agreement`) | Offer, counter, accept and verify |
| Attestations (`attestations`) | Issue, list, inspect, verify, revoke, the sovereign revocation feed and recognition policy |
| Boundary (`boundary`) | Decide and verify |
| Boundary policy (`boundary_policy`) | Validate, publish, list, activate, deactivate, history and verify policies; policy-aware evaluation |
| Evidence store (`evidence_store`) | Submit executor-signed evidence, search, status, verify, resource heads and histories, vendor histories, JSON Lines export, executor keys, retention and store anchors (list, anchor now); remediation records, the due queue, notices and reviews (1.4.0); archives and retention through an archived position (1.5.0); pre-issued grants, a grant's use chain, time tokens, grant uses and revocation (1.6.0) |
| Changes outside the controlled path (`out_of_band`) | Observations (one or a batch) and break-glass records, judging them, a resource's changes with how each was governed, operator key holders and holder changes (1.3.0) |
| Disclosure (`disclosure`) | Commitment, membership proof, nullifier and verification |
| Consensus (`consensus`) | Vote, assemble proof and verify against explicit validator keys |
| Data usage (`data_usage`) | License policies, usage intents and verification |
| Evidence (`evidence`) | Build and verify signed trust evidence |
| Enrollment (`enrollment`) | Join, heartbeat and renew |
| Discovery (`discovery`) | Signed agent registration, lookup, listing and deregistration |
| Treaties (`treaties`) | Issue, inspect, verify, revoke, import revocation feeds, the recognition graph and trust paths |
| Network (`network`) | Genesis, policy, CRL, health, readiness, sovereign metadata, dashboard, atlas, node roster, the NA key history (1.5.0) and edge nodes (1.7.0) |
| Administration (`administration`) | Invites, certificate revocation, policy publication, versions and rollback, operator-key revocation and NA key succession (1.5.0) |

The audit pack route is not forwarded: build packs against the authority with
`genesis-mesh audit pack` (see {doc}`../operations/audit-packs`).

Forwarding an operator operation needs the client's administrative permission
and the four `X-Admin-*` headers signed by an operator key; the authority then
checks the key's tier. Browser signing is available in the console; private
seeds stay in the browser session and are never sent to the gateway.

The proxy forwards only catalogued methods, paths, parameters, and JSON bodies.
Resource identifiers may span path segments (`kv:vault/secret`) and carry
non-ASCII text; each segment is encoded once, and dot segments, `%`, `\` and
control characters are refused. The evidence export is forwarded as JSON Lines
(`application/x-ndjson`) within 8 MiB. Issuing, listing and reading grants, a
resource's changes, the remediation due queue and one subject's remediation
state may answer up to 8 MiB of JSON. Every other response must be JSON within
2 MiB. The gateway's CI regenerates the catalog from the core and fails when
they differ.
It does not forward gateway bearer tokens, cookies, client URLs, or arbitrary
headers to an authority. This boundary prevents a gateway credential from
becoming an authority credential.

## Federation and live mesh

Native federation preflight was added in v0.56.3. A network can pin additional CRL issuers, each with its own anchors,
sequence floor, freshness policy, and optional refresh URL. Issuers are
verified separately; the gateway does not merge signed CRLs or treat
membership feeds as join revocation lists.

The gateway checks certificates and CRLs with the authority keys pinned in its
policy (`anchors`). It does not follow an authority's key history. From a
succession's `effective_at` it refuses the authority's CRL, whose `issuer` is
now the new key (1.8.0), and certificates the new key signs; once the old
key's last CRL expires the network, and with it `/ready`, goes not ready. Its
operator re-pins the network to the new key after `effective_at` and before
that expiry: the new key as the network's anchor and the CRL the new key
signed as its starting CRL. An authority before 1.8.0 kept the old key ID as
the CRL's `issuer`, so no re-pin matched it. Plan a succession with the
gateway's key-succession runbook (`docs/key-succession.md` in the gateway
repository) and {doc}`../operations/key-succession`.

The console can optionally publish a read-only live mesh view at `/v1/mesh`.
Publication is disabled by default and is enabled per network with
`public_mesh: true`. The view contains only explicitly published signed
memberships, active recognition treaties, and approved trust domains. It does
not expose private gateway policy, credentials or edge nodes. To show a
network's members, the gateway can hold a `read`-tier operator key for that
authority (`mesh_reader`).

## Durable production controls

The gateway includes configurable adapters for:

- SQLite durable per-issuer CRL checkpoints with sequence rollback and
  conflicting same-sequence updates rejected.
- A durable SQLite audit outbox that records request intent and completion,
  with at-least-once delivery to a pinned HTTPS collector and stable event IDs.
- Pinned OIDC issuer, audience, JWKS, subject bindings, and required claims.
- Native mutual TLS using an approved client CA. mTLS is an additional listener
  control and does not replace application authorization.
- Redis-backed atomic request quotas shared by replicas.
- JSON audit logging, request correlation, Prometheus metrics, readiness probes,
  bounded request bodies, deadlines, and cancellation-safe worker limits.

These controls are opt-in deployment adapters. Their presence does not claim
certification, accreditation, compliance, or linearizable revocation across
replicas.

The gateway holds no Network Authority signing key. With `mesh_reader`, it
holds one `read`-tier operator key per published network, which can read the
attestation list and node roster and nothing else.

## Distribution and operations

The gateway is distributed as:

- A signed multi-architecture image for Linux AMD64 and ARM64,
  `ghcr.io/genesismeshlabs/genesis-mesh-gateway`, with SBOM and provenance
  (see [Container Images](../operations/container-images.md)).
- The same image as a signed OCI archive on each GitHub release.
- Signed, checksummed native binary bundles for Linux and Windows.

The runtime image is non-root and read-only with constrained resources. Policy,
keys, tokens, CRLs, and other deployment secrets remain external to the image.
Use `--check-config` before rollout and initialize durable state explicitly with
`--init-state` when persistent state is enabled.

For deployment details, recovery semantics, policy examples, and rollout
boundaries, see the gateway repository's [operations guide](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/operations.md),
[platform controls](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/platform.md),
[service catalog](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/services.md),
[distribution guide](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/distribution.md),
and [mesh operations](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/mesh.md).

## Build and verify

From the gateway repository:

```bash
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
cargo test --locked --doc
node --test tools/test_ui_*.mjs
cargo build --locked --release --bin genesis-mesh-gateway
```

Interoperability work should also run the Python conformance suite and the
Rust `tests/interop.rs` fixtures. Changes to canonical serialization,
signatures, certificates, CRLs, or trust decisions are protocol changes and
must preserve compatibility in both implementations.

## Scope boundary

The Rust gateway does not replace the Network Authority, issue sovereign
credentials in production, prove possession of a node private key, or
authorize arbitrary application actions. Relying services remain responsible
for session authentication, resource authorization, privacy controls, ingress
TLS, and operational incident response.
