# Public API Stability

Genesis Mesh v0.51.0 introduces its first versioned stability contract.
Symbols listed on this page are **stable**: they will not be removed or
have their signatures changed in a breaking way without a deprecation
period as defined in `DEPRECATION_POLICY.md` at the repository root.

Symbols not listed here are **internal**. They may change at any time.

---

## Stability levels

| Level | Meaning |
|-------|---------|
| **stable** | Will not break across minor versions. Removed only after a full deprecation cycle. |
| **beta** | Shape is settled but may change in a minor version with a changelog notice. |
| **internal** | No stability guarantee. May change or disappear in any release. |

---

## CLI (stable)

All subcommands reachable from `genesis-mesh` and `genesis-mesh-na`.

| Command | Since |
|---------|-------|
| `genesis-mesh init` | v0.3.0 |
| `genesis-mesh na start` | v0.4.0 |
| `genesis-mesh na stop` | v0.4.0 |
| `genesis-mesh join` | v0.5.0 |
| `genesis-mesh status` | v0.5.0 |
| `genesis-mesh admin invite` | v0.7.0 |
| `genesis-mesh admin revoke` | v0.10.0 |
| `genesis-mesh dev up` | v0.13.0 |
| `genesis-mesh fleet` | v0.23.0 |
| `genesis-mesh trust evaluate` | v0.32.0 |
| `genesis-mesh trust path` | v0.32.0 |
| `genesis-mesh trust connectome` | v0.35.0 |

---

## Python API (stable)

### `genesis_mesh.crypto`

| Symbol | Since |
|--------|-------|
| `sign_model(model, signing_key, *, key_id)` | v0.9.0 |
| `verify_model_signature(model, signature, public_key)` | v0.9.0 |
| `load_private_key(path)` | v0.9.0 |

### `genesis_mesh.trust.treaty`

| Symbol | Since |
|--------|-------|
| `RecognitionTreaty` | v0.9.0 |
| `MembershipAttestation` | v0.9.0 |
| `SovereignRevocationFeed` | v0.10.0 |
| `verify_recognition_treaty(treaty, issuer_public_keys, *, expected_issuer_sovereign_id, expected_subject_sovereign_id, current_time)` | v0.9.0 |
| `verify_sovereign_revocation_feed(feed, issuer_public_keys, *, expected_issuer_sovereign_id)` | v0.10.0 |

### `genesis_mesh.trust.decision`

| Symbol | Since |
|--------|-------|
| `TrustDecision` | v0.32.0 |
| `evaluate_trust_decision(graph, source_sovereign_id, target_sovereign_id, *, requested_roles, now)` | v0.32.0 |
| `explain_trust_path(graph, source_sovereign_id, target_sovereign_id)` | v0.35.0 |

### `genesis_mesh.trust.agreement`

| Symbol | Since |
|--------|-------|
| `AgreementTerms` | v0.26.0 |
| `CapabilityOffer` | v0.26.0 |
| `CapabilityCounter` | v0.26.0 |
| `AgreementRecord` | v0.26.0 |
| `build_offer(offerer_sovereign_id, responder_sovereign_id, requested_terms, graph, signing_key, *, issued_by, expires_at, now)` | v0.26.0 |
| `build_counter(offer, offered_terms, graph, signing_key, *, issued_by, now)` | v0.26.0 |
| `accept_offer(offer, graph, signing_key, *, issued_by, now)` | v0.26.0 |
| `accept_counter(counter, original_offer, signing_key, *, issued_by, now)` | v0.26.0 |
| `verify_agreement(agreement, issuer_public_keys, *, at_time)` | v0.26.0 |

### `genesis_mesh.trust.invocation_token`

| Symbol | Since |
|--------|-------|
| `InvocationToken` | v0.32.0 |
| `issue_invocation_token(agreement, bearer_sovereign_id, capabilities, signing_key, *, issued_by, valid_for_seconds, max_invocations, now)` | v0.32.0 |
| `verify_invocation_token(token, issuer_public_keys, *, requested_capability, bearer_sovereign_id, use_records, at_time)` | v0.32.0 |

### `genesis_mesh.trust.logic_attestation`

