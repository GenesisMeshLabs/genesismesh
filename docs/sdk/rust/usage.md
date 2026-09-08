# Modules & CLI — Rust crate

## Module map

| Module | Purpose |
| --- | --- |
| `genesis_mesh::crypto` | Ed25519 identities: `KeyPair`, `CachedPublicKey`, detached signing and verification. |
| `genesis_mesh::canonical` | Canonical JSON byte-compatible with Python's `json.dumps(sort_keys=True, separators=(",", ":"))`, including `\uXXXX` escaping for non-ASCII. |
| `genesis_mesh::models` | `JoinCertificate`, `CertificateRevocationList`, `ServiceManifest`, `Signature`, the `Signed` trait. |
| `genesis_mesh::trust` | `verify_join_certificate`, `Policy`, `TrustAnchors`, `Decision`, `Reason` — evaluates a certificate into an actionable decision. |
| `genesis_mesh::federation` | Read-only preflight against a candidate authority: fetch genesis, CRL, revocation feed, and treaties, then assess readiness. |
| `genesis_mesh::gateway` | The Axum-based HTTP service: `keygen`, `issue`, `verify`, `verify/batch`, and the authority service proxy. |

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

- `keygen` — generate an Ed25519 identity; prints the seed and public key.
- `issue` — issue and sign a join certificate; prints it as JSON.
- `verify` — evaluate a certificate against trust anchors; exits 0 if trusted.
- `canonical` — print the canonical JSON of a file, for cross-checking
  against the Python implementation's output.

Example local round trip:

```sh
seed=$(cargo run --bin genesis-mesh -- keygen | awk '/seed_b64/{print $2}')
node_key=$(cargo run --bin genesis-mesh -- keygen | awk '/public_key_b64/{print $2}')

cargo run --bin genesis-mesh -- issue \
  --seed "$seed" --key-id na-local --node-key "$node_key" \
  --network mesh-local --role role:anchor --days 7 > cert.json

cargo run --bin genesis-mesh -- verify \
  --cert cert.json --anchor na-local="$(cargo run --bin genesis-mesh -- keygen | awk '/public_key_b64/{print $2}')"
```

---

## `genesis-mesh-operator` federation preflight

Native, read-only check of a candidate authority before recognizing it. No
signing key or Python runtime required.

```sh
genesis-mesh-operator --origin https://na.example.org --network example \
  --authority-key BASE64_PUBLIC_KEY \
  --report preflight.json --policy-fragment network.json
```

It fetches `/genesis`, `/crl`, `/sovereign-revocation-feed`, and
`/recognition-treaties` from the origin, assesses them, and — only on a
passing preflight — writes a gateway policy fragment for that network. A
passing preflight is not recognition by itself: establish scoped treaties,
verify a test membership, revoke it, and confirm rejection at every peer
after propagation.

---

## Running the gateway locally

```sh
cargo run --example local_policy
GATEWAY_POLICY_FILE=.local/policy.json cargo run --bin genesis-mesh-gateway
```

`examples/local_policy.rs` generates a self-consistent local policy: a
throwaway authority key, an empty signed CRL, and one bearer-token client. It
is explicitly not trust material — the authority seed is discarded except for
minting local test certificates against the same policy. See
{doc}`/concepts/rust-gateway` for the production deployment, service catalog,
and security boundary.
