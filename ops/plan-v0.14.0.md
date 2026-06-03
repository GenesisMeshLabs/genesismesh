# v0.14.0 Plan - External Operator Adoption Readiness

## Positioning

v0.14.0 was shipped as **External Operator Adoption Readiness**, not the final
multi-cloud sovereign operation proof. This distinction matters because the release
produced the packet, playbook, proof bundle shape, and operator-facing docs that
make adoption possible, while the future external-operator run still depends on a
real external operator.

- Before v0.14: Genesis Mesh had maintainer-operated sovereignty proof.
- After v0.14: Genesis Mesh had an operator packet ready for a second human to
  run.
- After v0.17: Genesis Mesh should have the actual external operator adoption
  proof.

v0.13.0 made sovereign operation reproducible. v0.14.0 packaged that work into
external operator readiness. The adoption milestone itself moved to v0.17.0 so
the public release history stays honest.

The release should prove this statement:

> A future external operator has enough documentation, safety guidance, and proof
> bundle structure to run a sovereign without handing control of their keys,
> policy, or infrastructure to Genesis Core.

The community milestone remains v0.17.0: a named future external operator
actually running the proof.

## Scope Adjustment

v0.14.0 is tagged as the readiness release. The original external-operator run
and post-run hardening phases were moved to v0.17.0 so the release history does
not imply that multi-cloud operation proof happened before a named future external operator
ran a sovereign.

Deferred to v0.17.0:

- External operator run.
- Post-run onboarding hardening.

## Operator Quality Test

The realness of the first external operator is the whole game. An investor
will smell the difference between "real adopter" and "friend doing a favor" in
one question. Use this test before counting the proof as complete:

- Did they ask to run a sovereign, or did the maintainer ask them?
- Do they have a concrete reason to run it that exists with or without
  Genesis Mesh's success?
- Would they keep operating it after the proof, or shut it down?
- Are they willing to be named publicly as Sovereign B?
- Would they answer "why are you running this?" without coaching?

If two or more answers are no, the proof is technically valid but narratively
weak. Recruit harder rather than ship faster. A second operator who shuts the
sovereign down after the demo is not adoption; it is theater.

## Success Criteria

- [x] Operator quickstart exists.
- [x] Operator security checklist exists.
- [x] Recognition playbook exists.
- [x] Proof bundle schema exists.
- [x] Proof bundle capture path exists or is documented.
- [x] Documentation distinguishes maintainer-operated readiness from actual
  external operation.
- [x] Release notes are honest that a future external operator is still required.

## Release Name

`v0.14.0 - External Operator Adoption Readiness`

## Core Flow

```text
Maintainer
  -> packages operator quickstart, security checklist, recognition playbook
  -> defines proof bundle evidence
  -> verifies docs and commands against the current implementation
  -> publishes readiness release with the adoption gap stated clearly

External Operator Candidate
  -> receives the packet
  -> can understand what to run, what not to share, and what evidence to return
  -> becomes the target for v0.17 multi-cloud operation proof
```

The supply-chain trust gate scheduled for v0.15 is the most likely recruitment
vehicle for the eventual operator. v0.14 does not need to ship that wedge, but
it should make the operator packet clear enough that v0.15 can point a real
maintainer at it.

## Design Principles

- Be honest about independence. v0.14 readiness is not the same as adoption.
- Do not hide operational friction. Record every manual step that blocked the
  maintainer while producing the packet.
- Keep the protocol neutral. The external operator should not need Genesis Core
  as a permanent broker.
- Prefer one clear readiness packet over more maintainer-operated demos.
- Move future external-operator proof to v0.17. Do not blur the release language.

## Scope

### In Scope

- Operator packet for external sovereign setup.
- External-operator checklist and security checklist.
- Proof bundle format for adoption evidence.
- Documentation of the first external operator proof.
- Small tooling fixes discovered during onboarding.
- Support for a managed onboarding session if needed.

### Out of Scope

- Marketplace or registry launch.
- Paid billing integration.
- Transitive trust.
- General global discovery of all sovereigns.
- Large enterprise IdP bridge unless the external operator specifically needs
  it to complete the proof.

## Implementation Phases

### Phase 1 - Operator Packet

- [x] Add `docs/operators/quickstart.md`.
- [x] Add `docs/operators/security-checklist.md`.
- [x] Add `docs/operators/recognition-playbook.md`.
- [x] Include exact commands for generating keys, bootstrapping a VM, checking
      health, and exposing sovereign metadata.
- [x] Include a "what not to share" section for private keys and operator
      signatures.

### Phase 2 - Proof Bundle

- [x] Define a small proof bundle JSON schema or markdown format.
- [x] Capture endpoints, network names, NA public key prefixes, attestation ID,
      treaty ID, feed ID, feed sequence, pre/post verification reasons, and
      Connectome summary.
- [x] Redact secrets by construction.
- [x] Add a command or script option that writes the proof bundle.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

External proof verification moved to v0.17.0. v0.14 verification is limited to
docs, schema, proof-bundle tooling, and normal project checks.

## Release Gate

v0.14.0 was ready to tag when:

- [x] The operator packet was complete enough to hand to a candidate operator.
- [x] The proof bundle format was documented.
- [x] The recognition playbook was documented.
- [x] The security checklist made key ownership boundaries explicit.
- [x] The CHANGELOG did not claim external adoption had already happened.
- [x] Full verification passed.
