# v0.18.0 Plan - Multi-Cloud Sovereign Operation Proof

## Current Status - 2026-06-08

`v0.18.0` shipped as an official-operator artifact release:

- Commit: `8e80e4b` (`Release v0.18.0 official operators`)
- Tag: `v0.18.0`
- Release: `https://github.com/GenesisMeshLabs/genesismesh/releases/tag/v0.18.0`
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
  are maintainer-operated sovereign deployments.
- The public labels currently recorded are `MiraOS-NA`, `001-NA`,
  `anonymous-NA`, `AMINE-M6-NA`, `ONS-A-NA`, and `USG-NB`.
- These operators are maintained as separate sovereign trust domains with
  distinct genesis material, NA keys, operator keys, databases, endpoints, and
  policies.

Important distinction: this release proves maintainer-operated multi-cloud
sovereign operation. It does not prove third-party or external-operator
adoption.

## Positioning

v0.18.0 is the multi-cloud operation milestone. v0.14.0 made the external
operator packet ready; v0.18.0 proved that separate sovereign trust domains can
be packaged, documented, recognized, and reviewed as a public fleet.

This is the release that changes the public story:

- Before v0.18: Genesis Mesh had local protocol proofs, operator readiness, and
  two-cloud operational evidence.
- After v0.18: Genesis Mesh had a maintainer-operated reference fleet with
  public trust material and continuity expectations.

The release should prove this statement:

> Separate maintainer-operated sovereign trust domains can run across multiple
> clouds, publish reviewable trust material, form recognition relationships, and
> propagate revocation without sharing private keys or collapsing into one
> central authority.

The future external-operator milestone remains separate:

> A named external operator runs a sovereign trust domain with their own account,
> keys, policy, endpoint, and continuity responsibilities, then produces a proof
> bundle that distinguishes their infrastructure from Genesis Mesh maintainer
> infrastructure.

## v0.17.x Readiness Patches

The v0.17.x patch series shipped before v0.18.0 and reduced onboarding
friction:

- v0.17.2 - Federation Bootstrap Readiness: reduce the friction of the first
  recognition relationship.
- v0.17.3 - Trust Bundle Exchange: package existing public trust material into
  a coherent reviewable bundle.
- v0.17.4 - Treaty Lifecycle Management: make direct recognition treaties
  easier to inspect, renew, replace, revoke, and audit.
- v0.17.5 - Sovereign Health and Trust Dashboard: make sovereign health and
  trust state legible without creating a central control plane.

These releases are readiness patches. They make operator onboarding easier, but
they do not count as external adoption proof.

## Operator Quality Test

The realness of the first external operator remains a separate gate. Use this
test before counting future external-operator proof as complete:

- Did they ask to run a sovereign, or did the maintainer ask them?
- Do they have a concrete reason to run it that exists with or without Genesis
  Mesh's success?
- Would they keep operating it after the proof, or shut it down?
- Are they willing to be named publicly?
- Would they answer "why are you running this?" without coaching?

If two or more answers are no, the proof is technically valid but narratively
weak. Recruit harder rather than ship faster.

## Success Criteria

### Completed v0.18.0 Criteria

- [x] Maintainer-operated sovereigns run with separate genesis material, NA
      keys, operator keys, databases, endpoints, and policies.
- [x] Public trust material is committed under `examples/official-operators/`.
- [x] `USG-NB` trust material validates against its live public endpoint.
- [x] The public material includes signed recognition and revocation-feed
      evidence.
- [x] The proof bundle clearly distinguishes maintainer-operated infrastructure
      from future externally operated infrastructure.
- [x] Documentation records what the release proves and what remains open.
- [x] Full release verification passes.

### Still Open For External Adoption

- [ ] A named external operator runs a sovereign from their own infrastructure
      account.
- [ ] The external operator controls their own genesis material, NA key,
      operator key, database, endpoint, and policy.
- [ ] The external operator publishes or shares public trust material for
      recognition.
- [ ] Another sovereign recognizes that external operator's sovereign through a
      signed treaty.
- [ ] Revocation propagates and changes acceptance on the recognizing
      sovereign.
