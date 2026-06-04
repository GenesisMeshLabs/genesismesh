# v0.17.3 Plan - Trust Bundle Exchange

## Positioning

v0.17.3 is an adoption-readiness patch. It should make sovereign trust material
portable and reviewable as one coherent bundle instead of scattered URLs,
keys, files, and instructions.

The default design should be a packaging and inspection layer over existing
public surfaces. It should not create a new protocol primitive unless the work
cannot be done safely without one.

This release should prove this statement:

> An operator can export, inspect, share, and import a sovereign trust bundle
> that packages existing public trust material without exposing secrets or
> granting trust automatically.

If the bundle becomes a signed, versioned public protocol artifact with its own
validation rules and semantics, stop and promote the work to a minor release
plan. As long as it packages existing endpoints and proof material, it remains
a v0.17.x patch.

## Success Criteria

- [ ] A trust bundle format is documented and versioned.
- [ ] A CLI export path creates a bundle from existing public sovereign
      material.
- [ ] A CLI inspect path displays sovereign identity, endpoints, public key
      fingerprints, validity, policy, revocation feed references, and treaty
      context.
- [ ] A CLI validate path detects malformed, stale, inconsistent, or incomplete
      bundles.
- [ ] Import or use of a bundle feeds review/bootstrap workflows but does not
      grant trust automatically.
- [ ] Bundles never include private keys, operator secrets, invite tokens, or
      bearer credentials.
- [ ] Tests cover export, inspect, validate, redaction, and failure modes.

## Release Name

`v0.17.3 - Trust Bundle Exchange`

## Scope

### In Scope

- Define a trust bundle schema for existing public trust material.
- Export bundle data from:
  - sovereign metadata;
  - genesis trust root;
  - recognition policy;
  - revocation feed references;
  - optional treaty references or proof context.
- Add bundle inspection output for operators.
- Add validation checks for identity consistency, endpoint reachability, key
  fingerprints, required fields, and unsupported bundle versions.
- Add docs explaining how to exchange and review a bundle.
- Add tests for bundle round trip and validation failure paths.

### Out of Scope

- A global registry.
- Automatic trust or auto-issued treaties.
- Private-key packaging.
- Invite-token packaging.
- New treaty semantics.
- Mandatory signed protocol artifact semantics unless the work is explicitly
  re-scoped as a minor release.

## Parallel Adoption Checkpoint

At v0.17.3 tag time, record:

- [ ] Number of candidate operators who received or reviewed a trust bundle.
- [ ] Number of candidate operators who could explain what the bundle contains.
- [ ] Whether the bundle reduced onboarding friction compared with raw URLs and
      files.
- [ ] Top remaining blockers for v0.18.0.

If recruitment remains at zero, do not treat bundle work as progress toward
adoption. Pause and recruit before continuing unrelated readiness work.

## Implementation Phases

### Phase 1 - Bundle Boundary

- [ ] Decide the minimum bundle contents.
- [ ] Document what is allowed and forbidden in a bundle.
- [ ] Decide whether the bundle is JSON, directory, archive, or both.
- [ ] Confirm the design remains a packaging layer over existing trust
      material.

### Phase 2 - Export and Inspect

- [ ] Add the export command or command path.
- [ ] Add human-readable inspect output.
- [ ] Include stable fingerprints rather than raw key-heavy output where
      appropriate.
- [ ] Ensure exports are deterministic enough to diff or archive.

### Phase 3 - Validate and Use

- [ ] Validate required fields and version support.
- [ ] Validate sovereign identity consistency across included material.
- [ ] Validate endpoint reachability when requested.
- [ ] Allow a valid bundle to seed federation bootstrap review.
- [ ] Ensure bundle use still requires explicit operator trust decisions.

### Phase 4 - Docs and Tests

- [ ] Add operator docs for exchanging trust bundles.
- [ ] Add schema or format reference.
- [ ] Add tests for export, inspect, validate, and unsupported versions.
- [ ] Add tests that bundles never contain private material.
- [ ] Add tests for using a bundle in federation review.

## Verification

```powershell
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs/examples/assets/scripts -q
python -m sphinx -b html -W docs docs/pages
git diff --check
```

Smoke verification should include:

- export a bundle from a local sovereign;
- inspect the bundle without a running NA where possible;
- validate the bundle against a running NA;
- reject a malformed or mismatched bundle;
- confirm no private keys, invite tokens, or credentials are present.

## Release Gate

Do not tag v0.17.3 until:

- [ ] The bundle format is documented.
- [ ] Export, inspect, and validate flows work.
- [ ] Bundle use cannot grant trust automatically.
- [ ] No secrets are included in exported bundles.
- [ ] The protocol-primitive escape valve has been explicitly reviewed.
- [ ] Focused and full verification pass.
- [ ] The adoption checkpoint is recorded.
