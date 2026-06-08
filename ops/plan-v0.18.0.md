# v0.18.0 Plan - External Operator Adoption Proof

## Current Status - 2026-06-08

`v0.18.0` has shipped as an official-operator artifact release:

- Commit: `8e80e4b` (`Release v0.18.0 official operators`)
- Tag: `v0.18.0`
- Release: `https://github.com/thaersaidi/genesismesh/releases/tag/v0.18.0`
- Assets: `genesis_mesh-0.18.0-py3-none-any.whl`,
  `genesis_mesh-0.18.0.tar.gz`
- Public operator artifacts:
  `examples/official-operators/`
- Refreshed `USG-NB` trust bundle:
  `examples/official-operators/usg-nb/trust-bundle.json`

The shipped `USG-NB` trust bundle validates against
`http://164.92.250.135:8443` and records:

- `sovereign_id`: `USG-NB`
- `active_edge_count`: `9`
- `recognition_edge_count`: `9`
- `active_treaty_count`: `9`
- `revocation_feed_sequence`: `2`
- `revocation_feed_status`: `ok`

Operator status confirmation:

- The public operator labels represented in `examples/official-operators/`
  are confirmed by the maintainer to be non-maintainers of Genesis Mesh.
- The public labels currently recorded are `MiraOS-NA`, `001-NA`,
  `anonymous-NA`, `AMINE-M6-NA`, `ONS-A-NA`, and `USG-NB`.
- These operators are also confirmed as founding community operators: early
  protocol testers from the initial public releases who now maintain their own
  sovereigns.

Important distinction: this release proves the current official-operator
connectome, public trust material path, and founding community operator cohort.
The operators are initial maintainers of their own sovereigns, not Genesis Mesh
core maintainers.

## Adoption Proof Completion Confirmation

Maintainer confirmation for the v0.18.0 adoption proof:

- The founding community operators controlled their own genesis, NA key,
  operator key, database, endpoint, and policy.
- Genesis Core did not receive or control their private keys.
- The public operator artifacts distinguish founding-community-operated
  sovereigns from Genesis Core-maintained runtime material.
- The operator run completed cleanly, onboarding gaps were handled, and no
  unresolved blocker remains for the shipped artifact release.

With these confirmations, the original external non-maintainer adoption proof is
complete for the v0.18.0 release narrative.

## Positioning

v0.18.0 is the actual adoption milestone. v0.14.0 made the operator packet
ready; v0.18.0 proves that a real non-maintainer can use it.

This is the release that changes the public story:

- Before v0.18: Genesis Mesh has maintainer-operated proof and operator
  readiness.
- After v0.18: Genesis Mesh has evidence of an early network.

Every other release in v0.13-v0.16 is mostly code, docs, or operations that the
maintainer can ship alone. v0.18 cannot be completed alone, and that is exactly
why it matters.

The release should prove this statement:

> A named non-maintainer operator can run a sovereign trust domain, form a
> recognition relationship, and complete the revocation proof without handing
> control of their keys, policy, or infrastructure to Genesis Core.

## v0.17.x Readiness Patches

The v0.17.x patch series can ship before v0.18.0, but it must not dilute what
v0.18.0 means.

- v0.17.2 - Federation Bootstrap Readiness: reduce the friction of the first
  recognition relationship.
- v0.17.3 - Trust Bundle Exchange: package existing public trust material into
  a coherent reviewable bundle.
- v0.17.4 - Treaty Lifecycle Management: make direct recognition treaties
  easier to inspect, renew, replace, revoke, and audit.
- v0.17.5 - Sovereign Health and Trust Dashboard: make sovereign health and
  trust state legible without creating a central control plane.

These releases are readiness patches. They are allowed to make operator
onboarding easier, but they do not count as external adoption proof. The v0.18.0
gate remains unchanged: a named non-maintainer operator must run a sovereign
with their own keys, policy, database, endpoint, and infrastructure.

At each v0.17.x patch tag, record the adoption checkpoint from that plan. If
candidate operator conversations are still zero across the patch series, pause
feature work before v0.18.0 and focus on recruitment. More readiness code does
not solve a zero-demand signal.

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

- [x] A non-maintainer operator is named and willing to be referenced in release
      notes or a public case artifact.
- [x] The operator runs a sovereign using their own genesis, NA key, operator
      key, DB, endpoint, and policy.
- [x] The operator publishes or shares public trust material for recognition.
- [x] The operator issues and revokes a membership, maintainer, or agent
      attestation.
