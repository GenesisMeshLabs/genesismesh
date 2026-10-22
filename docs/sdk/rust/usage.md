# Gateway: modules and CLI

> **Beta** · Crate: `genesis-mesh-gateway` 1.7.0 · Source: [`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway)

This page covers the gateway crate ({doc}`gateway`), not the Rust SDK.

## Module map

| Module | Purpose |
| --- | --- |
| `genesis_mesh::crypto` | Ed25519 identities: `KeyPair`, `CachedPublicKey`, detached signing and verification. |
| `genesis_mesh::canonical` | Canonical JSON byte-compatible with Python's `json.dumps(sort_keys=True, separators=(",", ":"))`, including `\uXXXX` escaping for non-ASCII. |
| `genesis_mesh::time` | Timestamps rendered as the Python reference renders them (no fraction, or exactly six digits; always `Z`). |
| `genesis_mesh::models` | `JoinCertificate`, `CertificateRevocationList`, `ServiceManifest`, `Signature`, the `Signed` trait. |
| `genesis_mesh::trust` | `verify_join_certificate`, `Policy`, `TrustAnchors`, `Decision`, `Reason`: evaluates a certificate into a decision. |
| `genesis_mesh::admin_auth` | Operator admin signatures, version 2: `AdminRequest`, `signing_payload`, `sign` ({doc}`auth`). |
| `genesis_mesh::federation` | Read-only preflight against a candidate authority: fetch genesis, CRL, revocation feed and treaties, then assess readiness. |
| `genesis_mesh::gateway` | The Axum-based HTTP service: scoped forwarding of the authority's service catalog, `verify` and `verify/batch`, the console, durable state and audit. `/keygen` and `/issue` exist only in local development mode. |
| `genesis_mesh::error` | `Error` and `Result` ({doc}`auth`). |

`#![forbid(unsafe_code)]` applies to the whole crate.

---

## `genesis-mesh` CLI

Dependency-free argument parsing; the crate is meant to build on constrained
edge targets.

```text
genesis-mesh keygen
genesis-mesh issue --seed <b64> --key-id <id> --node-key <b64> \
                   --network <name> [--role <r>]... [--days <n>]
genesis-mesh verify --cert <file> --anchor <key-id>=<pubkey-b64> [--anchor ...] \
                   [--crl <file>]
genesis-mesh canonical --file <file>
```

- `keygen`: generate an Ed25519 identity; prints the seed and public key.
  Each run makes a new identity.
- `issue`: issue and sign a join certificate; prints it as JSON.
- `verify`: evaluate a certificate against trust anchors; exits 0 if trusted.
- `canonical`: print the canonical JSON of a file, for cross-checking
  against the Python implementation's output.

A local round trip. Run `keygen` once for the authority and keep both of its
lines: the anchor passed to `verify` must be the public key of the seed that
signed the certificate.

```sh
cargo run -q --bin genesis-mesh -- keygen > na.txt
seed=$(awk '/seed_b64/{print $2}' na.txt)
na_pub=$(awk '/public_key_b64/{print $2}' na.txt)
node_key=$(cargo run -q --bin genesis-mesh -- keygen | awk '/public_key_b64/{print $2}')

cargo run -q --bin genesis-mesh -- issue \
  --seed "$seed" --key-id na-local --node-key "$node_key" \
  --network mesh-local --role role:anchor --days 7 > cert.json

cargo run -q --bin genesis-mesh -- verify --cert cert.json --anchor na-local="$na_pub"
```

`na.txt` holds the authority's seed, which is its private key: delete it
when you are done.

---

## `genesis-mesh-operator` federation preflight

Native, read-only check of a candidate authority before recognizing it. No
signing key or Python runtime required.

```sh
genesis-mesh-operator --origin https://na.example.org --network example \
  --authority-key BASE64_PUBLIC_KEY \
  --report preflight.json --policy-fragment network.json
```

It fetches `/genesis`, `/crl`, `/sovereign-revocation-feed` and
`/recognition-treaties` from the origin, assesses them, and, only on a
passing preflight, writes a gateway policy fragment for that network. A
passing preflight is not recognition by itself: establish scoped treaties,
verify a test membership, revoke it, and confirm rejection at every peer
after propagation.

---

## Running the gateway locally

The gateway reads its trust policy and client credentials from a policy
file. The policy format and the credentials it needs are described in
[operating the gateway](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/operations.md#policy-format).
Write your policy to `.local/policy.json` in a checkout of the gateway
repository (Git and the container build ignore that path), then run it one
of two ways:

- With Compose:

  ```sh
  docker compose -f deploy/docker-compose.yml up --build -d gateway
  ```

- Without Docker:

  ```sh
  GATEWAY_POLICY_FILE=.local/policy.json cargo run --locked --bin genesis-mesh-gateway
  ```

  The default bind address is loopback.

`genesis-mesh-gateway --check-config` validates the policy that
`GATEWAY_POLICY_FILE` names without starting the server. Local crypto utility mode (`/keygen` and `/issue`) needs
`GATEWAY_DEVELOPMENT=true` and a `GATEWAY_TOKEN` of at least 32 bytes; never
use it for a public service. See {doc}`/concepts/rust-gateway` for the
production deployment, service catalog and security boundary.