| Symbol | Since |
|--------|-------|
| `ModelAttestation` | v0.34.0 |
| `AttestationPolicy` | v0.34.0 |
| `create_model_attestation(agent_sovereign_id, model_id, model_version_tag, system_prompt, tool_ids, signing_key, *, token_id, valid_for_seconds, now)` | v0.34.0 |
| `verify_model_attestation(attestation, policy, agent_public_keys, *, at_time)` | v0.34.0 |

### `genesis_mesh.trust.evidence`

| Symbol | Since |
|--------|-------|
| `TrustEvidence` | v0.36.0 |
| `build_trust_evidence(decision, issuer_sovereign_id, graph_digest, issued_by, signing_key, *, now)` | v0.36.0 |
| `verify_trust_evidence(evidence, issuer_public_keys, *, expected_graph_digest)` | v0.36.0 |

### `genesis_mesh.trust.selective_disclosure`

| Symbol | Since |
|--------|-------|
| `CapabilityCommitment` | v0.33.0 |
| `CapabilityMembershipProof` | v0.33.0 |
| `commit_capabilities(capabilities, agreement, signing_key, *, issued_by, now)` | v0.33.0 |
| `prove_capability_membership(capability, capabilities, commitment, prover_sovereign_id, *, now)` | v0.33.0 |
| `verify_capability_proof(proof, commitment, issuer_public_keys, *, nullifier, used_nullifiers)` | v0.33.0 |
| `issue_nullifier(proof, signing_key, *, issued_by, now)` | v0.33.0 |

### `genesis_mesh.trust.justification`

| Symbol | Since |
|--------|-------|
| `GateTrace` | v0.32.0 |
| `BoundaryDecision` | v0.32.0 |
| `JustificationProof` | v0.32.0 |
| `sign_justification_proof(trace, decision, signing_key, *, issued_by, now)` | v0.32.0 |

### `genesis_mesh.trust.consensus`

| Symbol | Since |
|--------|-------|
| `cast_validator_vote(justification_proof, validator_sovereign_id, vote, signing_key, *, reason, context_digest, now)` | v0.37.0 |
| `assemble_consensus_proof(justification_proof, votes, required_threshold, validator_sovereign_ids, assembler_signing_key, *, issued_by, valid_for_seconds, cascade_threshold, expected_deliberation_seconds, now)` | v0.37.0 |
| `verify_consensus_proof(proof, validator_public_keys, assembler_public_keys, *, justification_proof, cascade_threshold, expected_deliberation_seconds, at_time)` | v0.37.0 |

### `genesis_mesh.trust.data_usage`

| Symbol | Since |
|--------|-------|
| `DataLicensePolicy` | v0.48.0 |
| `DataSourceDescriptor` | v0.48.0 |
| `DataAccessIntent` | v0.48.0 |
| `create_data_access_intent(agent_sovereign_id, decision_id, sources, access_types, signing_key, *, estimated_volume_bytes, valid_for_seconds, now)` | v0.48.0 |
| `verify_data_access_intent(intent, policy, agent_public_keys, *, at_time)` | v0.48.0 |

### `genesis_mesh.trust.connectome`

| Symbol | Since |
|--------|-------|
| `build_connectome_view(graph)` | v0.35.0 |
| `explain_trust_path(graph, source_sovereign_id, target_sovereign_id)` | v0.35.0 |

---

## Python API (beta)

These symbols are shipped and in active use but may evolve in minor versions.

| Symbol | Module | Note |
|--------|--------|------|
| `PeerRiskSignal` | `genesis_mesh.trust.risk_signal` | shape may refine in v0.52 |
| `build_risk_signal(...)` | `genesis_mesh.trust.risk_signal` | same |
| `BoundaryEngine` | `genesis_mesh.trust.context` | gate extension API may grow |

---

## Conformance vectors

The reference implementation produces deterministic output for every stable
API above.  Vector files live in `conformance/vectors/` and are validated
by `pytest genesis_mesh/tests/test_conformance.py`.

Alternative implementations must pass all vectors to claim conformance.
See `conformance/CONFORMANCE.md` for instructions.
