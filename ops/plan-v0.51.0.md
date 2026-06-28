# v0.51.0 Plan -- Public API Stability + Protocol Conformance Suite

## Positioning

SDK authors, enterprise integrators, and independent implementors all need
the same guarantee before they invest in Genesis Mesh: that the APIs they
build against will not change arbitrarily between releases.

Without an explicit stability contract, every API is implicitly unstable.
Users cannot distinguish between a surface that will never change and one
that might change next week.  That uncertainty kills adoption.

The companion requirement is a protocol conformance suite.  A conformance
suite is what separates a protocol from a library.  A library is correct
when its tests pass.  A protocol is correct when any independent implementation
produces the same outputs for the same inputs.  Without conformance vectors,
the Python implementation is the protocol -- and that means there can only
ever be one implementation.

v0.51 locks the stability boundary and builds the infrastructure that lets
any future implementation prove conformance without needing the Python source.

v0.51 should prove:

> Genesis Mesh has a documented, versioned stability boundary: stable CLI
> commands and Python APIs are identified by name and guaranteed not to change
> incompatibly without a deprecation notice.  A machine-readable conformance
> suite of test vectors covers all major protocol operations; any implementation
> that passes the suite is a conforming Genesis Mesh implementation.

## Design

### `docs/stability.md` -- Public API stability contract

Two sections:

**Stable CLI surface** (guaranteed not to change incompatibly after v0.51):

```
genesis-mesh trust agree offer
genesis-mesh trust agree counter
genesis-mesh trust agree accept
genesis-mesh trust agree cosign
genesis-mesh trust agree verify
genesis-mesh trust boundary decide
genesis-mesh trust boundary verify
genesis-mesh trust evidence build
genesis-mesh trust evidence verify
genesis-mesh trust feed publish
genesis-mesh trust feed verify
genesis-mesh trust attest model
genesis-mesh trust attest verify
```

**Stable Python API** (guaranteed not to change incompatibly after v0.51):

```python
# genesis_mesh.trust.agreement
build_offer(), build_counter(), accept_offer(), cosign_agreement()
verify_agreement()

# genesis_mesh.trust.boundary
BoundaryEngine.decide(), BoundaryEngine.verify()

# genesis_mesh.trust.evidence
build_trust_evidence(), verify_trust_evidence()

# genesis_mesh.trust.selective_disclosure
commit_capabilities(), prove_capability_membership(), verify_capability_proof()
issue_nullifier()

# genesis_mesh.trust.consensus
cast_validator_vote(), build_consensus_proof(), verify_consensus_proof()

# genesis_mesh.trust.data_usage
create_data_access_intent(), verify_data_access_intent(), verify_data_access_record()

# genesis_mesh.crypto
generate_keypair(), sign_model(), load_private_key()
```

**Deprecation policy**: any stable API that must change will carry a
`DeprecationWarning` for at minimum two minor releases before removal.

**Internal (unstable)**: any symbol with a leading underscore, anything in
`genesis_mesh._internal`, any Tamarin/formal module.

### `DEPRECATION_POLICY.md`

Concise document:
- What "stable" means (no incompatible changes without 2-release notice)
- How deprecations are announced (DeprecationWarning + CHANGELOG)
- How to request a stability guarantee for an unlisted surface
- What is explicitly never stable (internal modules, experimental features)

### `conformance/` -- Protocol conformance suite

```
conformance/
  README.md               -- how to run, how to submit results
  vectors/
    signatures.json       -- Ed25519 sign + verify vectors
    treaties.json         -- treaty verification vectors
    attestations.json     -- model attestation vectors
    revocation.json       -- revocation feed vectors
    ibct.json             -- InvocationBoundedContinuityToken vectors
    trust_evidence.json   -- TrustEvidence build + verify vectors
    selective_disclosure.json  -- Merkle commitment + proof vectors
    consensus.json        -- multi-validator consensus proof vectors
    data_usage.json       -- DataAccessIntent + policy vectors
  runner.py               -- Python conformance runner (uses Python impl)
  CONFORMANCE.md          -- what "passing" means, result format
```

### Vector format (all vector files share this schema)

```json
{
  "suite": "signatures",
  "version": "0.51.0",
  "vectors": [
    {
      "id": "sig-001",
      "description": "Sign canonical JSON, verify with matching public key",
      "input": {
        "message": "<hex-encoded canonical JSON>",
        "private_key": "<base64url signing key>"
      },
      "expected": {
        "signature": "<base64url>",
        "valid": true
      }
    }
  ]
}
```

All keys are deterministic.  All timestamps are fixed.  All UUIDs are fixed.
A conforming implementation must produce bit-identical output for the
`expected` fields.

### `conformance/runner.py`

```python
def run_suite(suite_path: Path) -> ConformanceResult:
    """Load a vector file, run each vector against the Python implementation,
    return pass/fail per vector."""

def run_all(vectors_dir: Path) -> dict[str, ConformanceResult]:
    """Run all suites; print a summary table."""
```

The runner is the reference.  A new implementation runs the same vectors
and compares outputs.

### `genesis_mesh/tests/test_conformance.py`

Parametrized test that runs every vector in `conformance/vectors/` through
the Python implementation and asserts it matches `expected`.  This keeps the
conformance suite honest: if the Python implementation changes and the vector
is not updated, the test fails.

### Internal API cleanup

All symbols currently in public modules that are not listed in the stable
surface are prefixed with `_` or moved to `genesis_mesh._internal`.  This is
a one-time mechanical change; no behavior changes.

## Success Criteria

- [ ] `docs/stability.md` listing stable CLI surface + Python API
- [ ] `DEPRECATION_POLICY.md`
- [ ] `conformance/vectors/` with all 9 vector files (signatures, treaties,
      attestations, revocation, ibct, trust_evidence, selective_disclosure,
      consensus, data_usage)
- [ ] `conformance/runner.py` (`run_suite`, `run_all`)
- [ ] `conformance/README.md` and `conformance/CONFORMANCE.md`
- [ ] `genesis_mesh/tests/test_conformance.py` parametrized against all vectors
- [ ] All new conformance tests pass; full suite passes
- [ ] Internal API cleanup: no unstable symbols in public namespaces
- [ ] Sphinx build clean with `-W`

## Release Gate

- [ ] Package metadata bumped to `0.51.0`
- [ ] CHANGELOG entry (stability + conformance suite)
- [ ] history.md updated with v0.51.0 entry
- [ ] All prior tests continue to pass
- [ ] `conformance/runner.py` exits 0 on all vectors
