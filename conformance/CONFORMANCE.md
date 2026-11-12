# Protocol Conformance

This directory contains the reference conformance suite for Genesis Mesh. It
started with v0.51.0; the `version` in each file is the release that last
changed that suite's vectors (for example `admin_auth.json`: 1.0.2).

An alternative implementation (TypeScript, Go, C#, etc.) that correctly
processes every vector in `vectors/` against its own cryptography and model
layer is considered **conformant** with the Genesis Mesh protocol.

## Structure

```
conformance/
  vectors/           # reference JSON vectors (one file per suite)
  generate_vectors.py  # regenerate vectors from the Python reference impl
  runner.py            # run vectors against genesis_mesh Python package
  CONFORMANCE.md       # this file
  README.md            # quick-start instructions
```

## Suites

| Suite | File | Vectors | What it covers |
|-------|------|---------|----------------|
| signatures | `signatures.json` | 2 | Ed25519 sign + verify over canonical JSON |
| treaties | `treaties.json` | 1 | RecognitionTreaty issue + verify |
| attestations | `attestations.json` | 1 | ModelAttestation issue + policy verify |
| revocation | `revocation.json` | 1 | SovereignRevocationFeed issue + verify |
| ibct | `ibct.json` | 1 | InvocationToken issue + verify |
| trust_evidence | `trust_evidence.json` | 1 | TrustEvidence packaging + verify |
| selective_disclosure | `selective_disclosure.json` | 2 | Capability Merkle proof + nullifier |
| consensus | `consensus.json` | 1 | 3-validator ConsensusProof assemble + verify |
| data_usage | `data_usage.json` | 1 | DataAccessIntent policy verify |
| node | `node.json` | 11 | Node request signatures (heartbeat, the edge `/join` executor co-signature, the `/node/*` routes with `purpose` and `audience`), a tampered body, join certificates and CRLs signed by the NA (v1.7.0; the Rust SDK runs it) |
| vouching | `vouching.json` | 32 | Records of a succeeded NA key judged now, the vouching horizon (1.8.0): attestations, treaties, revocation feeds and grants inside the grace, past the horizon, backdated into the old key's window, after the hand-over, by the new key, with a shorter or clamped grace, and tampered; and grants that start more than 24 hours after their issue (`record_malformed`). The core and the four SDKs run it (the SDKs from 1.8.1) |

## Vector format

Each `*.json` file has this shape:

```json
{
  "suite": "<suite-name>",
  "version": "0.51.0",
  "vectors": [
    {
      "id": "<suite>-NNN",
      "description": "human-readable description",
      "input": { ... },
      "expected": { ... }
    }
  ]
}
```

An alternative implementation must reproduce every value in `expected`
given the corresponding `input`.

## Key material

All vectors use deterministic Ed25519 keys derived from fixed seeds:

| Key | Seed (hex) | Public key (base64) |
|-----|-----------|---------------------|
| a | 000102...1f | (see `generate_vectors.py::pub_b64("a")`) |
| b | 202122...3f | (see `generate_vectors.py::pub_b64("b")`) |
| c | 404142...5f | (see `generate_vectors.py::pub_b64("c")`) |

Seed "a" is `bytes(range(32))`, seed "b" is `bytes(range(32, 64))`, seed "c"
is `bytes(range(64, 96))`.

In the `node` suite, "a" is the node key, "b" the executor key and "c" the
Network Authority's key. Each vector has a `kind`: `node_request` and
`join_request` give the unsigned body (`input.body`) and expect the exact
payload and the Ed25519 signature (deterministic), `join_request` also the
executor's payload, signature and key ID; `node_request_tampered` expects a
signature over another body not to verify; `join_certificate` and `crl` give
a signed record as the NA serves it (a certificate with the `edge` block
`/join` adds, which is not signed) and expect its canonical payload and
whether it verifies.

## Running against the Python reference implementation

```bash
pip install "genesis-mesh[dev]"
python conformance/runner.py          # all suites
python conformance/runner.py ibct     # one suite
pytest genesis_mesh/tests/test_conformance.py -v
```

## Regenerating vectors

If the Python reference implementation changes in a way that alters
canonical output, regenerate and commit the updated vectors:

```bash
python conformance/generate_vectors.py
git add conformance/vectors/ contract/kinds.json contract/MANIFEST.json genesis_mesh/contract_bundle.py
git commit -m "chore(conformance): regenerate vectors for vX.Y.Z"
```

The generator also rewrites `contract/kinds.json`,
`contract/MANIFEST.json`, the contract bundle's manifest (below), and
`genesis_mesh/contract_bundle.py`, the bundle version and digest the Network
Authority reports in `/health`.

Only regenerate vectors after updating `CHANGELOG.md` and bumping the
version — stale vectors must never be committed ahead of the code change
that produces them.

## Contract bundle

From 1.11.0 the vectors reach the SDKs and the gateway as a versioned
contract bundle instead of copies taken from `main`. The bundle is the
set of files listed in `contract/bundle.json`:

- the suites in `conformance/vectors/`;
- the frozen audit pack in `conformance/fixtures/`;
- `contract/public-surface.json` and `contract/kinds.json`;
- the tool `scripts/gm_contract.py`.

`contract/MANIFEST.json` lists each file with its sha256, each suite with
its vectors per kind, and the kinds each tier of consumer must run:

| Tier | Consumers |
|---|---|
| `verifier` | sdk-go |
| `governed` | sdk-typescript, sdk-rust, sdk-dotnet |
| `edge` | the sdk-rust edge agent |
| `gateway` | gateway |

`"all"` in `bundle.json` means every kind of the suite except its
`na_only_kinds`, so a new kind in such a suite is required at once. A
new suite without an entry fails the check, so every new suite needs a
decision on who must run it. Its `contract_digest` names the contract
itself: two releases with the same digest carry the same contract.

```bash
python scripts/gm_contract.py manifest          # rewrite contract/MANIFEST.json and genesis_mesh/contract_bundle.py
python scripts/gm_contract.py manifest --check  # CI "Contract bundle" and pre-commit
python scripts/gm_contract.py archive --out dist/contract
```

### Pinning the bundle in a consumer

A consumer (an SDK or the gateway) vendors `scripts/gm_contract.py` and
declares its side in `contract-bundle/consumer.json`:
- its tiers;
- which bundle files it copies where (a key ending in `/` copies a whole
  directory);
- the commands that regenerate derived files;
- the commands that run its conformance tests.

`sync` copies the bundle in and writes the pin to
`contract-bundle/bundle.lock`, next to an exact copy of the pinned manifest
(`contract-bundle/MANIFEST.json`):

```bash
python scripts/gm_contract.py sync --core-ref <40-hex commit on core main>
python scripts/gm_contract.py sync --core-path ../genesismesh   # local development only
python scripts/gm_contract.py verify --online
python scripts/gm_contract.py conformance --json-out conformance.json
```

- **A commit pin** (`--core-ref`) reads the files from that core commit.
  `verify --online` checks that the commit is on core `main` and that its
  manifest is the pinned one. Until the core publishes its first bundle with
  1.11.0, consumers pin commits and do not release.
- **A path pin** (`--core-path`) is for trying a core change locally:
  `verify` always refuses it, so it cannot be merged.
- **`verify`** checks every copy, the vendored tool and the manifest copy
  against the lock, and that every suite the consumer's tiers require is
  copied. Mark the copies, the lock and the manifest copy `-text` in
  `.gitattributes`: a checkout that converts line endings changes their
  bytes.
- **`conformance`** runs the test commands with `GM_CONFORMANCE_RECEIPTS`
  set, then `receipt-check`. Each runner writes a receipt saying how many
  vectors of each kind it ran and how many it does not run by design. The
  check fails when:
  - a required suite has no receipt;
  - a required kind is run short;
  - across a suite's runners, a kind's vectors are not each accounted for
    exactly once;
  - a receipt names a copy that differs from the bundle.
- **`sync --no-lock`** writes the copies and the manifest copy but leaves
  the lock and the tool, for canaries that test against core `main`; then
  run `conformance --no-lock-check`.

Release pins (`sync --version`), `release-check` and the publishing of the
bundle with each core release follow in the next change. The plan for
publishing the bundle with each core release, and for consumers pinning it,
is `ops/plan-v1.11.0-release-model.md`.
