# v0.17.2 Plan - Federation Bootstrap Readiness

## Positioning

v0.17.2 is an adoption-readiness patch. It should make the first relationship
between two sovereigns easier to start without changing the recognition treaty
model itself.

The protocol already has the required primitives: sovereign metadata, genesis
trust roots, recognition treaties, revocation feeds, proof bundles, and the
Connectome. The missing piece is the operator journey that turns those pieces
into a clear first federation workflow.

This release should prove this statement:

> An operator can review another sovereign, understand its public trust
> material, draft or issue a direct recognition treaty, and verify the
> resulting trust path without needing the maintainer to explain every step.

This is not the external-operator adoption milestone. v0.18.0 still requires a
named future external operator running their own sovereign.

## Success Criteria

- [ ] A guided command path or documented flow exists for reviewing another
      sovereign before trust is granted.
- [ ] The bootstrap flow checks health, readiness, genesis, public metadata,
      recognition policy, and Connectome availability where applicable.
- [ ] Treaty scope is previewed before issue, including subject sovereign,
      public key material, validity, allowed roles, accepted statuses, and
      claims.
- [ ] The operator must explicitly confirm the trust decision before a treaty is
      created.
- [ ] The flow verifies the resulting trust path after treaty creation.
- [ ] Evidence output is useful for an operator packet or proof bundle.
- [ ] The release does not introduce automatic trust, transitive trust, or
      global discovery.

## Release Name

`v0.17.2 - Federation Bootstrap Readiness`

## Scope

### In Scope

- Add or refine a guided federation bootstrap CLI flow over existing public and
  admin surfaces.
- Add sovereign preflight checks for:
  - `/healthz`;
  - `/readyz`;
  - `/genesis`;
  - `/sovereign.json`;
  - `/recognition-policy`;
  - `/connectome.json`.
- Show a human-readable trust review before treaty issue.
- Preview treaty scope and validity before signing.
- Verify the trust path after treaty issue.
- Emit a small bootstrap evidence summary that can be attached to an operator
  proof bundle.
- Update operator docs to explain the first federation workflow.
- Add focused tests for review, confirmation, failure, and verification paths.

### Out of Scope

- Global registry or sovereign discovery service.
- Automatic trust decisions.
- Transitive trust.
- Browser-based admin mutation.
- New treaty semantics.
- New public trust artifact format.
- Counting a maintainer-controlled VM as multi-cloud operation proof.

## Parallel Adoption Checkpoint

At v0.17.2 tag time, record:

- [ ] Number of real candidate operators in conversation.
- [ ] Number of candidates who reviewed the bootstrap workflow.
- [ ] Top three onboarding blockers still preventing v0.18.0.
- [ ] Whether any candidate has a concrete reason to run a sovereign.

If all candidate counts are zero, pause unrelated feature work after this patch
and concentrate on recruitment before continuing the v0.17.x series.

## Implementation Phases

### Phase 1 - Current Surface Review

- [ ] Inventory the existing sovereign metadata, treaty, proof, and Connectome
      surfaces used during bootstrap.
- [ ] Identify which checks are browser-safe and which require signed operator
      calls.
- [ ] Confirm no new trust semantics are needed.

### Phase 2 - Guided Bootstrap Flow

- [ ] Add or refine the CLI command path for reviewing another sovereign.
- [ ] Display endpoint, sovereign ID, network name, NA public key fingerprint,
      genesis validity, and policy information.
- [ ] Fail clearly when public metadata is unavailable or internally
      inconsistent.
- [ ] Require explicit confirmation before treaty issue.

### Phase 3 - Treaty Preview and Issue

- [ ] Preview treaty scope and validity before signing.
- [ ] Reuse existing treaty issue semantics.
- [ ] Emit a stable evidence summary for the issued treaty.
- [ ] Verify the resulting recognition edge in Connectome.

### Phase 4 - Docs and Tests

- [ ] Add operator documentation for the bootstrap workflow.
- [ ] Add focused CLI tests for successful bootstrap.
- [ ] Add tests for failed preflight checks.
- [ ] Add tests that confirm no treaty is issued without explicit approval.
- [ ] Add tests for trust-path verification output.

## Verification

```powershell
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs/examples/assets/scripts -q
python -m sphinx -b html -W docs docs/pages
git diff --check
```

Smoke verification should include:

- one clean bootstrap review against a local sovereign;
- one treaty issue through the guided flow;
- one trust-path verification after treaty issue;
- one failed preflight path against an unavailable or mismatched sovereign;
- confirmation that no private keys or secrets are written to evidence output.

## Release Gate

Do not tag v0.17.2 until:

- [ ] The bootstrap flow reviews another sovereign before trust is granted.
- [ ] Treaty issue remains explicit and signed.
- [ ] Trust-path verification works after treaty creation.
- [ ] Docs explain the first federation workflow.
- [ ] Focused and full verification pass.
- [ ] The adoption checkpoint is recorded.
