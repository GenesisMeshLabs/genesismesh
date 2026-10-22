# Rust Trust Core Walkthrough

A hands-on walkthrough of the Rust implementation: mint and verify a join
certificate locally with the gateway repository's `genesis-mesh` binary
(`cargo run --bin genesis-mesh`; not the Python CLI of the same name, whose
commands differ), run the production gateway against a local authority,
verify a certificate over HTTP, and preflight a candidate authority before
recognizing it. Everything here runs against the
[`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway)
repository. Steps 1 to 3 and 6 need no Python runtime. Steps 4 and 5 take the
authority's signed CRL from a local Python Network Authority, because the
gateway trusts a network only with a signed CRL and the Rust binaries do not
sign one.

The commands were run on 2026-10-22 with gateway 1.7.0 and Genesis Mesh 1.7.0,
in a Linux shell. Building on Windows needs NASM for the TLS library.

See {doc}`/sdk/rust/index` for the crate as a Rust dependency and
{doc}`/concepts/rust-gateway` for the production HTTP service.

## 1. Generate identities and a certificate

```sh
git clone https://github.com/GenesisMeshLabs/gateway.git
cd gateway

cargo run --bin genesis-mesh -- keygen
# Keep the seed secret; it is the private key.
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

Exit code `0` (output `trusted`) means the certificate is trusted under that
anchor. Tamper with `cert.json` or pass the wrong anchor and the command
prints `UNTRUSTED` with its reasons and exits `1`:

```text
UNTRUSTED
  - BadSignature { key_id: "na-local" }
  - NoTrustedIssuer
```

## 3. Cross-check canonical JSON against Python

```sh
cargo run --bin genesis-mesh -- canonical --file cert.json
```

Compare this output against the Python reference implementation's
`json.dumps(data, sort_keys=True, separators=(",", ":"))` for the same
document. They must match byte for byte — this is what makes a signature
produced by one implementation verifiable by the other.

## 4. Run the gateway against a local authority

The gateway trusts a network only with the authority's public key and a CRL
that key signed. Start a throwaway local Network Authority with the Python
package, take its key and signed CRL, and write a gateway policy with one
bearer-token client (`local-tester`). The policy format is described in the
gateway's `docs/operations.md`.

```sh
mkdir -p .local
python3 -m venv .local/venv && . .local/venv/bin/activate
pip install genesis-mesh
genesis-mesh init --home .local/na --config .local/na/config.json \
  --env-file .local/na.env --na-port 8443
genesis-mesh na start --env-file .local/na.env &
until curl -sf http://127.0.0.1:8443/health > /dev/null; do sleep 1; done

NA_PUB=$(grep -v '^#' .local/na/keys/na.pub | tr -d '[:space:]')
curl -s http://127.0.0.1:8443/crl > .local/crl.json
SEQ=$(python3 -c 'import json; print(json.load(open(".local/crl.json"))["sequence"])')
TOKEN=$(openssl rand -hex 32)
TOKEN_SHA=$(printf %s "$TOKEN" | sha256sum | cut -d' ' -f1)
cat > .local/policy.json <<EOF
{
  "revision": "local-1",
  "clients": [{"id": "local-tester", "token_sha256": "$TOKEN_SHA",
               "networks": ["mesh-local"], "metrics": false, "requests_per_minute": 60}],
  "networks": {
    "mesh-local": {
      "anchors": {"na-local": "$NA_PUB"},
      "minimum_crl_sequence": $SEQ,
      "crl": $(cat .local/crl.json)
    }
  }
}
EOF

GATEWAY_POLICY_FILE=.local/policy.json cargo run --locked --bin genesis-mesh-gateway -- --check-config
GATEWAY_POLICY_FILE=.local/policy.json cargo run --locked --bin genesis-mesh-gateway
```

`--check-config` prints `Configuration valid`. This is not trust material: it
exists only so the gateway starts in production mode with one ready network.
The CRL is valid until its `next_update` (a day for a local NA); the policy
above sets no `crl_url`, so restart with a fresh CRL after that.

## 5. Verify a certificate over HTTP

In a second terminal, in the same directory, mint a certificate under the
local NA's key and call the running gateway. Signing with the NA's seed
outside the NA is a shortcut for this local example only; a real node gets
its certificate by enrolling with the NA.

```sh
NA_SEED=$(grep -v '^#' .local/na/keys/na.key | tr -d '[:space:]')
cargo run --bin genesis-mesh -- issue \
  --seed "$NA_SEED" --key-id na-local \
  --node-key <node public_key_b64> --network mesh-local --days 7 > cert.json

curl -s http://127.0.0.1:8080/verify \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"certificate\": $(cat cert.json)}"
# {"trusted":true,"reasons":[]}
```

The same call with a tampered certificate answers `200` with
`{"trusted":false,"reasons":["BadSignature { key_id: \"na-local\" }","NoTrustedIssuer","IssuerSignatureMissing"]}`.
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
  Redis-backed quotas, and the authority proxy are separate, opt-in controls
  documented in {doc}`/concepts/rust-gateway`.
- It does not replace the Network Authority. The Rust gateway verifies
  certificates and revocation state that the Python authority issued and
  signed. In production mode it never accepts or holds an authority's
  private signing key. The development-only `/issue` route
  (`GATEWAY_DEVELOPMENT=true`) takes a seed and must never be exposed.
