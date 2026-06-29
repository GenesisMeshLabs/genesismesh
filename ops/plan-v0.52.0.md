# v0.52.0 Plan -- Trust API Surface (NA HTTP Endpoints)

## Positioning

The Python trust library (v0.51) exposes a complete, stable API for every
protocol operation: agreement negotiation, boundary decisions, trust evidence,
selective disclosure, consensus proofs, and data usage intents.

The SDK tier (v0.53 TypeScript, v0.54 Go, v0.55 C#) needs a stable HTTP
surface to call.  Without it, each SDK would need to embed its own
cryptography, reimplementing what the Python library already provides correctly.

v0.52 adds the missing Network Authority HTTP routes so that the SDKs are
HTTP clients over a well-tested Python server, not independent protocol
reimplementations.

v0.52 should prove:

> Every SDK-required stable protocol operation can be invoked or verified
> over HTTP against a running Network Authority, with JSON request/response
> bodies that match the protocol models exactly.

## Design

Six new route blueprints, one per missing sub-client domain:

| Blueprint file | Routes prefix | Operations |
|---|---|---|
| `routes/agreement.py` | `/agreements/` | offer, counter, accept, verify |
| `routes/boundary.py` | `/boundary/` | decide, verify |
| `routes/evidence.py` | `/trust-evidence/` | build, verify |
| `routes/disclosure.py` | `/disclosure/` | commit, prove, verify, nullifier |
| `routes/consensus.py` | `/consensus/` | vote, proof, verify |
| `routes/data_usage.py` | `/data-usage/` | policy (admin), intent, verify |

### Auth pattern

Follows the existing pattern from `routes/attestations.py` and
`routes/treaties.py`:

- **Admin / signing routes** (`POST /admin/...`): require a valid operator
  signature verified by `verify_admin_request`. The NA signs output using
  its stored `na_private_key`.
- **Verification routes** (`POST .../verify`, `GET .../policy`): unauthenticated.
  These are stateless cryptographic checks; anyone can call them.
- **`POST /disclosure/prove`**: unauthenticated — all inputs are caller-supplied
  and no NA state is used. The output is a Merkle proof, not a signed artifact.

### Signing security constraint

Admin routes that produce signed artifacts follow one rule:

> The caller declares **intent** (parameters and identifiers).
> The NA constructs the canonical protocol artifact from those parameters
> and signs it.  The NA never signs a caller-provided pre-built model.

This applies specifically to offer, counter, accept, trust-evidence, disclosure
commit, consensus vote/proof, data-usage policy, and data-usage intent.
Verification routes accept full models as input because they are reading, not
signing.

### Agreement routes

```
POST /admin/agreements/offer
     Body: {responder_sovereign_id, capabilities, scope, valid_from, valid_until, expires_at}
     → CapabilityOffer (signed by NA as offerer)

POST /admin/agreements/counter
     Body: {offer: CapabilityOffer, capabilities, scope, valid_from, valid_until}
     → CapabilityCounter (signed by NA as counter-offerer)

POST /admin/agreements/accept
     Body: {offer: CapabilityOffer} | {counter: CapabilityCounter, original_offer: CapabilityOffer}
     → AgreementRecord (signed by NA as acceptor)

POST /agreements/verify
     Body: {agreement: AgreementRecord, issuer_public_keys: [str]}
     → {accepted: bool, reason: str}
```

The NA uses its own recognition graph export (from `service.export_recognition_graph()`)
to supply the `graph` parameter for offer/counter/accept calls.

### Boundary routes

```
POST /admin/boundary/decide
     Body: {agreement: AgreementRecord, capability: str, context?: dict}
     → BoundaryDecision (signed by NA as operator)

POST /boundary/verify
     Body: {decision: BoundaryDecision, issuer_public_keys: [str]}
     → {valid: bool, reason: str}
```

### Trust evidence routes

```
POST /admin/trust-evidence
     Body: {decision: TrustDecision, graph_digest?: str}
     → TrustEvidence (signed by NA)

POST /trust-evidence/verify
     Body: {evidence: TrustEvidence, issuer_public_keys: [str], expected_graph_digest?: str}
     → {accepted: bool, reason: str, verdict: str}
```

### Disclosure routes

```
POST /admin/disclosure/commit
     Body: {capabilities: [str], agreement: AgreementRecord}
     → CapabilityCommitment (signed by NA)

POST /disclosure/prove
     Body: {capability: str, capabilities: [str], commitment: CapabilityCommitment,
            prover_sovereign_id: str}
     → CapabilityMembershipProof

POST /disclosure/verify
     Body: {proof: CapabilityMembershipProof, commitment: CapabilityCommitment,
            issuer_public_keys: [str]}
     → {valid: bool, reason: str}

POST /admin/disclosure/nullifier
     Body: {proof: CapabilityMembershipProof}
     → CapabilityNullifier (signed by NA)
```

### Consensus routes

```
POST /admin/consensus/vote
     Body: {justification_proof: JustificationProof, vote: bool, reason?: str}
     → ValidatorVote (signed by NA as validator)

POST /admin/consensus/proof
     Body: {justification_proof: JustificationProof, votes: [ValidatorVote],
            required_threshold: int, validator_sovereign_ids: [str]}
     → ConsensusProof (signed by NA as assembler)

POST /consensus/verify
     Body: {proof: ConsensusProof, validator_public_keys: {id: key},
            assembler_public_keys: [str]}
     → {valid: bool, reason: str}
```

### Data usage routes

```
POST /admin/data-usage/policy
     Body: DataLicensePolicy fields
     → DataLicensePolicy (signed by NA as licensor)

GET  /data-usage/policy
     → DataLicensePolicy (current stored policy, or 404)

POST /admin/data-usage/intent
     Body: {sources: [DataSourceDescriptor], access_types: [str],
            decision_id?: str, estimated_volume_bytes?: int}
     → DataAccessIntent (signed by NA as agent)

POST /data-usage/verify
     Body: {intent: DataAccessIntent, policy: DataLicensePolicy,
            agent_public_keys: [str]}
     → {valid: bool, violation_count: int, violations: [...]}
```

### Error responses

All routes return consistent JSON errors:

```json
{"error": "missing_field", "detail": "capabilities is required"}
```

HTTP status codes follow REST conventions:
- 400 Bad Request — missing or malformed input
- 401 Unauthorized — invalid or missing operator signature (admin routes)
- 422 Unprocessable Entity — input is well-formed but semantically invalid
- 500 Internal Server Error — unexpected failure in the trust library

## HTTP API documentation

`docs/api/trust-http.md` lists every route with: auth required, request
shape, response shape, error codes, and a curl example.  SDK authors and
operators use this page instead of reading source.

## Success Criteria

- [ ] 6 new route files under `genesis_mesh/na_service/routes/`
- [ ] All routes registered in `server.py`
- [ ] All admin routes verified with `verify_admin_request`
- [ ] All verification routes unauthenticated
- [ ] `docs/api/trust-http.md` with route, auth, request, response, error codes, curl example for every endpoint
- [ ] Tests in `genesis_mesh/tests/test_na_trust_api.py`: >= 30 tests, all pass
- [ ] Full pytest suite passes (1043 + new tests)
- [ ] Sphinx build clean with `-W`

## Release Gate

- [ ] Version bumped to `0.52.0`
- [ ] CHANGELOG entry
- [ ] `docs/development/history.md` updated
- [ ] All tests pass
- [ ] Tag `v0.52.0`, push, GitHub release created
