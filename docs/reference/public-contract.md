# Public Contract

<!-- Generated from contract/public-surface.json by scripts/render_public_contract.py. Do not edit. -->

This page is the v1 public contract of Genesis Mesh: every HTTP route of the
Network Authority, every CLI command, the public Python API, every signed
artifact and every API error code, each classified as stable, beta or
internal. The source of truth is `contract/public-surface.json`;
`genesis_mesh/tests/test_public_contract.py` fails when the code exposes
anything the contract does not classify, or when a listed item changes or
disappears. Compatibility rules are in `DEPRECATION_POLICY.md`.

| Level | Meaning |
| --- | --- |
| **stable** | Will not break within 1.x. Removed or changed incompatibly only after the deprecation cycle in `DEPRECATION_POLICY.md`. |
| **beta** | Shipped and supported; may change in a minor version with a CHANGELOG notice. |
| **internal** | No compatibility promise. Operator UI pages and implementation details. |

## Packages

| Package | Level | Support |
| --- | --- | --- |
| genesis-mesh (PyPI) (`GenesisMeshLabs/genesismesh`) | stable | The Network Authority, CLI and Python API as classified on this page. Supported deployment profiles: single instance on SQLite, and one or more instances on PostgreSQL (HA). Security fixes for the latest minor version line. |
| ghcr.io/genesismeshlabs/genesis-mesh (container image) (`GenesisMeshLabs/genesismesh`) | stable | The Network Authority and node image for linux/amd64 and linux/arm64, signed keylessly by the publish-image workflow of each release. Stable: the image name; X.Y.Z tags, which are never moved; X.Y and latest, which follow the newest release; SERVICE_ROLE=na and SERVICE_ROLE=node; the environment variables in the configuration reference; the /data state directory, writable by user 10001 and group 0; port 8443; user 10001; the health check; and refusing to start without a genesis block or signing key. The base image and its OS packages are not part of the contract. |
| genesis-mesh-sdk (npm) (`GenesisMeshLabs/sdk-typescript`) | stable | Every stable HTTP route, the governed secret lifecycle (attestation evaluation, policy lifecycle, evidence store, governedAction), HA failover, and offline verification of decisions, agreements, policies, data-usage records and evidence exports. Node.js 22 or newer. |
| github.com/GenesisMeshLabs/sdk-go (`GenesisMeshLabs/sdk-go`) | stable | Stable for its clients (agreement, boundary decide and verify, evidence, attestation, disclosure, consensus, data usage, raw admin calls) and offline verification of agreements, boundary decisions, license policies and data access intents. It does not wrap the policy lifecycle, attestation evaluation or the evidence store; call those routes with raw admin calls. |
| genesismesh-sdk-dotnet (NuGet) (`GenesisMeshLabs/sdk-dotnet`) | stable | Same scope as the Go SDK: its clients and OfflineVerifier are stable; the policy lifecycle, attestation evaluation and evidence store are reached with raw admin calls. .NET 8. |
| genesis-mesh-sdk (Rust crate, Git) (`GenesisMeshLabs/sdk-rust`) | beta | Embeddable portable-trust primitives distributed as a Git dependency, not on crates.io. Not a leg of the interoperability scenario yet. |
| genesis-mesh-gateway (`GenesisMeshLabs/gateway`) | beta | Release binaries on GitHub and the container image below. Not part of the v1 stable contract. |
| ghcr.io/genesismeshlabs/genesis-mesh-gateway (container image) (`GenesisMeshLabs/gateway`) | beta | The gateway and its operator tool for linux/amd64 and linux/arm64, signed keylessly by the gateway distribution workflow of each release, with the same tag rules as the Network Authority image. Beta like the gateway itself. |
| PHP SDK (`GenesisMeshLabs/sdk-php`) | unsupported | Not on the release train (last version 0.56.0); no support or compatibility promise. |

## HTTP routes