- [x] Another sovereign recognizes that operator's sovereign through a signed
      treaty.
- [x] Revocation propagates and changes acceptance on the recognizing
      sovereign.
- [x] The proof bundle clearly distinguishes maintainer-operated infrastructure
      from externally operated infrastructure.
- [x] Any shipped v0.17.x readiness patches were reviewed during the operator
      run, and remaining onboarding gaps are recorded.
- [x] Documentation records what the operator did self-service and where
      maintainer assistance was still required.

## Release Name

`v0.18.0 - External Operator Adoption Proof`

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

- [x] Identify candidate operators from v0.15 and commercial-track outreach.
- [x] Review the shipped v0.17.x readiness artifacts with candidate operators.
- [x] Apply the Operator Quality Test.
- [x] Confirm the operator has a concrete reason to run a sovereign.
- [x] Confirm what can be named publicly.
- [x] Agree on proof scope, timeline, and support boundaries.

### Phase 2 - Operator-Owned Sovereign

- [x] Have the operator generate their own genesis.
- [x] Have the operator generate or own their NA key and operator key.
- [x] Have the operator run their own DB and endpoint.
- [x] Confirm private keys are never shared with Genesis Core.
- [x] Capture health, readiness, Genesis, and Connectome evidence.

Captured evidence:

- Public official operator material is stored in
  `examples/official-operators/`.
- `USG-NB` live trust bundle validation passed against
  `http://164.92.250.135:8443`.
- The exported `USG-NB` connectome summary contains `9` active recognition
  edges.

Ownership confirmation is complete: the founding community operators maintain
their own sovereigns, and Genesis Core did not receive or control private keys.

### Phase 3 - Recognition and Revocation Proof

- [x] Import or fetch the operator's public trust material.
- [x] Form a signed treaty with the recognizing sovereign.
- [x] Issue an attestation from the operator sovereign.
- [x] Verify the recognizing sovereign accepts it before revocation.
- [x] Revoke the attestation on the operator sovereign.
- [x] Import the revocation feed.
- [x] Verify the recognizing sovereign rejects the same attestation after
      revocation.

Captured evidence:

- `examples/official-operators/usg-nb/trust-bundle.json` includes a valid
  revocation feed with sequence `2`.
- The live `USG-NB` trust bundle validation reported no errors or warnings.

Before/after revocation acceptance evidence is complete for the operator run.

### Phase 4 - Evidence and Hardening

- [x] Capture the proof bundle.
- [x] Redact secrets and sensitive endpoints if needed.
- [x] Record what was self-service versus assisted.
- [x] Patch the top friction points found during onboarding.
- [x] Add tests for any code fixes.
- [x] Update docs from the operator's actual run.

Captured evidence:

- Runtime homes, local configs, logs, pids, databases, and private keys are
  ignored.
- Public material was moved into `examples/official-operators/` rather than
  committing generated runtime homes.
- `v0.18.0` package metadata, tag, release, wheel, and sdist were created.
- Maintainer confirmation: onboarding gaps from the operator run are clean and
  handled; no unresolved onboarding blocker remains for the shipped artifact
  release.

The shipped artifact release required no unresolved follow-up code fix from the
operator run.

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

### Completed Verification For Shipped v0.18.0

- [x] JSON syntax validation for all official operator artifacts.
- [x] `genesis-mesh trust-bundle validate --bundle
      examples/official-operators/usg-nb/trust-bundle.json --na
      http://164.92.250.135:8443 --format json`
- [x] `pre-commit run --all-files`
- [x] `pre-commit run --all-files --hook-stage pre-push`
- [x] `python -m build`
- [x] GitHub release created with wheel and sdist assets.

Note: `check-added-large-files` was skipped in the pre-commit wrapper because
Windows Application Control blocked that hook process with `WinError 4551`.
The same hook implementation was run directly and confirmed all added files are
well below the configured `4096 KB` limit.

## Release Gate

Original external-adoption release gate:

- [x] A named non-maintainer operator has run one sovereign.
- [x] The proof completed without Genesis Core controlling the operator's keys.
- [x] The proof bundle is captured and redacted.
- [x] The onboarding gaps are documented.
- [x] Any critical onboarding blockers found during the run are fixed.
- [x] v0.17.x readiness work has not been substituted for external-operator
      evidence.
- [x] Public release notes distinguish this from the v0.14 readiness release.
- [x] Full verification passes.

`v0.18.0` has already been tagged and released. With the maintainer
confirmations recorded above, the release can be described as external
non-maintainer adoption proof by founding community operators.
