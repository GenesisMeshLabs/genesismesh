# Trust API — HTTP Reference

> **Added in v0.52.0**

These routes expose every SDK-required stable protocol operation over HTTP.
They are served by the Network Authority (NA).

**Base URL** — the NA process, e.g. `https://na.example.com`.

**Auth** — admin routes require operator-signed headers (same scheme as
`/admin/recognition-treaties`). Verification routes are unauthenticated.

**Rate limits** — admin routes: 30 requests per 60 seconds per IP.
Unauthenticated verify/prove routes: 60 requests per 60 seconds per IP.
`GET /data-usage/policy`: 120 requests per 60 seconds per IP.

**Error sanitization** — internal exception details are never included in API
error responses; they are written to the server log. Clients receive a
human-readable message and a stable `code` string only.

---

## Agreement negotiation

### `POST /admin/agreements/offer`

Build and sign a `CapabilityOffer` as the NA sovereign.

**Auth** — operator signature required.

**Request**

```json
{
  "responder_sovereign_id": "sovereign-b",
  "capabilities": ["read", "write"],
  "scope": {},
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_until": "2026-06-02T00:00:00Z",
  "expires_at": "2026-06-01T01:00:00Z"
}
```

**Response** `201` — `CapabilityOffer` JSON with `signatures`.

**Errors** — `400 missing_offer_fields`, `400 invalid_timestamps`,
`401 admin_auth_failed`, `422 offer_rejected`.

```sh
curl -X POST $NA/admin/agreements/offer \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key-Id: ..." -H "X-Admin-Signature: ..." \
  -d '{"responder_sovereign_id":"b","capabilities":["read"],"valid_from":"...","valid_until":"...","expires_at":"..."}'
```

---

### `POST /admin/agreements/counter`

Build and sign a `CapabilityCounter` in response to an existing offer.

**Auth** — operator signature required.

**Request**

```json
{
  "offer": { "<CapabilityOffer>": "..." },
  "capabilities": ["read"],
  "scope": {},
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_until": "2026-06-01T12:00:00Z"
}
```

**Response** `201` — `CapabilityCounter` JSON with `signatures`.

**Errors** — `400 missing_counter_fields`, `400 invalid_offer`,
`401 admin_auth_failed`, `422 counter_rejected`.

---

### `POST /admin/agreements/accept`

Accept an offer or counter-offer, producing a signed `AgreementRecord`.

**Auth** — operator signature required.

**Request (accept offer)**

```json
{ "offer": { "<CapabilityOffer>": "..." } }
```

**Request (accept counter)**

```json
{
  "counter": { "<CapabilityCounter>": "..." },
  "original_offer": { "<CapabilityOffer>": "..." }
}
```

**Response** `201` — `AgreementRecord` JSON with `signatures`.

**Errors** — `400 missing_accept_fields`, `401 admin_auth_failed`,
`422 accept_rejected`.

---

### `POST /agreements/verify`

Verify a signed `AgreementRecord`. Unauthenticated.

**Request**

```json
{
  "agreement": { "<AgreementRecord>": "..." },
  "offerer_public_keys": ["<base64-ed25519>"],
  "responder_public_keys": ["<base64-ed25519>"]
}
```

**Response** `200`

```json
{ "accepted": true, "reason": "accepted", "agreement_id": "..." }
```

**Errors** — `400 missing_agreement`, `400 invalid_agreement`.

---

## Boundary decisions

### `POST /admin/boundary/decide`

Evaluate a `ContextRecord` against an `AgreementRecord` and sign a
`BoundaryDecision`.

**Auth** — operator signature required.

**Request**

```json
{
  "agreement": { "<AgreementRecord>": "..." },
  "requested_capability": "read",
  "context": {
    "requester_sovereign_id": "sovereign-b",
    "request_parameters": {}
  }
}
```

**Response** `201` — `BoundaryDecision` JSON with `signature`.

**Errors** — `400 missing_boundary_fields`, `400 invalid_agreement`,
`401 admin_auth_failed`, `422 boundary_eval_failed`.

```sh
curl -X POST $NA/admin/boundary/decide \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key-Id: ..." -H "X-Admin-Signature: ..." \
  -d '{"agreement":{...},"requested_capability":"read"}'
```

---

### `POST /boundary/verify`

Verify a signed `BoundaryDecision`. Unauthenticated.