| Method | Path | Level |
| --- | --- | --- |
| GET | `/` | internal |
| POST | `/admin/agreements/accept` | stable |
| POST | `/admin/agreements/counter` | stable |
| POST | `/admin/agreements/offer` | stable |
| POST | `/admin/attestations` | stable |
| POST | `/admin/attestations/<attestation_id>/revoke` | stable |
| GET, POST | `/admin/boundary-policies` | stable |
| POST | `/admin/boundary-policies/<policy_id>/activate` | stable |
| POST | `/admin/boundary-policies/<policy_id>/deactivate` | stable |
| GET | `/admin/boundary-policies/<policy_id>/history` | stable |
| GET | `/admin/boundary-policies/active` | stable |
| POST | `/admin/boundary-policies/validate` | stable |
| POST | `/admin/boundary/decide` | beta |
| POST | `/admin/boundary/evaluate` | stable |
| POST | `/admin/consensus/proof` | beta |
| POST | `/admin/consensus/vote` | beta |
| POST | `/admin/data-usage/intent` | stable |
| POST | `/admin/data-usage/policy` | stable |
| POST | `/admin/disclosure/commit` | beta |
| POST | `/admin/disclosure/nullifier` | beta |
| GET | `/admin/evidence` | stable |
| GET, POST | `/admin/evidence/anchors` | beta |
| POST | `/admin/evidence/break-glass/<break_glass_id>/judge` | beta |
| GET | `/admin/evidence/changes/<path:resource_id>` | beta |
| GET, POST | `/admin/evidence/executor-keys` | stable |
| POST | `/admin/evidence/executor-keys/<key_id>/retire` | stable |
| GET | `/admin/evidence/export` | stable |
| POST | `/admin/evidence/observations/<observation_id>/judge` | beta |
| GET | `/admin/evidence/operator-holders` | beta |
| GET | `/admin/evidence/resource-heads/<path:resource_id>` | stable |
| GET | `/admin/evidence/resources/<path:resource_id>` | stable |
| POST | `/admin/evidence/retention/apply` | stable |
| GET | `/admin/evidence/status` | stable |
| GET | `/admin/evidence/vendors/<vendor_id>` | stable |
| GET | `/admin/evidence/verify` | stable |
| POST | `/admin/invite` | stable |
| POST | `/admin/operator-keys/<key_id>/holder` | beta |
| POST | `/admin/operator-keys/<key_id>/revoke` | stable |
| POST | `/admin/operator-keys/holder-changes/<proposal_id>/approve` | beta |
| POST | `/admin/policy` | stable |
| GET | `/admin/policy/history` | stable |
| POST | `/admin/policy/rollback` | stable |
| POST | `/admin/recognition-policy` | stable |
| POST | `/admin/recognition-treaties` | stable |
| POST | `/admin/recognition-treaties/<treaty_id>/revoke` | stable |
| POST | `/admin/revoke` | stable |
| POST | `/admin/sovereign-revocation-feeds/import` | stable |
| POST | `/admin/trust-evidence` | beta |
| GET, POST | `/agents` | beta |
| DELETE, GET | `/agents/<path:node_public_key>` | beta |
| POST | `/agreements/verify` | stable |
| GET | `/api-reference` | internal |
| GET | `/atlas` | internal |
| GET | `/atlas.json` | beta |
| GET | `/attestations` | stable |
| GET | `/attestations/<attestation_id>` | stable |
| POST | `/attestations/verify` | stable |
| POST | `/attestations/verify-with-treaty` | stable |
| POST | `/boundary-policies/verify` | stable |
| POST | `/boundary/verify` | stable |
| GET | `/cli-reference` | internal |
| GET | `/connectome` | internal |
| GET | `/connectome.json` | stable |
| GET | `/connectome/trust-path` | beta |
| POST | `/consensus/verify` | beta |
| GET | `/crl` | stable |
| GET | `/dashboard` | internal |
| GET | `/dashboard.json` | internal |
| GET | `/data-usage/policy` | stable |
| POST | `/data-usage/verify` | stable |
| POST | `/disclosure/prove` | beta |
| POST | `/disclosure/verify` | beta |
| POST | `/evidence/break-glass` | beta |
| POST | `/evidence/execution` | stable |
| POST | `/evidence/observations` | beta |
| POST | `/evidence/observations/batch` | beta |
| GET | `/favicon.ico` | internal |
| GET | `/favicon.svg` | internal |
| GET | `/genesis` | stable |
| GET | `/health` | stable |
| GET | `/healthz` | stable |
| POST | `/heartbeat` | stable |
| POST | `/join` | stable |
| GET | `/metrics` | beta |
| GET | `/nodes` | stable |
| GET | `/operator-console-static/console.js` | internal |
| GET | `/operator-console-static/logo.svg` | internal |
| GET | `/operator-console-static/styles.css` | internal |
| GET | `/policy` | stable |
| GET | `/readyz` | stable |
| GET | `/recognition-graph` | beta |
| GET | `/recognition-policy` | stable |
| GET | `/recognition-treaties` | stable |
| GET | `/recognition-treaties/<treaty_id>` | stable |
| POST | `/recognition-treaties/verify` | stable |
| POST | `/renew` | stable |
| GET | `/sovereign-revocation-feed` | stable |
| GET | `/sovereign.json` | stable |
| GET | `/surfaces` | internal |
| GET | `/swagger.json` | internal |
| POST | `/trust-evidence/verify` | beta |

