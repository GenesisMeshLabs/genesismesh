# v0.55.0 Plan -- Go Protocol Verifier (First Independent Implementation)

## Positioning

Three SDKs (TypeScript, Go, C#) make it easier to call Genesis Mesh.
They do not prove that Genesis Mesh is a protocol.

A protocol is independent of any single implementation.  The only way to
prove that is with a second implementation that passes the conformance suite
without using the first implementation's code.

The Go protocol verifier is the first independent implementation of Genesis
Mesh.  It is written in Go from the protocol specification and the conformance
vectors (v0.51).  It shares no code with the Python implementation.

Scope for v0.55 is verification only.  The verifier can check signatures,
validate treaties, verify attestations, check revocation feeds, verify IBCTs,
verify TrustEvidence records, verify selective-disclosure proofs, and verify
consensus proofs.  It does not issue, sign, or construct new records.

A sovereign that wants to verify that another party has produced a valid
Genesis Mesh record can do so using the Go verifier without running any
Python or calling any external service.  This is the foundation for
multi-runtime trust enforcement in infrastructure-level components.

v0.55 should prove:

> A Genesis Mesh record produced by the Python implementation can be
> independently verified by the Go verifier: the verifier passes all
> conformance vectors for the 9 supported suites using only the Go standard
> library plus an Ed25519 package, with no Python dependency.

## Design

### Repository location: `verifier/go/`

The verifier is a standalone Go module, separate from the `sdk/go/` client.
It has no network dependency -- it verifies records from local data.

```
verifier/go/
  go.mod                     -- module: github.com/thaersaidi/genesismesh/verifier
  go.sum
  verifier/
    signatures.go            -- Ed25519 signature verification
    treaties.go              -- treaty structure + signature verification
    attestations.go          -- model attestation verification
    revocation.go            -- revocation feed chain verification
    ibct.go                  -- InvocationBoundedContinuityToken verification
    trust_evidence.go        -- TrustEvidence + graph digest verification
    disclosure.go            -- Merkle proof verification (capability membership)
    consensus.go             -- multi-validator consensus proof verification
    data_usage.go            -- DataAccessIntent + policy compliance check
  cmd/
    gm-verify/
      main.go                -- CLI: gm-verify <suite> <record.json>
  conformance/
    runner.go                -- runs conformance/vectors/ against this verifier
  verifier_test/
    signatures_test.go
    treaties_test.go
    ...
  README.md
```

### Core verification functions

Each function takes a Go struct (deserialized from the protocol JSON) and
returns `(bool, VerificationResult)`:

```go
// Signature verification
func VerifySignature(message []byte, signature []byte, publicKey ed25519.PublicKey) bool

// Treaty
func VerifyTreaty(treaty Treaty, issuerPublicKey ed25519.PublicKey) (bool, VerificationResult)

// Model attestation
func VerifyAttestation(attestation ModelAttestation, policy LogicPolicy,
    agentPublicKeys []ed25519.PublicKey, atTime time.Time) (bool, AttestationVerificationResult)

// Revocation feed
func VerifyRevocationFeed(feed RevocationFeed, issuerPublicKey ed25519.PublicKey) (bool, VerificationResult)

// IBCT
func VerifyIBCT(token InvocationToken, useCount int, issuerPublicKey ed25519.PublicKey,
    atTime time.Time) (bool, IBCTVerificationResult)

// TrustEvidence
func VerifyTrustEvidence(evidence TrustEvidence, graphExport GraphExport,
    issuerPublicKey ed25519.PublicKey, atTime time.Time) (bool, EvidenceVerificationResult)

// Selective disclosure
func VerifyCapabilityProof(proof CapabilityMembershipProof, commitment CapabilityCommitment,
    issuerPublicKey ed25519.PublicKey) (bool, ProofVerificationResult)

// Consensus
func VerifyConsensusProof(proof ConsensusProof,
    validatorPublicKeys map[string]ed25519.PublicKey,
    atTime time.Time) (bool, ConsensusVerificationResult)

// Data usage
func VerifyDataAccessIntent(intent DataAccessIntent, policy DataLicensePolicy,
    agentPublicKey ed25519.PublicKey, atTime time.Time) (bool, DataUsageViolationReason, []DataUsageViolation)
```

### `VerificationResult` type

```go
type VerificationResult struct {
    Valid  bool
    Reason string // matches Python reason strings exactly
}
```

Reason strings must exactly match the Python implementation's reason strings
as documented in the conformance suite.  This is the correctness invariant.

### `cmd/gm-verify` CLI

```
gm-verify signatures   record.json --public-key <base64url>
gm-verify treaty       treaty.json --public-key <base64url>
gm-verify attestation  attestation.json --policy policy.json --public-key <base64url>
gm-verify evidence     evidence.json --graph graph.json --public-key <base64url>
gm-verify ibct         token.json --use-count 3 --public-key <base64url>
gm-verify disclosure   proof.json --commitment commitment.json --public-key <base64url>
gm-verify consensus    proof.json --validators validators.json
gm-verify data-usage   intent.json --policy policy.json --public-key <base64url>
```

Exit code 0 = valid.  Exit code 1 = invalid (reason printed to stdout as JSON).

### Conformance runner

`verifier/go/conformance/runner.go` reads the vector files from
`conformance/vectors/` (the Python-side suite from v0.51) and runs each
vector through the Go verifier.  Output is a pass/fail table per vector.

`go test ./conformance/...` runs all vectors as subtests.

### Dependencies

Go standard library only, plus:
- `golang.org/x/crypto` (Ed25519 is in stdlib since Go 1.13, but x/crypto
  provides the NaCl-compatible API that matches the Python `nacl` library)

No external HTTP dependencies.  No Python.  No cgo.

## Success Criteria

- [ ] `verifier/go/` with all 9 verification functions
- [ ] All functions accept and return the correct protocol types
- [ ] Reason strings exactly match Python implementation strings
- [ ] `gm-verify` CLI handles all 8 suites; exits 0/1 correctly
- [ ] Conformance runner passes all 9 vector suites (100% pass rate)
- [ ] `go test ./...` >= 50 tests; all pass
- [ ] `go build ./...` produces no errors
- [ ] Zero external dependencies beyond `golang.org/x/crypto`
- [ ] `README.md` explains verification-only scope

## Release Gate

- [ ] Package metadata bumped to `0.55.0`
- [ ] `verifier/go/go.mod` at correct version
- [ ] CHANGELOG entry (Go verifier -- "first independent implementation")
- [ ] history.md updated with v0.55.0 entry
- [ ] All prior Python tests continue to pass
- [ ] All SDK tests continue to pass
- [ ] Conformance vector pass rate explicitly stated in CHANGELOG (must be 100%)
