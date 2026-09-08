# Rust Trust Gateway

Genesis Mesh has a companion Rust implementation at
[GenesisMeshLabs/gateway](https://github.com/GenesisMeshLabs/gateway). It is a
concurrent trust-verification gateway and API console built on the same portable
trust data model as the Python implementation.

The Rust gateway is an interoperability and deployment surface, not a second
Network Authority. The Python Genesis Mesh implementation remains the protocol
authority for issuing credentials, maintaining authority state, and publishing
signed revocation material. The gateway consumes that material, verifies it
locally, and exposes narrowly scoped services to relying applications.

## Version status

The gateway reached v0.56.0 with production trust policy and portable
Linux/Windows distributions. The current Rust release is v0.57.2. The
interoperability contract is protected by canonical-JSON and signature
fixtures shared with the Python implementation.

The gateway crate requires Rust 1.88 or newer and is published as
`genesis-mesh-gateway`. It contains three binaries:

- `genesis-mesh-gateway`: the HTTP trust gateway and embedded console.
- `genesis-mesh`: local signing and interoperability CLI.
- `genesis-mesh-operator`: operator and authority-management utilities.

## Trust verification

The gateway validates signed Genesis Mesh join certificates using pinned
Ed25519 authority keys, required roles, certificate freshness, and signed CRL
sequence and revocation checks. It supports single and bounded batch
verification:

```http
POST /verify
POST /verify/batch
```

Production callers provide a scoped bearer credential. The gateway supplies the
anchors and revocation state from operator policy; callers cannot replace those
trust inputs. A successful HTTP response does not itself grant trust: callers
must inspect `trusted` and its reason list, then bind the certificate identity
to their own authenticated session and authorization decision.

The gateway also provides `/health`, `/ready`, `/metrics`, `/api`,
`/openapi.json`, and an embedded endpoint explorer. Readiness becomes
unavailable when configured revocation state is stale or durable state is
unhealthy.

## Authority service proxy

The gateway exposes a reviewed, allowlisted proxy for the Network Authority:

```http
GET|POST|DELETE /v1/networks/{network}/services/{operation}
```

The catalog currently contains 59 scoped authority operations across these
areas:

| Area | Capabilities |
| --- | --- |
| Agreement | Offer, counter, accept, and verify |
| Attestations | Issue, list, inspect, verify, revoke, and recognition policy |
| Boundary | Decide and verify |
| Disclosure | Commitment, membership proof, nullifier, and verification |
| Consensus | Vote, assemble proof, and verify against validator keys |
| Data usage | License policies, usage intents, and verification |
| Evidence | Build and verify signed trust evidence |
| Enrollment | Invite, join, heartbeat, renew, and certificate revocation |
| Discovery | Signed agent registration, lookup, listing, and deregistration |
| Treaties | Issue, inspect, verify, revoke, import feeds, and trust paths |
| Network | Genesis, policy, CRL, health, dashboard, atlas, and node roster |
| Administration | Policy versions, rollback, and operator-key revocation |

Clients receive explicit network and service-group permissions. Administrative
operations additionally require the four `X-Admin-*` headers signed by an
operator key. Browser signing is available in the console; private seeds stay
in the browser session and are never sent to the gateway.

The proxy forwards only catalogued methods, paths, parameters, and JSON bodies.
It does not forward gateway bearer tokens, cookies, client URLs, or arbitrary
headers to an authority. This boundary prevents a gateway credential from
becoming an authority credential.

## Federation and live mesh

Native federation preflight and independent authority operations were added in
v0.56.3. A network can pin additional CRL issuers, each with its own anchors,
sequence floor, freshness policy, and optional refresh URL. Issuers are
verified independently; the gateway does not merge signed CRLs or treat
membership feeds as join revocation lists.

The console can optionally publish a read-only live mesh view at `/v1/mesh`.
Publication is disabled by default and is enabled per network with
`public_mesh: true`. The view contains only explicitly published signed
memberships, active recognition treaties, and approved trust domains. It does
not expose private gateway policy or credentials.

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
replicas. The gateway never accepts or stores authority private signing keys.

## Distribution and operations

The gateway is distributed as:

- Multi-architecture OCI images for Linux AMD64 and ARM64.
- Checksummed native binary bundles for Linux and Windows.
- CI artifacts with SBOM and provenance metadata.

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
cargo test --locked
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