## Error codes

Every error response is {"error": {"code", "message", "details", "request_id"}}. code is stable; message and details are for people and may change.
Errors derived from a plain HTTP status (not_found, method_not_allowed, request_entity_too_large and other werkzeug status names) use the status name in snake case and are stable.
Every code below is stable: it is never removed or given a new meaning.

`accept_rejected`, `admin_auth_failed`, `admin_auth_throttled`, `agent_not_registered`, `agreement_untrusted`, `ambiguous_basis`, `asset_not_found`, `attestation_issuer_mismatch`, `attestation_not_found`, `bad_request`, `boundary_eval_failed`, `boundary_policy_activation_conflict`, `boundary_policy_activation_refused`, `boundary_policy_integrity_failed`, `boundary_policy_invalid`, `boundary_policy_not_active`, `boundary_policy_not_found`, `boundary_policy_required`, `boundary_policy_version_conflict`, `break_glass_conflict`, `break_glass_invalid_signature`, `break_glass_malformed`, `break_glass_out_of_scope`, `break_glass_secret_material`, `break_glass_unknown_key`, `caller_keys_not_accepted`, `certificate_key_mismatch`, `certificate_not_found`, `certificate_revoked`, `commit_failed`, `conflict`, `context_party_mismatch`, `counter_rejected`, `crl_publish_contention`, `delete_signature_required`, `descriptor_expired`, `descriptor_network_mismatch`, `descriptor_signature_required`, `empty_subject_public_keys`, `evidence_anchor_refused`, `evidence_build_failed`, `evidence_capability_mismatch`, `evidence_chain_gap`, `evidence_chain_mismatch`, `evidence_conflict`, `evidence_decision_denied`, `evidence_decision_mismatch`, `evidence_decision_not_found`, `evidence_invalid_signature`, `evidence_malformed`, `evidence_outside_decision_window`, `evidence_secret_material`, `evidence_store_disabled`, `evidence_store_unavailable`, `evidence_unknown_executor`, `executor_key_exists`, `executor_key_not_found`, `executor_key_retired`, `feed_issuer_mismatch`, `forbidden`, `holder_change_already_approved`, `holder_change_needs_second_holder`, `holder_change_not_found`, `insufficient_operator_tier`, `intent_create_failed`, `internal_server_error`, `invalid_agent_descriptor`, `invalid_agreement`, `invalid_attestation_id`, `invalid_attestation_or_policy`, `invalid_attestation_or_treaty`, `invalid_boundary_policy`, `invalid_break_glass`, `invalid_commitment`, `invalid_context`, `invalid_decision`, `invalid_evidence`, `invalid_holder`, `invalid_input`, `invalid_invite_token`, `invalid_json`, `invalid_json_object`, `invalid_justification`, `invalid_key_role`, `invalid_max_validity_hours`, `invalid_observation`, `invalid_offer`, `invalid_page`, `invalid_policy`, `invalid_policy_version`, `invalid_proof`, `invalid_public_key`, `invalid_public_keys`, `invalid_recipient_public_key`, `invalid_recognition_policy`, `invalid_recognition_treaty`, `invalid_resource_prefix`, `invalid_retention`, `invalid_revocation_reason`, `invalid_role`, `invalid_signature`, `invalid_signed_at`, `invalid_source`, `invalid_sovereign_revocation_feed`, `invalid_threshold`, `invalid_timestamp_order`, `invalid_timestamps`, `invalid_token_expiry_hours`, `invalid_treaty_scope`, `invalid_validity_hours`, `invalid_verdict`, `invalid_vote_type`, `judgement_conflict`, `judgement_subject_not_found`, `justification_untrusted`, `last_active_operator_key`, `missing_accept_fields`, `missing_agreement`, `missing_attestation_subject`, `missing_boundary_fields`, `missing_cert_id`, `missing_certificate_identity`, `missing_commit_fields`, `missing_counter_fields`, `missing_decision`, `missing_evidence`, `missing_executor_key_fields`, `missing_intent_fields`, `missing_invite_token`, `missing_issuer_public_keys`, `missing_node_public_key`, `missing_offer_fields`, `missing_policy`, `missing_policy_fields`, `missing_policy_id`, `missing_proof`, `missing_proof_fields`, `missing_prove_fields`, `missing_recognition_policy`, `missing_signature`, `missing_treaty_subject`, `missing_trust_path_parameters`, `missing_validator_public_keys`, `missing_validity_window`, `missing_verify_fields`, `missing_vote_fields`, `no_policy`, `node_auth_failed`, `node_has_no_active_certificate`, `node_key_compromised`, `node_key_revoked`, `not_found`, `nullifier_failed`, `observation_conflict`, `observation_invalid_signature`, `observation_malformed`, `observation_out_of_scope`, `observation_secret_material`, `observation_unknown_key`, `offer_rejected`, `out_of_band_disabled`, `policy_not_found`, `policy_sign_failed`, `proof_assembly_failed`, `prove_failed`, `rate_limit_exceeded`, `recognition_policy_not_configured`, `renewal_role_change_forbidden`, `request_validation_failed`, `resource_chain_gap`, `resource_chain_mismatch`, `resource_not_found`, `retention_in_progress`, `service_not_ready`, `service_unavailable`, `signed_at_outside_window`, `stale_sequence`, `treaty_not_found`, `unauthorized`, `unexpected_field`, `unknown_operator_key`, `validation_failed`, `vendor_not_found`, `vote_failed`, `wrong_issuer`

