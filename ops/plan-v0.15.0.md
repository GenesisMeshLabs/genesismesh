# v0.15.0 Plan - Supply-Chain Trust Gate

## Positioning

This release reconciles a disagreement between the deck and the roadmap. The
deck names a bank, a manufacturer, and an AI platform as early buyers. The
roadmap's adoption hypothesis names open-source supply chain. Both are right,
but they are different beachheads.

Reconcile them this way:

- **Free wedge:** open-source supply chain. Maintainers are findable without
  enterprise sales. Integration is a GitHub Action. Pain is real and
  post-incident sensitivity is high. This is how the v0.17 external operator
  gets recruited.
- **Paid enterprise:** managed sovereign per v0.16. Banks, manufacturers, and
  AI platforms pay for hosted control plane and operational credibility.

v0.15 is the wedge. v0.16 is the revenue. The two point in the same direction:
portable trust, demonstrated cheaply on the open-source side, sold expensively
on the enterprise side.

The release should prove this statement:

> A project can accept or reject a maintainer action based on a portable
> attestation issued by another sovereign, and revocation of that attestation
> blocks the action without local re-enrollment.

Additionally, the artifacts produced by this release should give an
open-source maintainer a concrete reason to stand up a sovereign, and
therefore become candidate Sovereign B for v0.17.

This is not a package registry replacement. It is a narrow CI/release gate
that demonstrates how Genesis Mesh can sit in a publishing or release path.

## Competitive Positioning

Supply-chain trust already has Sigstore, SLSA, npm provenance, PyPI
attestations, and GitHub artifact attestations. Expect the question "isn't
this Sigstore?" in every conversation. Have the one-liner ready:

> Sigstore and SLSA sign provenance inside one trust domain. Genesis Mesh
> carries portable trust *across* independent sovereigns and revokes it so a
> compromised maintainer is rejected everywhere, not just unsigned.

Land this distinction in the docs example. If a reader walks away thinking
Genesis Mesh is Sigstore-with-extra-steps, the release has failed regardless
of test coverage.

## Parallel Adoption Checkpoint

This release can tag before the external operator proof, but recruitment cannot
wait until after it. At v0.15.0 tag time, record the adoption pipeline status:

- [ ] At least five real operator or maintainer conversations are in flight.
- [ ] At least one maintainer has reviewed the v0.14 operator packet.
- [ ] At least one candidate can explain why they might run a sovereign without
      being coached.
- [ ] If all counts are zero, pause new feature planning and treat the blocker
      as demand discovery, not engineering.

## Success Criteria

- A project or maintainer sovereign can issue a maintainer attestation.
- Another project can recognize the issuing sovereign.
- A CI/release gate can verify whether the maintainer is trusted for a scoped
  role.
- Revocation by the issuing sovereign causes the gate to reject the same
  maintainer.
- The gate emits a clear trust-path explanation for audit and debugging.
- The workflow runs locally and in GitHub Actions without requiring private
  keys in logs.

## Release Name

`v0.15.0 - Supply-Chain Trust Gate`

## Core Flow

```text
Project A Sovereign
  -> attests Alice as release maintainer

Project B Sovereign
  -> signs treaty recognizing Project A maintainer attestations

CI / Release Gate
  -> receives Alice attestation
  -> verifies treaty-backed trust
  -> allows release action

Project A Sovereign
  -> revokes Alice attestation
  -> publishes feed

Project B / CI
  -> imports feed
  -> rejects Alice on the same release gate
```

## Design Principles

- Keep the gate narrow. Prove trust enforcement before attempting registry
  integration.
- Make failure useful. A blocked action should explain the issuer, treaty,
  role, revocation reason, and trust path.
- Do not claim full supply-chain protection until a real registry or release
  system honors the gate.
- Avoid heavy governance. Maintainers should see a lightweight trust check, not
  a new bureaucracy.

## Scope

### In Scope

- Maintainer/release attestation claims.
- CLI verifier suitable for CI.
- GitHub Actions example workflow.
- Docs example showing before/after revocation.
- Optional proof bundle for CI output.
- Tests for accepted, unknown issuer, disallowed role, revoked attestation, and
  stale feed behavior in the gate.
- A one-page "why a maintainer would run a sovereign" pitch intended for
  recruitment of the v0.17 external operator, not just documentation.
- A "vs Sigstore / SLSA / npm provenance / artifact attestations" comparison
  page anchored from the supply-chain example.

### Out of Scope

- Publishing to PyPI, npm, crates.io, or other registries.
- Package-manager policy plugins.
- Transparency logs.
- Reputation scores.
- Economic settlement.
- General marketplace behavior.

## Implementation Phases

### Phase 1 - Maintainer Attestation Profile

- [x] Define a documented claim profile for project maintainers.
- [x] Include project ID, subject key, delegated role, validity window, and
      optional repository metadata.
- [x] Reuse existing membership attestation primitives where possible.
- [x] Add validation helpers if the generic model is too permissive for CI.

### Phase 2 - CI Verifier

- [x] Add a CLI command that verifies an attestation against a treaty and
      optional imported revocation state.
- [x] Return stable exit codes for allow/deny/error.
- [x] Print compact audit output suitable for CI logs.
- [x] Avoid printing private keys, signatures, or full request bodies.

### Phase 3 - GitHub Actions Example

- [x] Add a sample workflow that runs the verifier before a release action.
- [x] Use checked-in demo artifacts or ephemeral local proof setup.
- [x] Demonstrate accepted before revocation.
- [x] Demonstrate rejected after revocation import.

### Phase 4 - Docs and Assets

- [x] Add `docs/examples/supply-chain-trust-gate.md`.
- [x] Add an asset script under `docs/examples/assets/scripts/`.
- [x] Generate PNG/GIF proof assets.
- [x] Link the example from `docs/examples/demos.md` and `docs/index.md`.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

If the GitHub Actions example is added, verify it with a local dry run where
possible and with focused tests for the verifier command.

## Release Gate

Do not tag v0.15.0 until:

- [x] A maintainer attestation can authorize a CI/release gate.
- [x] Revocation blocks the same maintainer after feed import.
- [x] The gate provides stable exit codes and human-readable reasons.
- [x] Docs clearly state that registry integration is future work.
- [ ] Adoption checkpoint has been updated with real conversation counts.
- [x] Full verification passes.