**Request**

```json
{
  "decision": { "<BoundaryDecision>": "..." },
  "operator_public_keys": ["<base64-ed25519>"]
}
```

**Response** `200`

```json
{ "accepted": true, "authorized": true, "reason": "...", "decision_id": "..." }
```

**Errors** — `400 missing_decision`, `400 invalid_decision`.

---

## Trust evidence

### `POST /admin/trust-evidence`

Sign a `TrustEvidence` record from a `TrustDecision`.

**Auth** — operator signature required.

**Request**

```json
{
  "decision": {
    "source_sovereign_id": "TEST",
    "target_sovereign_id": "sovereign-b",
    "verdict": "allow",
    "reason": "direct recognition",
    "requested_roles": [],
    "trusted": true,
    "trust_path": [],
    "hop_count": 0,
    "signals": [],
    "evaluated_at": "2026-06-01T00:00:00Z"
  },
  "graph_digest": "<optional-sha256-hex>"
}
```

**Response** `201` — `TrustEvidence` JSON with `signatures`.

**Errors** — `400 missing_decision`, `400 invalid_decision`,
`401 admin_auth_failed`, `422 evidence_build_failed`.

---

### `POST /trust-evidence/verify`

Verify a `TrustEvidence` signature and optional graph digest. Unauthenticated.

**Request**

```json
{
  "evidence": { "<TrustEvidence>": "..." },
  "issuer_public_keys": ["<base64-ed25519>"],
  "expected_graph_digest": "<optional-sha256-hex>"
}
```

**Response** `200`

```json
{
  "accepted": true,
  "reason": "accepted",
  "evidence_id": "...",
  "issuer_sovereign_id": "...",
  "verdict": "allow"
}
```

**Errors** — `400 missing_evidence`, `400 invalid_evidence`.

---

## Selective disclosure

### `POST /admin/disclosure/commit`

Commit to a list of capabilities under an `AgreementRecord`, signed by the NA.

**Auth** — operator signature required.

**Request**

```json
{
  "capabilities": ["read", "write"],
  "agreement": { "<AgreementRecord>": "..." }
}
```

**Response** `201` — `CapabilityCommitment` JSON with `signature`.

**Errors** — `400 missing_commit_fields`, `401 admin_auth_failed`,
`422 commit_failed`.

---

### `POST /disclosure/prove`

Generate a Merkle membership proof. Unauthenticated — all inputs are
caller-supplied; no NA state is used.

**Request**

```json
{
  "capability": "read",
  "capabilities": ["read", "write"],
  "commitment": { "<CapabilityCommitment>": "..." },
  "prover_sovereign_id": "sovereign-b"
}
```

**Response** `200` — `CapabilityMembershipProof` JSON.

**Errors** — `400 missing_prove_fields`, `400 invalid_commitment`,
`422 prove_failed`.

---

### `POST /disclosure/verify`

Verify a `CapabilityMembershipProof` against its commitment. Unauthenticated.

**Request**

```json
{
  "proof": { "<CapabilityMembershipProof>": "..." },
  "commitment": { "<CapabilityCommitment>": "..." },
  "issuer_public_keys": ["<base64-ed25519>"]
}
```

**Response** `200`

```json
{ "valid": true, "reason": "valid", "commitment_id": "..." }
```

**Errors** — `400 missing_verify_fields`, `400 invalid_input`.

---

### `POST /admin/disclosure/nullifier`

Issue a one-time nullifier for a proof, signed by the NA.

**Auth** — operator signature required.

**Request**

```json
{ "proof": { "<CapabilityMembershipProof>": "..." } }
```

**Response** `201` — `CapabilityNullifier` JSON with `signature`.

**Errors** — `400 missing_proof`, `401 admin_auth_failed`, `422 nullifier_failed`.

---

## Consensus

### `POST /admin/consensus/vote`

Cast a `ValidatorVote` signed by the NA as validator.

**Auth** — operator signature required.

**Request**

```json
{
  "justification_proof": { "<JustificationProof>": "..." },
  "vote": true,
  "reason": "decision aligns with recognition policy"
}
```

**Response** `201` — `ValidatorVote` JSON with `signature`.

**Errors** — `400 missing_vote_fields`, `400 invalid_justification`,
`401 admin_auth_failed`, `422 vote_failed`.

---

### `POST /admin/consensus/proof`