## Signed artifacts

Each is signed over its canonical form without the signature field (see
RFC-001, *Canonical JSON and signatures*, and `DEPRECATION_POLICY.md` for how
signed formats evolve).

| Model | Signature field | Level |
| --- | --- | --- |
| `genesis_mesh.models.agreement:AgreementRecord` | `signatures` | stable |
| `genesis_mesh.models.agreement:CapabilityCounter` | `signatures` | stable |
| `genesis_mesh.models.agreement:CapabilityOffer` | `signatures` | stable |
| `genesis_mesh.models.atlas:GraphPruningPolicy` | `signature` | beta |
| `genesis_mesh.models.atlas:PrunedAtlasExport` | `signature` | beta |
| `genesis_mesh.models.atlas:TrustPathCache` | `signature` | beta |
| `genesis_mesh.models.atlas:TrustPathEntry` | `signature` | beta |
| `genesis_mesh.models.attestation:AttestationPolicy` | `signature` | beta |
| `genesis_mesh.models.attestation:ModelAttestation` | `signature` | beta |
| `genesis_mesh.models.boundary_policy:BoundaryPolicy` | `signature` | stable |
| `genesis_mesh.models.certificates:JoinCertificate` | `signatures` | stable |
| `genesis_mesh.models.certificates:ServiceManifest` | `signatures` | beta |
| `genesis_mesh.models.consensus:ConsensusProof` | `signature` | beta |
| `genesis_mesh.models.consensus:EphemeralExecutionIdentity` | `signature` | beta |
| `genesis_mesh.models.consensus:ValidatorVote` | `signature` | beta |
| `genesis_mesh.models.context:BoundaryDecision` | `signature` | stable |
| `genesis_mesh.models.context_integrity:ContextAppendSegment` | `signature` | beta |
| `genesis_mesh.models.context_integrity:ContextIntegrityRecord` | `signature` | beta |
| `genesis_mesh.models.control_plane:ControlMessageModel` | `signatures` | beta |
| `genesis_mesh.models.data_usage:DataAccessIntent` | `signature` | stable |
| `genesis_mesh.models.data_usage:DataAccessRecord` | `signature` | beta |
| `genesis_mesh.models.data_usage:DataLicensePolicy` | `signature` | stable |
| `genesis_mesh.models.delegation:DelegatedAgreementRecord` | `signatures` | beta |
| `genesis_mesh.models.discovery:AgentDescriptor` | `signatures` | beta |
| `genesis_mesh.models.evidence:TrustEvidence` | `signatures` | beta |
| `genesis_mesh.models.evidence_store:RetentionCheckpoint` | `signature` | stable |
| `genesis_mesh.models.evidence_store:StoreAnchor` | `signature` | stable |
| `genesis_mesh.models.execution:ExecutionEvidence` | `signature` | stable |
| `genesis_mesh.models.freshness:FreshnessProof` | `signature` | stable |
| `genesis_mesh.models.genesis:GenesisBlock` | `signatures` | stable |
| `genesis_mesh.models.invocation_token:InvocationToken` | `signature` | beta |
| `genesis_mesh.models.invocation_token:InvocationUseRecord` | `signature` | beta |
| `genesis_mesh.models.justification:JustificationProof` | `signature` | stable |
| `genesis_mesh.models.mediation:ExecutionMediationRequest` | `signature` | beta |
| `genesis_mesh.models.mediation:MediatedExecutionReceipt` | `signature` | beta |
| `genesis_mesh.models.out_of_band:BreakGlassRecord` | `signature` | stable |
| `genesis_mesh.models.out_of_band:JudgementRecord` | `signature` | stable |
| `genesis_mesh.models.out_of_band:ObservationRecord` | `signature` | stable |
| `genesis_mesh.models.out_of_band:QuarantineRecord` | `signature` | stable |
| `genesis_mesh.models.out_of_band:RegistryRecord` | `signature` | stable |
| `genesis_mesh.models.overlay_discovery:DiscoveryFeed` | `signature` | beta |
| `genesis_mesh.models.overlay_discovery:OverlayDiscoveryRecord` | `signature` | beta |
| `genesis_mesh.models.oversight:HumanOversightPolicy` | `signature` | beta |
| `genesis_mesh.models.policy:PolicyManifest` | `signatures` | stable |
| `genesis_mesh.models.privacy:CommunicationPrivacyProfile` | `signature` | beta |
| `genesis_mesh.models.privacy:MetadataEnvelope` | `signature` | beta |
| `genesis_mesh.models.purge:NullificationReceipt` | `signature` | beta |
| `genesis_mesh.models.purge:NullificationRegistryRoot` | `signature` | beta |
| `genesis_mesh.models.purge:PurgePolicy` | `signature` | beta |
| `genesis_mesh.models.revocation:CertificateRevocationList` | `signatures` | stable |
| `genesis_mesh.models.risk_signal:PeerRiskSignal` | `signature` | beta |
| `genesis_mesh.models.risk_signal:RiskSignalUpdate` | `signature` | beta |
| `genesis_mesh.models.selective_disclosure:CapabilityCommitment` | `signature` | beta |
| `genesis_mesh.models.selective_disclosure:CapabilityNullifier` | `signature` | beta |
| `genesis_mesh.models.sovereign:MembershipAttestation` | `signatures` | stable |
| `genesis_mesh.models.sovereign:RecognitionTreaty` | `signatures` | stable |
| `genesis_mesh.models.sovereign:SovereignRevocationFeed` | `signatures` | stable |

