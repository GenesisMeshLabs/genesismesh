# v0.38.1 Plan — Codebase Modularity and Layer Cleanup

## Positioning

This is a non-functional refactoring release. No new protocol capabilities,
no new CLI commands, no new models. The intent is to enforce the layer rule
before adding eleven more features on top of existing technical debt.

**The layer rule:**

```
models/*          = signed artifacts / Pydantic entities only
trust/*           = protocol logic only (create, verify, assess, gate)
cli/*             = Click parsing + output only — no protocol logic inline
na_service/routes/* = HTTP adaptation only — dispatch to service, return response
```

Any file that does more than one of those must be split.

The immediate trigger is that `trust/consensus.py` now combines five distinct
responsibilities after v0.38. This pattern will repeat in every future plan
unless the boundary is made explicit and enforced via project conventions.

---

## Scope

### P1 — trust/consensus.py → package

Current 410-line file mixes: cascade scoring, vote creation, proof assembly,
proof verification, ephemeral identity issuance, identity verification, and a
ConsensusGate. Split into:

```
genesis_mesh/trust/consensus/
  __init__.py      # re-exports everything for backward compat
  cascade.py       # CascadeAssessmentReason, assess_cascade_risk()
  votes.py         # cast_validator_vote()
  proof.py         # assemble_consensus_proof(), verify_consensus_proof(),
                   # ConsensusProofVerificationReason, result dataclasses
  identity.py      # issue_ephemeral_identity(), verify_ephemeral_identity(),
                   # EphemeralIdentityVerificationReason, result dataclasses
  gate.py          # ConsensusGate
```

Backward-compat guarantee: `from genesis_mesh.trust.consensus import X` works
unchanged for all existing callers. No caller file needs to change.

### P2 — trust/context.py → package

464-line file mixes: BoundaryEngine orchestration, proof-aware evaluation
(evaluate_with_proof), decision verification, validity window gate, and
several built-in gate helpers.

```
genesis_mesh/trust/context/
  __init__.py      # re-exports for backward compat
  engine.py        # BoundaryEngine class only
  gates.py         # validity_window_gate(), built-in gate helpers
  decisions.py     # verify_boundary_decision(), result types
```

### P3 — CLI modules: thin wrappers

Each CLI file should be: Click decorators + arg parsing + `click.echo()`.
Multi-step workflow logic goes into a new `genesis_mesh/workflows/` module.

Files targeted:
- `cli/proof_ops.py` → extract workflow to `workflows/proof.py`
- `cli/trust_bundle.py` → extract to `workflows/trust_bundle.py`
- `cli/federation.py` → extract to `workflows/federation.py`

### P4 — NA routes: HTTP adaptation only

Files targeted:
- `na_service/routes/treaties.py`
- `na_service/routes/enrollment.py`
- `na_service/routes/attestations.py`

Each route handler becomes: parse → dispatch to domain service → return
response. Domain validation and business logic move to
`na_service/services/` modules.

### P5 — Operator console: view-model from rendering

Files targeted:
- `na_service/operator_console/dashboard.py`
- `na_service/operator_console/atlas.py`
- `na_service/operator_console/rendering.py`

Split data assembly (view-model building) from HTML template rendering.

---

## Out of Scope

- `node/runtime.py`, `node/node.py`, `node/peer_manager.py` — large but
  stable interfaces; refactor only if bugs or tests show locality problems.
- Any new feature, capability, model, or test behavior.
- Changelog visible to users — this is a maintenance release.
- Renaming public symbols or changing call signatures.

---

## Implementation Rules

1. **No behavior change.** Every refactored module must produce identical
   results before and after. If a test breaks, the refactor is wrong.
2. **Backward-compat shims.** Every split module provides `__init__.py`
   re-exports so callers need zero changes.
3. **Tests prove equivalence.** Full suite (757+ tests) must pass at every
   intermediate step, not just at the end.
4. **One split at a time.** Each P1/P2/P3 item is a separate commit.
5. **No opportunistic cleanup.** Do not rename, fix, or improve adjacent code
   while splitting. Resist the urge. That belongs in the next feature plan.

---

## Success Criteria

- [x] `trust/consensus/` package with 5 submodules; all existing imports work
- [x] `trust/context/` package with 3 submodules; all existing imports work
- [x] CLI target files thinned; workflow logic in `workflows/`
- [ ] Each NA route handler < 80 lines; business logic in `services/`
- [x] Full test suite passes at every commit
- [x] Sphinx clean with -W at every commit
- [x] mypy clean at every commit
- [x] AGENT.md updated with the layer rule

## Release Gate

- [x] Version bumped to `0.38.1`
- [x] CHANGELOG entry (internal maintenance note)
- [x] history.md updated
- [x] No user-visible behavior changes