Assemble a `ConsensusProof` from votes, signed by the NA as assembler.

**Auth** — operator signature required.

**Request**

```json
{
  "justification_proof": { "<JustificationProof>": "..." },
  "votes": [{ "<ValidatorVote>": "..." }],
  "required_threshold": 2,
  "validator_sovereign_ids": ["na-1", "na-2"]
}
```

**Response** `201` — `ConsensusProof` JSON with `signature`.

**Errors** — `400 missing_proof_fields`, `401 admin_auth_failed`,
`422 proof_assembly_failed`.

---

### `POST /consensus/verify`

Verify a `ConsensusProof`. Unauthenticated.

**Request**

```json
{
  "proof": { "<ConsensusProof>": "..." },
  "validator_public_keys": { "na-1": "<base64>", "na-2": "<base64>" },
  "assembler_public_keys": ["<base64-ed25519>"]
}
```

**Response** `200`

```json
{ "valid": true, "reason": "valid", "consensus_id": "..." }
```

**Errors** — `400 missing_proof`, `400 invalid_proof`.

---

## Data usage

### `POST /admin/data-usage/policy`

Create and sign a `DataLicensePolicy` as licensor (NA). The policy is stored
in process memory and becomes the active policy returned by
`GET /data-usage/policy`.

> **Warning: ephemeral storage.** Policies are held in process memory and are
> lost on process restart. Re-POST after restart, or store the signed response
> body externally. Multi-instance deployments require coordinated re-posting to
> each instance. Database persistence is planned for a future release.

**Auth** — operator signature required.

**Request**

```json
{
  "licensee_sovereign_id": "sovereign-b",
  "allowed_source_ids": ["src-1"],
  "allowed_access_types": ["read"],
  "max_volume_bytes_per_session": null,
  "prohibited_classification_tags": [],
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_until": "2026-12-31T00:00:00Z"
}
```

**Response** `201` — `DataLicensePolicy` JSON with `signature`.

**Errors** — `400 missing_policy_fields`, `400 invalid_timestamps`,
`401 admin_auth_failed`.

```sh
curl -X POST $NA/admin/data-usage/policy \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key-Id: ..." -H "X-Admin-Signature: ..." \
  -d '{"licensee_sovereign_id":"b","allowed_source_ids":["src-1"],"allowed_access_types":["read"],"valid_from":"...","valid_until":"..."}'
```

---

### `GET /data-usage/policy`

Return the currently active `DataLicensePolicy`. Unauthenticated.

**Response** `200` — `DataLicensePolicy` JSON.

**Errors** — `404 no_policy` (no policy has been created yet).

---

### `POST /admin/data-usage/intent`

Create and sign a `DataAccessIntent` as agent (NA).

**Auth** — operator signature required.

**Request**

```json
{
  "sources": [
    {
      "source_id": "src-1",
      "source_type": "database",
      "owner_sovereign_id": "TEST",
      "classification_tags": []
    }
  ],
  "access_types": ["read"],
  "decision_id": "dec-001",
  "estimated_volume_bytes": 1048576
}
```

**Response** `201` — `DataAccessIntent` JSON with `signature`.

**Errors** — `400 missing_intent_fields`, `400 invalid_source`,
`401 admin_auth_failed`, `422 intent_create_failed`.

---

### `POST /data-usage/verify`

Verify a `DataAccessIntent` against a `DataLicensePolicy`. Unauthenticated.

**Request**

```json
{
  "intent": { "<DataAccessIntent>": "..." },
  "policy": { "<DataLicensePolicy>": "..." },
  "agent_public_keys": ["<base64-ed25519>"]
}
```

**Response** `200`

```json
{
  "valid": true,
  "violation_reason": null,
  "violation_count": 0,
  "violations": []
}
```

**Errors** — `400 missing_verify_fields`, `400 invalid_input`.

---

## Common error format

All error responses use this envelope:

```json
{
  "error": {
    "code": "missing_offer_fields",
    "message": "responder_sovereign_id and capabilities[] are required",
    "details": {},
    "request_id": "<uuid>"
  }
}
```

| HTTP status | Meaning |
|---|---|
| 400 | Missing or malformed input |
| 401 | Invalid or missing operator signature (admin routes) |
| 404 | Resource not found |
| 422 | Input is well-formed but rejected by the trust library |
| 500 | Unexpected internal error |