## CLI commands

| Command | Level |
| --- | --- |
| `genesis-mesh admin invite` | stable |
| `genesis-mesh admin revoke` | stable |
| `genesis-mesh admin revoke-operator-key` | stable |
| `genesis-mesh atlas build` | beta |
| `genesis-mesh atlas cache` | beta |
| `genesis-mesh atlas lookup` | beta |
| `genesis-mesh atlas prune` | beta |
| `genesis-mesh attestation issue` | beta |
| `genesis-mesh attestation revoke` | beta |
| `genesis-mesh attestation verify-with-treaty` | beta |
| `genesis-mesh dev down` | beta |
| `genesis-mesh dev up` | stable |
| `genesis-mesh discover` | beta |
| `genesis-mesh evidence anchors fetch` | beta |
| `genesis-mesh evidence verify-export` | stable |
| `genesis-mesh federation bootstrap` | stable |
| `genesis-mesh fleet generate` | beta |
| `genesis-mesh fleet mesh` | beta |
| `genesis-mesh fleet status` | beta |
| `genesis-mesh fleet verify` | beta |
| `genesis-mesh genesis create` | stable |
| `genesis-mesh genesis sign` | stable |
| `genesis-mesh genesis verify` | stable |
| `genesis-mesh info` | beta |
| `genesis-mesh init` | stable |
| `genesis-mesh join` | stable |
| `genesis-mesh keygen network-authority` | stable |
| `genesis-mesh keygen node` | stable |
| `genesis-mesh keygen operator` | stable |
| `genesis-mesh keygen root` | stable |
| `genesis-mesh managed audit-export` | beta |
| `genesis-mesh managed backup` | beta |
| `genesis-mesh managed restore` | beta |
| `genesis-mesh na migrate-db` | stable |
| `genesis-mesh na start` | stable |
| `genesis-mesh na verify-db` | stable |
| `genesis-mesh proof canary` | beta |
| `genesis-mesh proof cleanup` | beta |
| `genesis-mesh proof inspect` | beta |
| `genesis-mesh proof remote` | beta |
| `genesis-mesh send` | beta |
| `genesis-mesh sovereign inspect` | stable |
| `genesis-mesh status` | stable |
| `genesis-mesh supply-chain verify` | beta |
| `genesis-mesh treaty import-feed` | beta |
| `genesis-mesh treaty inspect` | stable |
| `genesis-mesh treaty list` | stable |
| `genesis-mesh treaty renew` | stable |
| `genesis-mesh treaty replace` | stable |
| `genesis-mesh treaty revoke` | stable |
| `genesis-mesh trust agree accept` | stable |
| `genesis-mesh trust agree cosign` | stable |
| `genesis-mesh trust agree counter` | stable |
| `genesis-mesh trust agree offer` | stable |
| `genesis-mesh trust agree verify` | stable |
| `genesis-mesh trust attest create` | beta |
| `genesis-mesh trust attest policy` | beta |
| `genesis-mesh trust attest verify` | beta |
| `genesis-mesh trust boundary-policy explain` | stable |
| `genesis-mesh trust boundary-policy gate-types` | stable |
| `genesis-mesh trust boundary-policy validate` | stable |
| `genesis-mesh trust boundary-policy verify` | stable |
| `genesis-mesh trust consensus assemble` | beta |
| `genesis-mesh trust consensus assess-cascade` | beta |
| `genesis-mesh trust consensus issue-identity` | beta |
| `genesis-mesh trust consensus verify` | beta |
| `genesis-mesh trust consensus verify-identity` | beta |
| `genesis-mesh trust consensus vote` | beta |
| `genesis-mesh trust context evaluate` | stable |
| `genesis-mesh trust context request` | stable |
| `genesis-mesh trust context verify` | stable |
| `genesis-mesh trust data intent` | stable |
| `genesis-mesh trust data policy` | stable |
| `genesis-mesh trust data record` | beta |
| `genesis-mesh trust data verify` | stable |
| `genesis-mesh trust decide` | beta |
| `genesis-mesh trust delegate cosign` | beta |
| `genesis-mesh trust delegate create` | beta |
| `genesis-mesh trust delegate verify` | beta |
| `genesis-mesh trust disclose commit` | beta |
| `genesis-mesh trust disclose nullify` | beta |
| `genesis-mesh trust disclose prove` | beta |
| `genesis-mesh trust disclose verify` | beta |
| `genesis-mesh trust discover announce` | beta |
| `genesis-mesh trust discover feed` | beta |
| `genesis-mesh trust discover merge` | beta |
| `genesis-mesh trust discover verify` | beta |
| `genesis-mesh trust evidence` | beta |
| `genesis-mesh trust execution record` | beta |
| `genesis-mesh trust execution verify` | beta |
| `genesis-mesh trust freshness issue` | beta |
| `genesis-mesh trust freshness verify` | beta |
| `genesis-mesh trust guard request` | beta |
| `genesis-mesh trust guard start` | beta |
| `genesis-mesh trust guard verify` | beta |
| `genesis-mesh trust integrity commit` | beta |
| `genesis-mesh trust integrity verify` | beta |
| `genesis-mesh trust interop to-jwt` | beta |
| `genesis-mesh trust interop to-spiffe` | beta |
| `genesis-mesh trust interop to-vc` | beta |
| `genesis-mesh trust justify sign` | beta |
| `genesis-mesh trust justify verify` | beta |
| `genesis-mesh trust oversight approve` | beta |
| `genesis-mesh trust oversight evaluate` | beta |
| `genesis-mesh trust oversight propose` | beta |
| `genesis-mesh trust oversight reject` | beta |
| `genesis-mesh trust oversight verify` | beta |
| `genesis-mesh trust privacy apply` | beta |
| `genesis-mesh trust privacy profile` | beta |
| `genesis-mesh trust privacy scan` | beta |
| `genesis-mesh trust purge prove` | beta |
| `genesis-mesh trust purge receipt` | beta |
| `genesis-mesh trust purge register` | beta |
| `genesis-mesh trust purge verify` | beta |
| `genesis-mesh trust risk assess-seed` | beta |
| `genesis-mesh trust risk create` | beta |
| `genesis-mesh trust risk decay` | beta |
| `genesis-mesh trust risk show` | beta |
| `genesis-mesh trust risk update` | beta |
| `genesis-mesh trust token issue` | beta |
| `genesis-mesh trust token record-use` | beta |
| `genesis-mesh trust token verify` | beta |
| `genesis-mesh trust verify-evidence` | beta |
| `genesis-mesh trust-bundle export` | stable |
| `genesis-mesh trust-bundle import` | stable |
| `genesis-mesh trust-bundle inspect` | stable |
| `genesis-mesh trust-bundle validate` | stable |

