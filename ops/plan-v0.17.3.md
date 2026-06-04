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

- [x] A trust bundle format is documented and versioned.
- [x] A CLI export path creates a bundle from existing public sovereign
      material.
- [x] A CLI inspect path displays sovereign identity, endpoints, public key
      fingerprints, validity, policy, revocation feed references, and treaty
      context.
- [x] A CLI validate path detects malformed, stale, inconsistent, or incomplete
      bundles.
- [x] Import or use of a bundle feeds review/bootstrap workflows but does not
      grant trust automatically.
- [x] Bundles never include private keys, operator secrets, invite tokens, or
      bearer credentials.
- [x] Tests cover export, inspect, validate, redaction, and failure modes.

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

- [x] Decide the minimum bundle contents.
- [x] Document what is allowed and forbidden in a bundle.
- [x] Decide whether the bundle is JSON, directory, archive, or both.
- [x] Confirm the design remains a packaging layer over existing trust
      material.

### Phase 2 - Export and Inspect

- [x] Add the export command or command path.
- [x] Add human-readable inspect output.
- [x] Include stable fingerprints rather than raw key-heavy output where
      appropriate.
- [x] Ensure exports are deterministic enough to diff or archive.

### Phase 3 - Validate and Use

- [x] Validate required fields and version support.
- [x] Validate sovereign identity consistency across included material.
- [x] Validate endpoint reachability when requested.
- [x] Allow a valid bundle to seed federation bootstrap review.
- [x] Ensure bundle use still requires explicit operator trust decisions.

### Phase 4 - Docs and Tests

- [x] Add operator docs for exchanging trust bundles.
- [x] Add schema or format reference.
- [x] Add tests for export, inspect, validate, and unsupported versions.
- [x] Add tests that bundles never contain private material.
- [x] Add tests for using a bundle in federation review.

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

Implementation verification completed locally:

- `python -m pytest genesis_mesh/tests -q` - 263 passed
- `python -m mypy genesis_mesh --ignore-missing-imports` - passed
- `python -m compileall genesis_mesh docs/examples/assets/scripts -q` - passed
- `python -m sphinx -b html -W docs docs/pages` - passed
- `git diff --check` - passed

Live endpoint smoke completed from the local checkout:

- exported a USG-NB bundle from `http://164.92.250.135:8443`;
- inspected and validated the bundle against the live DigitalOcean endpoint;
- imported the bundle into a local review receipt with `trust_granted: false`;
- ran `federation bootstrap --dry-run` from Azure USG to the USG-NB issuer
  bundle.

## Release Gate

Do not tag v0.17.3 until:

- [x] The bundle format is documented.
- [x] Export, inspect, and validate flows work.
- [x] Bundle use cannot grant trust automatically.
- [x] No secrets are included in exported bundles.
- [x] The protocol-primitive escape valve has been explicitly reviewed.
- [x] Focused and full verification pass.
- [ ] The adoption checkpoint is recorded.
