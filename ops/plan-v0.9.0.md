# v0.9.0 Plan - Sovereign Trust and Membership Attestations

## Goal

v0.9.0 should prove portable trust across separately administered sovereign
trust domains.

The release should answer:

```text
Can Sovereign B evaluate a membership claim issued by Sovereign A,
under its own local recognition policy, and stop trusting that claim when
Sovereign A revokes it?
```

## Release Narrative

Genesis Mesh moves from trusted nodes inside one mesh to portable trust across
sovereign communities.

The first proof can be operated by the maintainer on two separately configured
Network Authorities. That is acceptable for v0.9.0 as long as the demo is
honest about it. The protocol mechanism must allow a third-party operator to
replace Sovereign B without code changes.

## Success Criteria

- A sovereign can issue a signed membership attestation.
- A different sovereign can evaluate that attestation using local recognition
  policy.
- Acceptance requires explicit issuer recognition.
- Unknown issuers are rejected.
- Expired and not-yet-valid attestations are rejected.
- Revoked attestations are rejected.
- Invalid signatures are rejected.
- Trust decisions are explainable through structured results and audit-ready
  reason codes.

## Scope

### In Scope

- `SovereignIdentity` model.
- `MembershipAttestation` model.
- `RecognitionPolicy` model.
- Local attestation verification helper.
- Role/status claims in attestations.
- Attestation validity windows.
- Local revocation list support.
- Focused model and verifier tests.
- Documentation/demo plan for two maintainer-operated sovereigns.

### Out of Scope

- Signed `RecognitionTreaty` artifacts.
- Cross-sovereign revocation propagation.
- Derived/transitive recognition.
- Global sovereign discovery.
- Connectome visualization.
- Package registry integration.
- Governance UI.

## Implementation Phases

### Phase 1 - Core Models

- [x] Add `SovereignIdentity`.
- [x] Add `MembershipAttestation`.
- [x] Add `RecognizedIssuer`.
- [x] Add `RecognitionPolicy`.
- [x] Export the models from `genesis_mesh.models`.
- [x] Add canonical JSON helpers for signing.
- [x] Add validity helpers.

### Phase 2 - Local Verification

- [x] Add an attestation verifier.
- [x] Verify issuer is recognized.
- [x] Verify signature using the recognized issuer public key.
- [x] Verify validity window.
- [x] Verify status is acceptable.
- [x] Verify requested roles are allowed by local policy.
- [x] Verify attestation ID is not locally revoked.
- [x] Return structured reason codes.

### Phase 3 - Tests

- [x] Valid attestation accepted.
- [x] Unknown issuer rejected.
- [x] Expired attestation rejected.
- [x] Not-yet-valid attestation rejected.
- [x] Revoked attestation rejected.
- [x] Invalid signature rejected.
- [x] Disallowed role rejected.
- [x] Suspended status rejected unless policy allows it.

### Phase 4 - Network Authority Integration

- [x] Add durable attestation storage.
- [x] Add issuer-side attestation endpoint.
- [x] Add accepting-side verification endpoint.
- [x] Add persistent local recognition policy for verifier defaults.
- [x] Add audit events for trust decisions.

### Phase 5 - Demo

- [x] Run Sovereign A and Sovereign B with separate genesis blocks, NA keys,
      operator keys, policies, and databases.
- [x] Sovereign A issues an attestation for a member.
- [x] Sovereign B accepts it only after recognizing Sovereign A.
- [x] Sovereign A revokes it.
- [x] Sovereign B rejects the same attestation after revocation input.

## Verification Commands

```powershell
python -m pytest genesis_mesh\tests\test_sovereign_trust.py genesis_mesh\tests\test_na_attestations.py -q
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh -q
python docs\examples\assets\scripts\sovereign-attestation-demo.py
git diff --check
```
