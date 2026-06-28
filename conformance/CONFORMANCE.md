# Protocol Conformance

This directory contains the reference conformance suite for Genesis Mesh v0.51.0.

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
git add conformance/vectors/
git commit -m "chore(conformance): regenerate vectors for vX.Y.Z"
```

Only regenerate vectors after updating `CHANGELOG.md` and bumping the
version — stale vectors must never be committed ahead of the code change
that produces them.
