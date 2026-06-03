# v0.17.0 Plan - External Operator Adoption Proof

## Positioning

v0.17.0 is the actual adoption milestone. v0.14.0 made the operator packet
ready; v0.17.0 proves that a real non-maintainer can use it.

This is the release that changes the public story:

- Before v0.17: Genesis Mesh has maintainer-operated proof and operator
  readiness.
- After v0.17: Genesis Mesh has evidence of an early network.

Every other release in v0.13-v0.16 is mostly code, docs, or operations that the
maintainer can ship alone. v0.17 cannot be completed alone, and that is exactly
why it matters.

The release should prove this statement:

> A named non-maintainer operator can run a sovereign trust domain, form a
> recognition relationship, and complete the revocation proof without handing
> control of their keys, policy, or infrastructure to Genesis Core.

## Operator Quality Test

The realness of the first external operator is the whole game. An investor will
smell the difference between "real adopter" and "friend doing a favor" in one
question. Use this test before counting the proof as complete:

- Did they ask to run a sovereign, or did the maintainer ask them?
- Do they have a concrete reason to run it that exists with or without Genesis
  Mesh's success?
- Would they keep operating it after the proof, or shut it down?
- Are they willing to be named publicly as Sovereign B?
- Would they answer "why are you running this?" without coaching?

If two or more answers are no, the proof is technically valid but narratively
weak. Recruit harder rather than ship faster. A second operator who shuts the
sovereign down after the demo is not adoption; it is theater.

## Success Criteria

- [ ] A non-maintainer operator is named and willing to be referenced in release
      notes or a public case artifact.
- [ ] The operator runs a sovereign using their own genesis, NA key, operator
      key, DB, endpoint, and policy.
- [ ] The operator publishes or shares public trust material for recognition.
- [ ] The operator issues and revokes a membership, maintainer, or agent
      attestation.
- [ ] Another sovereign recognizes that operator's sovereign through a signed
      treaty.
- [ ] Revocation propagates and changes acceptance on the recognizing
      sovereign.
- [ ] The proof bundle clearly distinguishes maintainer-operated infrastructure
      from externally operated infrastructure.
- [ ] Documentation records what the operator did self-service and where
      maintainer assistance was still required.

## Release Name

`v0.17.0 - External Operator Adoption Proof`

## Core Flow

```text
External Operator
  -> runs Sovereign B
  -> owns genesis, keys, policy, database, endpoint
  -> issues member, maintainer, or agent attestation
  -> revokes that attestation
  -> publishes signed feed

Recognizing Sovereign
  -> fetches B public material
  -> signs treaty for B
  -> accepts B attestation
  -> imports B feed
  -> rejects revoked attestation
  -> explains trust state in Connectome
```

The v0.15 supply-chain gate is the preferred recruitment wedge. A maintainer who
has a real reason to protect release authority is a stronger Sovereign B than a
friendly operator running a demo with no reason to continue.

## Design Principles

- Be honest about independence. "External operator" means a real second human
  controls at least one sovereign's keys and infrastructure.
- Do not tag without a named non-maintainer operator.
- Do not hide operational friction. Record every manual step that blocked the
  operator.
- Prefer one strong adoption proof over several maintainer-operated demos.
- If recruitment slips repeatedly, treat that as a demand signal. Do not answer
  it by shipping unrelated code.

## Scope

### In Scope

- Recruiting one credible external operator.
- Running the v0.14 operator packet with that operator.
- Capturing the proof bundle from their run.
- Patching small onboarding blockers discovered during the run.
- Updating docs and examples from the operator's actual experience.
- Publishing a short public artifact if the operator agrees.

### Out of Scope

- Marketplace or registry launch.
- Paid billing integration.
- Transitive trust.
- General global discovery of all sovereigns.
- Enterprise IdP bridge unless the external operator specifically needs it.
- Counting a maintainer-controlled second VM as adoption proof.

## Implementation Phases

### Phase 1 - Recruit Operator

- [ ] Identify candidate operators from v0.15 and commercial-track outreach.
- [ ] Apply the Operator Quality Test.
- [ ] Confirm the operator has a concrete reason to run a sovereign.
- [ ] Confirm what can be named publicly.
- [ ] Agree on proof scope, timeline, and support boundaries.

### Phase 2 - Operator-Owned Sovereign

- [ ] Have the operator generate their own genesis.
- [ ] Have the operator generate or own their NA key and operator key.
- [ ] Have the operator run their own DB and endpoint.
- [ ] Confirm private keys are never shared with Genesis Core.
- [ ] Capture health, readiness, Genesis, and Connectome evidence.

### Phase 3 - Recognition and Revocation Proof

- [ ] Import or fetch the operator's public trust material.
- [ ] Form a signed treaty with the recognizing sovereign.
- [ ] Issue an attestation from the operator sovereign.
- [ ] Verify the recognizing sovereign accepts it before revocation.
- [ ] Revoke the attestation on the operator sovereign.
- [ ] Import the revocation feed.
- [ ] Verify the recognizing sovereign rejects the same attestation after
      revocation.

### Phase 4 - Evidence and Hardening

- [ ] Capture the proof bundle.
- [ ] Redact secrets and sensitive endpoints if needed.
- [ ] Record what was self-service versus assisted.
- [ ] Patch the top friction points found during onboarding.
- [ ] Add tests for any code fixes.
- [ ] Update docs from the operator's actual run.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

External proof verification must include the operator's confirmation that they
controlled their own keys and infrastructure.

## Release Gate

Do not tag v0.17.0 until:

- [ ] A named non-maintainer operator has run one sovereign.
- [ ] The proof completed without Genesis Core controlling the operator's keys.
- [ ] The proof bundle is captured and redacted.
- [ ] The onboarding gaps are documented.
- [ ] Any critical onboarding blockers found during the run are fixed.
- [ ] Public release notes distinguish this from the v0.14 readiness release.
- [ ] Full verification passes.
