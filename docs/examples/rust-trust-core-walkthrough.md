# Rust Trust Core Walkthrough

A hands-on walkthrough of the Rust implementation: mint and verify a join
certificate locally with the `genesis-mesh` CLI, run the production gateway
against a throwaway local policy, verify a certificate over HTTP, and preflight
a candidate authority before recognizing it. Everything here runs against the
[`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway)
repository; no Python runtime is required.

See {doc}`/sdk/rust/index` for the crate as a Rust dependency and
{doc}`/concepts/rust-gateway` for the production HTTP service.

## 1. Generate identities and a certificate

```sh
git clone https://github.com/GenesisMeshLabs/gateway.git
cd gateway

cargo run --bin genesis-mesh -- keygen
# seed_b64       <authority seed, keep secret>
# public_key_b64 <authority public key>

cargo run --bin genesis-mesh -- keygen
# seed_b64       <node seed>
# public_key_b64 <node public key>

cargo run --bin genesis-mesh -- issue \
  --seed <authority seed_b64> --key-id na-local \
  --node-key <node public_key_b64> \
  --network mesh-local --role role:anchor --days 7 > cert.json
```

## 2. Verify it offline

```sh
cargo run --bin genesis-mesh -- verify \
  --cert cert.json --anchor na-local=<authority public_key_b64>
```

Exit code `0` means the certificate is trusted under that anchor. Tamper with
`cert.json` or pass the wrong anchor and the command exits non-zero with a
reason — trust decisions are never a silent boolean.

## 3. Cross-check canonical JSON against Python

```sh
cargo run --bin genesis-mesh -- canonical --file cert.json
```

Compare this output against the Python reference implementation's
`json.dumps(data, sort_keys=True, separators=(",", ":"))` for the same
document. They must match byte for byte — this is what makes a signature
produced by one implementation verifiable by the other.

## 4. Run the gateway against a local policy

```sh
cargo run --example local_policy
GATEWAY_POLICY_FILE=.local/policy.json cargo run --bin genesis-mesh-gateway
```

`examples/local_policy.rs` generates a throwaway authority key, an empty
signed CRL, and one bearer-token client (`local-tester`), then prints that
client's token. This is explicitly not trust material; it exists only so the
gateway starts in production mode with one ready network.

## 5. Verify a certificate over HTTP

In a second terminal, mint a certificate that verifies against the local
policy's discarded authority key (the script wrote it to
`.local/na-local.seed`), then call the running gateway:

```sh
cargo run --bin genesis-mesh -- issue \
  --seed "$(cat .local/na-local.seed)" --key-id na-local \
  --node-key <node public_key_b64> --network mesh-local --days 7 > cert.json

curl -s http://127.0.0.1:8080/verify \
  -H "Authorization: Bearer <client token printed above>" \
  -H 'content-type: application/json' \
  -d "{\"certificate\": $(cat cert.json)}"
```

Check `trusted` in the response body, not just the HTTP status: a `200` with
`"trusted": false` and a reason list is a normal, correct response.

## 6. Preflight a candidate authority before recognizing it

```sh
cargo run --bin genesis-mesh-operator -- \
  --origin https://na.example.org --network example \
  --authority-key BASE64_PUBLIC_KEY \
  --report preflight.json --policy-fragment network.json
```

This is a read-only check: it fetches `/genesis`, `/crl`,
`/sovereign-revocation-feed`, and `/recognition-treaties` from the candidate
origin and reports whether they are internally consistent. It writes a
gateway policy fragment only when the preflight passes, and a passing
preflight is not recognition by itself — establish scoped treaties, verify a
test membership, revoke it, and confirm rejection at every peer after
propagation.

## What this does and does not prove

- It proves the Rust and Python implementations agree on canonical JSON,
  signatures, and certificate/CRL schemas for this document.
- It does not prove production readiness: durable state, OIDC, mutual TLS,
  Redis-backed quotas, and the 59-operation authority proxy are separate,
  opt-in controls documented in {doc}`/concepts/rust-gateway`.
- It does not replace the Network Authority. The Rust gateway verifies
  certificates and revocation state that the Python authority issued and
  signed; it never accepts or holds an authority's private signing key.