## Python API

Symbols not listed are internal. Parameters are listed in order;
`*` marks keyword-only parameters and `?` optional ones.

| Symbol | Parameters | Level |
| --- | --- | --- |
| `genesis_mesh.crypto:generate_keypair` | (none) | stable |
| `genesis_mesh.crypto:sign_model` | model, private_key, key_id | stable |
| `genesis_mesh.crypto:verify_model_signature` | model, signature, public_key | stable |
| `genesis_mesh.crypto:sign_data` | data, private_key | stable |
| `genesis_mesh.crypto:verify_signature` | data, signature_b64, public_key | stable |
| `genesis_mesh.crypto:load_private_key` | path | stable |
| `genesis_mesh.models:SovereignIdentity` | model | stable |
| `genesis_mesh.models:MembershipAttestation` | model | stable |
| `genesis_mesh.models:RecognitionTreaty` | model | stable |
| `genesis_mesh.models:RecognitionTreatyScope` | model | stable |
| `genesis_mesh.models:SovereignRevocationFeed` | model | stable |
| `genesis_mesh.models:GenesisBlock` | model | stable |
| `genesis_mesh.models:Signature` | model | stable |
| `genesis_mesh.models:ContextRecord` | model | stable |
| `genesis_mesh.models:BoundaryPolicy` | model | stable |
| `genesis_mesh.models:PolicySelector` | model | stable |
| `genesis_mesh.models:GateSpec` | model | stable |
| `genesis_mesh.models:PolicyBinding` | model | stable |
| `genesis_mesh.models:AppliedPolicy` | model | stable |
| `genesis_mesh.models:PolicyGateEvaluation` | model | stable |
| `genesis_mesh.models:AttestationBinding` | model | stable |
| `genesis_mesh.models:EvidenceStoreEntry` | model | stable |
| `genesis_mesh.models:RetentionCheckpoint` | model | stable |
| `genesis_mesh.models:EvidenceEvent` | model | stable |
| `genesis_mesh.models:AgreementRecord` | model | stable |
| `genesis_mesh.models:CapabilityOffer` | model | stable |
| `genesis_mesh.models:CapabilityCounter` | model | stable |
| `genesis_mesh.models.execution:ExecutionEvidence` | model | stable |
| `genesis_mesh.models.context:BoundaryDecision` | model | stable |
| `genesis_mesh.models.justification:JustificationProof` | model | stable |
| `genesis_mesh.trust.treaty:verify_recognition_treaty` | treaty, issuer_public_keys, *expected_issuer_sovereign_id?, *expected_subject_sovereign_id?, *revoked_treaty_ids?, *current_time? | stable |
| `genesis_mesh.trust.treaty:verify_attestation_with_treaty` | attestation, treaty, treaty_issuer_public_keys, *revoked_treaty_ids?, *revoked_attestation_ids?, *current_time? | stable |
| `genesis_mesh.trust.treaty:verify_sovereign_revocation_feed` | feed, issuer_public_keys, *expected_issuer_sovereign_id?, *min_sequence? | stable |
| `genesis_mesh.trust.attestation:verify_membership_attestation` | attestation, policy, current_time? | stable |
| `genesis_mesh.trust.decision:evaluate_trust_decision` | graph, source_sovereign_id, target_sovereign_id, *requested_roles?, *now? | stable |
| `genesis_mesh.trust.agreement:AgreementTerms` | model | stable |
| `genesis_mesh.trust.agreement:build_offer` | offerer_sovereign_id, responder_sovereign_id, requested_terms, graph, signing_key, *issued_by, *expires_at, *now? | stable |
| `genesis_mesh.trust.agreement:build_counter` | offer, offered_terms, graph, signing_key, *issued_by, *now? | stable |
| `genesis_mesh.trust.agreement:accept_offer` | offer, graph, signing_key, *issued_by, *now? | stable |
| `genesis_mesh.trust.agreement:accept_counter` | counter, original_offer, signing_key, *issued_by, *now? | stable |
| `genesis_mesh.trust.agreement:cosign_agreement` | record, signing_key, *issued_by | stable |
| `genesis_mesh.trust.agreement:verify_agreement` | record, offerer_public_keys, responder_public_keys, *expected_graph_digest? | stable |
| `genesis_mesh.trust.context:verify_boundary_decision` | decision, operator_public_keys, *freshness_proof_issuer_keys?, *now?, *expected_policies?, *expected_attestation? | stable |
| `genesis_mesh.trust.context:sign_boundary_policy` | policy, signing_key, issued_by | stable |
| `genesis_mesh.trust.context:verify_boundary_policy` | policy, public_keys | stable |
| `genesis_mesh.trust.context:validate_boundary_policy` | policy, registry | stable |
| `genesis_mesh.trust.evidence_store:verify_evidence_events` | events, *na_public_keys, *executor_keys, *contiguous?, *checkpoint? | stable |
| `genesis_mesh.trust.evidence_store:check_metadata_only` | evidence | stable |
| `genesis_mesh.trust.data_usage:DataLicensePolicy` | model | stable |
| `genesis_mesh.trust.data_usage:DataSourceDescriptor` | model | stable |
| `genesis_mesh.trust.data_usage:DataAccessIntent` | model | stable |
| `genesis_mesh.trust.data_usage:create_data_access_intent` | agent_sovereign_id, decision_id, sources, access_types, signing_key, *estimated_volume_bytes?, *valid_for_seconds?, *now? | stable |
| `genesis_mesh.trust.data_usage:verify_data_access_intent` | intent, policy, agent_public_keys, *at_time? | stable |
| `genesis_mesh.trust.context:BoundaryEngine` | operator_sovereign_id, *decision_valid_seconds?, *require_freshness_proof? | beta |
| `genesis_mesh.trust.context:GateRegistry` | (none) | beta |
| `genesis_mesh.trust.context:resolve_policies` | active, context, registry, public_keys, now, *integrity_failures? | beta |
| `genesis_mesh.trust.context:assess_attestation_basis` | attestation_id, attestation, *issuer_public_keys, *stored_status, *feed_revoked, *revocation_seq_checked, *requester_id | beta |
| `genesis_mesh.trust.invocation_token:issue_invocation_token` | agreement, bearer_sovereign_id, capabilities, signing_key, *issued_by, *valid_for_seconds?, *max_invocations?, *policy_constraints?, *delegation?, *now? | beta |
| `genesis_mesh.trust.invocation_token:verify_invocation_token` | token, issuer_public_keys, *requested_capability, *bearer_sovereign_id, *use_records?, *at_time? | beta |
| `genesis_mesh.trust.logic_attestation:create_model_attestation` | agent_sovereign_id, model_id, model_version_tag, system_prompt, tool_ids, signing_key, *token_id?, *valid_for_seconds?, *now? | beta |
| `genesis_mesh.trust.logic_attestation:verify_model_attestation` | attestation, policy, agent_public_keys, *at_time? | beta |
| `genesis_mesh.trust.evidence:build_trust_evidence` | decision, issuer_sovereign_id, graph_digest, issued_by, signing_key, *metadata?, *now? | beta |
| `genesis_mesh.trust.evidence:verify_trust_evidence` | evidence, issuer_public_keys, *expected_graph_digest? | beta |
| `genesis_mesh.trust.selective_disclosure:commit_capabilities` | capabilities, agreement, signing_key, *issued_by, *now? | beta |
| `genesis_mesh.trust.selective_disclosure:prove_capability_membership` | capability, capabilities, commitment, prover_sovereign_id, *now? | beta |
| `genesis_mesh.trust.selective_disclosure:verify_capability_proof` | proof, commitment, issuer_public_keys, *nullifier?, *used_nullifiers?, *now? | beta |
| `genesis_mesh.trust.selective_disclosure:issue_nullifier` | proof, signing_key, *issued_by, *valid_for_seconds?, *now? | beta |
| `genesis_mesh.trust.consensus:cast_validator_vote` | justification_proof, validator_sovereign_id, vote, signing_key, *reason?, *context_digest?, *now? | beta |
| `genesis_mesh.trust.consensus:assemble_consensus_proof` | justification_proof, votes, required_threshold, validator_sovereign_ids, assembler_signing_key, *issued_by, *valid_for_seconds?, *cascade_threshold?, *expected_deliberation_seconds?, *now? | beta |
| `genesis_mesh.trust.consensus:verify_consensus_proof` | proof, validator_public_keys, assembler_public_keys, *justification_proof?, *cascade_threshold?, *expected_deliberation_seconds?, *at_time? | beta |
| `genesis_mesh.trust.connectome:build_connectome_view` | graph | beta |
| `genesis_mesh.trust.risk_signal:create_risk_signal` | from_sovereign_id, to_sovereign_id, signing_key, *initial_signal?, *alpha?, *decay_lambda?, *now? | beta |
| `genesis_mesh.trust.risk_signal:update_risk_signal` | signal, evidence, signing_key, *history?, *anomaly_sigma_threshold?, *now? | beta |
| `genesis_mesh.trust.risk_signal:decay_risk_signal` | signal, signing_key, *now? | beta |
| `genesis_mesh.na_service.key_provider:Signer` | signing_key, key_id, provider | beta |
| `genesis_mesh.na_service.key_provider:load_signer` | config, *http_get?, *environ? | beta |
| `genesis_mesh.na_service.key_provider:KeyProviderConfig` | provider?, key_id?, key_file?, seed_env_var?, vault_url?, secret_name? | beta |
| `genesis_mesh.workflows.db_migration:verify_database` | db, na_public_key? | beta |
| `genesis_mesh.workflows.db_migration:migrate_sqlite_to_postgres` | sqlite_path, database_url, *na_public_key? | beta |
