## v0.38.1 — Codebase Modularity Cleanup

**Internal maintenance release. No user-visible behavior changes.**

This release enforces the layer rule before the v0.38-v0.48 trust cycle adds more features:

```
models/*            = Pydantic entities only
trust/*             = protocol logic only
cli/*               = Click parsing + output only
workflows/*         = multi-step orchestration (new)
na_service/routes/* = HTTP adaptation only
```

### What changed

**trust/consensus/ (new package)**
Split the 410-line `trust/consensus.py` into five focused modules:
- `cascade.py` — `assess_cascade_risk()`, `CascadeAssessmentReason`
- `votes.py` — `cast_validator_vote()`
- `proof.py` — `assemble_consensus_proof()`, `verify_consensus_proof()`
- `identity.py` — `issue_ephemeral_identity()`, `verify_ephemeral_identity()`
- `gate.py` — `ConsensusGate`

All existing `from genesis_mesh.trust.consensus import X` imports continue to work.

**trust/context/ (new package)**
Split the 464-line `trust/context.py` into three focused modules:
- `gates.py` — `GateCallable`, built-in gates
- `engine.py` — `BoundaryEngine`
- `decisions.py` — `verify_boundary_decision()`

All existing imports unchanged.

**genesis_mesh/workflows/ (new package)**
Heavy workflow logic extracted from CLI files:
- `workflows/trust_bundle.py` — bundle export, validation, loading
- `workflows/federation.py` — `run_federation_bootstrap`, `FederationBootstrapVerificationError`
- `workflows/proof.py` — `run_remote_proof`, `inspect_proof_bundle`, `cleanup_proof_state`

**CLI files are now thin wrappers**
- `cli/trust_bundle.py`: 602 to 281 lines
- `cli/federation.py`: 465 to 163 lines
- `cli/proof_ops.py`: 623 to 264 lines

**AGENT.md** updated with the enforced layer rule for contributors.

### Upgrade path

No changes required. All public symbols are backward-compatible.