- [ ] A public case artifact or release note names the operator if they agree.

## Release Name

`v0.18.0 - Multi-Cloud Sovereign Operation Proof`

## Core Flow

```text
Maintainer-Operated Reference Sovereign
  -> owns separate genesis, keys, policy, database, endpoint
  -> publishes public trust material
  -> issues an attestation
  -> revokes that attestation
  -> publishes signed feed

Recognizing Sovereign
  -> fetches public material
  -> signs treaty for the issuer
  -> accepts issuer attestation
  -> imports issuer feed
  -> rejects revoked attestation
  -> explains trust state in Connectome
```

The future external-operator flow uses the same protocol path, but it must be
run by an external operator with their own infrastructure and continuity
responsibilities.

## Design Principles

- Be honest about independence. Maintainer-operated multi-cloud proof is
  operational evidence, not third-party adoption.
- Do not count a maintainer-controlled deployment as external adoption.
- Do not hide operational friction. Record every manual step that would matter
  to the next operator.
- Prefer one strong external proof over several synthetic or maintainer-run
  demos.
- If recruitment slips repeatedly, treat that as a demand signal. Do not answer
  it by shipping unrelated code.

## Scope

### In Scope

- Recording public trust material for the maintainer-operated reference fleet.
- Validating live trust material and revocation-feed evidence.
- Updating docs and examples to describe maintainer-operated multi-cloud
  operation accurately.
- Preserving the future external-operator gate as a separate milestone.

### Out of Scope

- Claiming third-party adoption.
- Marketplace or registry launch.
- Paid billing integration.
- Transitive trust.
- General global discovery of all sovereigns.
- Enterprise IdP bridge.

## Implementation Phases

### Phase 1 - Reference Sovereign Inventory

- [x] Identify maintainer-operated sovereigns represented in public artifacts.
- [x] Confirm separate sovereign identities, keys, endpoints, databases, and
      policies.
- [x] Confirm private keys are not committed.
- [x] Capture health, readiness, Genesis, and Connectome evidence.

Captured evidence:

- Public official operator material is stored in
  `examples/official-operators/`.
- `USG-NB` live trust bundle validation passed against
  `http://164.92.250.135:8443`.
- The exported `USG-NB` connectome summary contains `9` active recognition
  edges.

### Phase 2 - Recognition and Revocation Proof

- [x] Import or fetch public trust material.
- [x] Form signed treaties with recognizing sovereigns.
- [x] Issue attestations from issuer sovereigns.
- [x] Verify recognizing sovereigns accept before revocation.
- [x] Revoke attestations on issuer sovereigns.
- [x] Import revocation feeds.
- [x] Verify recognizing sovereigns reject after revocation.

Captured evidence:

- `examples/official-operators/usg-nb/trust-bundle.json` includes a valid
  revocation feed with sequence `2`.
- The live `USG-NB` trust bundle validation reported no errors or warnings.

### Phase 3 - Evidence and Hardening

- [x] Capture proof material.
- [x] Redact secrets and sensitive endpoints if needed.
- [x] Record what was self-service versus assisted.
- [x] Patch the top friction points found during onboarding.
- [x] Add tests for any code fixes.
- [x] Update docs from the actual run.

Captured evidence:

- Runtime homes, local configs, logs, pids, databases, and private keys are
  ignored.
- Public material was moved into `examples/official-operators/` rather than
  committing generated runtime homes.
- `v0.18.0` package metadata, tag, release, wheel, and sdist were created.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

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

Completed v0.18.0 gate:

- [x] Maintainer-operated reference sovereigns are represented by public
      artifacts.
- [x] The proof completed without sharing private keys across sovereigns.
- [x] The proof bundle is captured and redacted.
- [x] Onboarding gaps are documented.
- [x] Any critical onboarding blockers found during the run are fixed.
- [x] v0.17.x readiness work has not been substituted for external-operator
      evidence.
- [x] Public release notes distinguish this from the v0.14 readiness release.
- [x] Full verification passes.

`v0.18.0` has already been tagged and released. With the maintainer-operated
reference fleet confirmations recorded above, the release can be described as
multi-cloud sovereign operation proof, not external adoption proof.
