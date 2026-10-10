# Trust API — HTTP Reference

> **Added in v0.52.0**

These routes expose every SDK-required stable protocol operation over HTTP.
They are served by the Network Authority (NA).

```{tip}
Try the read and verify operations without running anything: the gateway at
[mesh.genesismesh.org](https://mesh.genesismesh.org) publishes a demo token
that can read and verify, but not change, its two sovereigns.
```

**Base URL** — the NA process, e.g. `https://na.example.com`.

**Auth** — admin routes require operator-signed headers (same scheme as
`/admin/recognition-treaties`). Verification routes are unauthenticated.

**Rate limits** — admin routes: 300 requests per 60 seconds per IP by default,
and 30 failed admin authentications per operator key and address before that
key gets `429 admin_auth_throttled` there (v1.1.0, per key since v1.2.0; see
{doc}`../reference/configuration`).
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

**Auth** — operator signature, privileged tier since v1.1.1: the offerer can
accept the counter on its own, so the NA's signature on a counter is its
consent to the agreement. A standard-tier key gets
`403 insufficient_operator_tier`.

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

**Auth** — operator signature (privileged tier since v0.62.0: the agreement
grants capabilities that boundary decisions then authorize). A standard-tier
key gets `403 insufficient_operator_tier`. Offers still accept a standard key;
counters need a privileged key since v1.1.1.

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

### Agreements and their parties (v1.1.1)

`/admin/boundary/decide`, `/admin/boundary/evaluate` and
`/admin/disclosure/commit` accept an agreement only if two different parties
signed it with keys the NA trusts: its own key for its own sovereign, and for
any other sovereign the keys of an active recognition treaty the NA issued to
it that grants at least one role. The NA's key never vouches for another
sovereign, a sovereign cannot agree with itself, and one key cannot sign for
both parties. An agreement the NA offered and accepted itself
(`/admin/agreements/accept`, privileged) stays trusted when its responder
holds such a treaty. Nothing in the request can add a trusted key. Otherwise
the route returns `422 agreement_untrusted` with `details.reason`
(`unknown_party`, `same_party`, `overlapping_party_keys`, or the reason
`verify_agreement` gives) and `details.party` when one party is at fault, and
records an `agreement_untrusted` audit event.

Under an agreement the requester is the agreement's responder and the provider
its offerer. `context.requester_sovereign_id` and
`context.provider_sovereign_id` may repeat them; any other value is refused
with `400 context_party_mismatch`.

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
`400 invalid_context`, `400 context_party_mismatch` (v1.1.1),
`401 admin_auth_failed`, `409 boundary_policy_required` (v0.58, when the NA
runs with `boundary_policy_enforcement=required`), `422 agreement_untrusted`
(v1.1.1), `422 boundary_eval_failed`.

This route does not consult boundary policies and its response never carries
`policy_binding`. Use `POST /admin/boundary/evaluate` for policy-aware
decisions.

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

## Boundary policies (v0.58)

Signed, versioned declarative policies that configure trusted gate types. See
{doc}`../examples/declarative-boundary-policy` for the model and semantics.
All admin routes are rate limited to 300 requests/min per IP by default; the
public verify route to 60/min per IP.

### `POST /admin/boundary-policies/validate`

Dry-run validation of policy intent against the NA's gate registry. Nothing is
signed or stored. **Auth** — operator signature (standard tier).

**Request** — the same intent body as publish.

**Response** `200`

```json
{ "valid": false, "issues": [{"code": "unknown_gate_type", "message": "...", "gate_id": "x"}],
  "policy_id": "transfer-limits", "next_version": 3 }
```

### `POST /admin/boundary-policies`

Validate, sign and store a new **inactive** version. **Auth** — operator
signature (privileged tier).

**Request** — intent fields only. `version`, `signature`, `issued_at`,
`issued_by` and `issuer_sovereign_id` are assigned by the NA.

```json
{
  "policy_id": "transfer-limits",
  "description": "Cap transfers",
  "valid_from": "2026-10-01T00:00:00Z",
  "valid_until": "2027-10-01T00:00:00Z",
  "selector": {"capabilities": ["payments.*"]},
  "gates": [
    {"gate_id": "amount-cap", "gate_type": "max_value.v1", "order": 0,
     "config": {"path": "request_parameters.amount", "max": 1000}}
  ]
}
```

**Response** `201` — signed `BoundaryPolicy` JSON.

**Errors** — `400 unexpected_field`, `400 missing_policy_id`,
`400 missing_validity_window`, `400 invalid_boundary_policy`,
`400 boundary_policy_invalid` (with `details.issues`), `401 admin_auth_failed`,
`403` (standard tier).

### `GET /admin/boundary-policies`

Every stored version with `active`, `policy_digest`, validity, gate count and
`integrity_ok`. **Auth** — operator signature.

### `GET /admin/boundary-policies/active`

**Auth** — operator signature.

```json
{ "enforcement": "optional", "policy_set_healthy": true, "problems": [],
  "registry_gate_types": ["allowlist.v1", "..."],
  "active": [{"policy_id": "transfer-limits", "version": 2, "policy_digest": "...", "policy": {"...": "..."}}] }
```

`policy_set_healthy=false` means every policy-aware evaluation is denied until
the listed problems are fixed.

### `GET /admin/boundary-policies/<policy_id>/history`

All versions of one policy, newest first, including the signed policy bodies.
**Auth** — operator signature.

### `POST /admin/boundary-policies/<policy_id>/activate`

Re-verify a stored version and make it the active one; any other active
version of the same policy is deactivated in the same transaction. Activating
an earlier version is the rollback. **Auth** — operator signature (privileged
tier).

**Request** `{ "version": 1 }` — **Response** `200`
`{ "policy_id": "...", "version": 1, "previous_version": 2, "active": true }`

**Errors** — `400 invalid_policy_version`, `404 boundary_policy_not_found`,
`409 boundary_policy_integrity_failed`,
`409 boundary_policy_activation_refused`.

### `POST /admin/boundary-policies/<policy_id>/deactivate`

**Request** `{ "version": 1 }`. **Auth** — operator signature (privileged tier).
**Errors** — `404 boundary_policy_not_found`, `409 boundary_policy_not_active`.

### `POST /admin/boundary/evaluate`

Policy-aware evaluation: built-in gates, then every applicable active policy.
**Auth** — operator signature (standard tier).

**Request** — the same body as `/admin/boundary/decide`, plus optional
`context.attributes` (normalized external facts; never secrets). Supply
**exactly one** basis: `agreement` (an `AgreementRecord`) or, since v0.58.1,
`attestation_id` (a `MembershipAttestation` this NA issued).

```json
{ "attestation_id": "7f0c...",
  "requested_capability": "app.invoke",
  "context": { "request_parameters": { "app_id": "billing" } } }
```

With `attestation_id` the NA loads the attestation from its store, verifies
its signature against the NA key, checks that it is active and not revoked
(locally or by an imported sovereign revocation feed), that the request time is
within `valid_from`..`expires_at`, and that `context.requester_sovereign_id`
(default: the attestation subject) is the subject. The provider is this NA's
sovereign; since v1.1.1 a different `context.provider_sovereign_id` is
refused with `400 context_party_mismatch`. The context's `parent_kind`
is always `"attestation"` and its `agreement_id` and `attestation_id` carry the
attestation id. The built-in gates are `attestation_status`,
`attestation_validity`, `capability_check` (against `claims.capabilities`) and
`freshness_check`, followed by the applicable policies with the read-only
`attestation.subject_id`, `attestation.roles` and `attestation.claims.<key>`
facts available to them. The signed decision carries an `attestation_binding`
(`attestation_id`, `subject_id`, `issuer_sovereign_id`, `attestation_digest`,
`revocation_seq_checked`) alongside its `policy_binding`, and the NA records a
`boundary_attestation_decision_made` audit event. See
{doc}`../examples/attestation-backed-evaluation`.

**Response** `201`

```json
{ "decision": { "<BoundaryDecision with policy_binding>": "..." },
  "justification_proof": { "<JustificationProof>": "..." } }
```

Policy-evaluation failures return `201` with a signed DENY decision and a
stable `policy_binding.resolution_failure` or gate `outcome`. An unusable
attestation also returns `201` with a signed DENY whose `denial_reason` is
`attestation_not_found`, `attestation_invalid` (signature does not verify),
`attestation_revoked`, `attestation_expired`, `attestation_not_yet_valid` or
`attestation_subject_mismatch`. Malformed requests return
`400 ambiguous_basis` (both or neither basis), `400 invalid_attestation_id`,
`400 missing_boundary_fields`, `400 invalid_agreement`, `400 invalid_context`
or `400 context_party_mismatch`. An agreement the NA does not trust returns
`422 agreement_untrusted` (v1.1.1, see *Agreements and their parties*).

### `POST /boundary-policies/verify`

Verify a signed `BoundaryPolicy`. Unauthenticated.

**Request** `{ "policy": {...}, "issuer_public_keys": ["<base64-ed25519>"] }`
(keys default to the NA key).

**Response** `200`
`{ "valid": true, "reason": "valid", "policy_id": "...", "version": 1, "policy_digest": "..." }`

**Errors** — `400 missing_policy`, `400 invalid_policy`,
`400 invalid_public_keys`.

---

## Evidence store (v0.59)

Opt-in (`EVIDENCE_STORE=on`, `--evidence-store on`). When off, every route
below returns `404 evidence_store_disabled` and nothing is stored. When on,
`/admin/boundary/evaluate` and `/admin/boundary/decide` store each signed
decision with its context (and justification proof) before responding; a
storage failure returns `503 evidence_store_unavailable`. See
{doc}`../examples/evidence-store`.

### `POST /evidence/execution`

Submit one signed `ExecutionEvidence` after acting. **Auth**: the record's
signature, by a registered, active executor key for its
`executor_sovereign_id`. Rate limit 120/min per IP.

**Request** `{ "evidence": { "<ExecutionEvidence>": "..." } }`. Optional v0.59
fields `resource_id`, `resource_action` (`create`, `rotate`, `revoke`, `update`,
`delete`), `resource_sequence` and `prev_resource_digest` place the record in
its resource's chain across decisions. `execution_parameters` and
`outcome_detail` must hold metadata only.

**Response** `201` `{ "entry": {...}, "entry_digest": "...", "status": "recorded" }`;
an identical resubmission returns `200` with `"status": "duplicate"`.

Since v1.1.1 the record must be exactly its serialized form: the fields of
`ExecutionEvidence` and no others, with their types (an absent resource field
may also be sent as `null`). Extra fields, coerced types and other variants
are refused as `evidence_malformed` with a message naming the difference, so
the store keeps only what the signature covers.

**Errors**: `422` with `evidence_malformed`, `evidence_unknown_executor`,
`evidence_invalid_signature`, `evidence_decision_not_found`,
`evidence_decision_denied`, `evidence_decision_mismatch`,
`evidence_outside_decision_window`, `evidence_capability_mismatch`,
`evidence_chain_gap`, `evidence_chain_mismatch`, `resource_chain_gap`,
`resource_chain_mismatch` or `evidence_secret_material`; `409 evidence_conflict`
when the position or `evidence_id` is already taken by a different record. Every
rejection is stored (without the payload) and audited.

### Operator routes

All operator-signed; the admin rate limits apply (see *Rate limits* above).

| Route | Purpose |
|---|---|
| `GET /admin/evidence` | Search by `vendor_id`, `attestation_id`, `capability`, `resource_id`, `outcome`, `entry_kind`, `decision_id`, `since`, `until`; page with `after_sequence` and `limit` (1-1000) |
| `GET /admin/evidence/resources/<resource_id>` | One resource's history, decision to execution, with a verification result. At most 10,000 records (the oldest); `truncated: true` when a longer chain was cut, in which case read it through the export |
| `GET /admin/evidence/resource-heads/<resource_id>` | `{resource_id, resource_sequence, record_digest}`: what the next record of the resource must link to (the latest stored record, or the latest retention checkpoint), from one indexed lookup; `404 resource_not_found` when there is none (v0.63.1). Controllers use this, not the history, before each action |
| `GET /admin/evidence/vendors/<vendor_id>` | A vendor's decisions and the evidence under them, verified; `truncated` as for resources |
| `GET /admin/evidence/verify` | Verify every stored entry, chain and signature |
| `GET /admin/evidence/status` | Mode, entry count, last `store_sequence`, latest retention checkpoint |
| `GET /admin/evidence/export` | `gm.evidence.event` JSON Lines (`application/x-ndjson`) after `since_sequence`; see {doc}`../reference/evidence-event-schema` |
| `GET /admin/evidence/executor-keys` | Registered executor and observer keys, including retired ones, with their `role` and `resource_prefix` |
| `POST /admin/evidence/executor-keys` | Register `{key_id, public_key, executor_sovereign_id}`, and since v1.3.0 `role` (`executor`, the default, or `observer`) and `resource_prefix` (the key signs only for resources whose ID starts with it) (privileged; `409 executor_key_exists`, `400 invalid_key_role`, `400 invalid_resource_prefix`) |
| `POST /admin/evidence/executor-keys/<key_id>/retire` | Retire a key: it still verifies old records and signs no new ones (privileged) |
| `POST /admin/evidence/retention/apply` | `{ "older_than_days": N }`: remove a verifiable prefix behind a signed `RetentionCheckpoint` (privileged) |
| `GET /admin/evidence/anchors` | Signed `StoreAnchor`s in order, paged with `after_anchor` and `limit` (1-1000); `read` tier (v1.2.0) |
| `POST /admin/evidence/anchors` | Sign the store's current head now: `201` with `"status": "anchored"`, or `200` with `"status": "unchanged"` and the latest anchor while the head has not moved; `read` tier; `409 evidence_anchor_refused` when the store no longer continues from the last anchor or the last anchor is dated ahead of the NA's clock (v1.2.0) |

Since v1.2.0 the NA signs the store's head (a `StoreAnchor`: `anchor_sequence`,
`sovereign_id`, `store_sequence`, `entry_digest`, `anchored_at`,
`previous_anchor_digest`, `issued_by`, `signature`) after an append once
`NA_ANCHOR_INTERVAL_SECONDS` have passed. Anchors are kept outside the store
chain and never removed. `GET /admin/evidence/verify` checks them, and
`GET /admin/evidence/status` reports the latest one and `unanchored_entries`.
See {doc}`../operations/evidence-anchors`.

Since v1.3.0 an authentic execution record refused for good (its decision
denied, mismatched or outside its window, the wrong capability, a chain
mismatch or a conflict) is kept as a `quarantine` entry; the `422` or `409`
names it in `error.details.quarantine_id`.

### Changes outside the controlled path (v1.3.0)

Observations, break-glass records, judgements, quarantine and registry
records. The routes are beta until 1.5.0; the records' signed forms are
stable. See {doc}`../operations/out-of-band-changes`.

#### `POST /evidence/observations`

Submit one signed `ObservationRecord`. **Auth**: the record's signature, by a
registered, active observer key for its `observer_sovereign_id` whose
`resource_prefix` covers the resource. Rate limit
`NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE` (120/min per IP).

**Request** `{ "observation": { "<ObservationRecord>": "..." } }`, in its exact
serialized form (absent optional fields left out, UTC timestamps).

**Response** `201` with `entry`, `entry_digest`, `payload` and
`"status": "recorded"`, and with automatic judgement on, `judgement` (the
judgement entry, or `null` when judging failed and is left to the judge
route); `"status": "quarantined"` when the observation is outside its time
bounds; `200` with `"status": "duplicate"` for the same observation again.

**Errors**: `422` with `observation_malformed`,
`observation_invalid_signature`, `observation_unknown_key`,
`observation_out_of_scope` or `observation_secret_material`;
`409 observation_conflict` for a different observation of the same source
event.

#### `POST /evidence/observations/batch`

`{ "observations": [...] }`, up to 100, admitted in order of their change
times. **Response** `200` `{ "results": [...] }` in request order, each with
`index` and the single route's body, or `"status": "refused"` with its
`error`.

#### `POST /evidence/break-glass`

Submit one signed `BreakGlassRecord`, `{ "record": {...} }`. **Auth**: the
record's signature, by a registered, active executor key. Responses as for
observations; errors `break_glass_malformed`, `break_glass_invalid_signature`,
`break_glass_unknown_key`, `break_glass_out_of_scope`,
`break_glass_secret_material`, `409 break_glass_conflict`.

#### Operator routes

| Route | Purpose |
|---|---|
| `POST /admin/evidence/observations/<observation_id>/judge` | Judge an observation once: `201` with `"status": "judged"`, or `200` with `"status": "existing"`; `404 judgement_subject_not_found` |
| `POST /admin/evidence/break-glass/<break_glass_id>/judge` | The same for a break-glass record |
| `GET /admin/evidence/changes/<resource_id>` | Every change to a resource, oldest first: `kind`, `action`, `at`, `governed_by`, `state` (`recorded`, `matched`, `judged_allowed`, `judged_denied`, `indeterminate`, `observed`, `quarantined`), and the verdict, flag, hint or justification where there is one; `read` tier |
| `GET /admin/evidence/operator-holders` | The holder the store records for each operator key; `read` tier |
| `POST /admin/operator-keys/<key_id>/holder` | Propose `{ "holder": "..." }` for an operator key (privileged): `201` with a `proposal_id` |
| `POST /admin/operator-keys/holder-changes/<proposal_id>/approve` | Approve it with a privileged key of a different holder; recorded in the store; `409 holder_change_needs_second_holder`, `409 holder_change_already_approved`, `404 holder_change_not_found` |

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
`422 agreement_untrusted` (v1.1.1, see *Agreements and their parties*),
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

Since v1.1.1 the justification proof must be one this NA signed; any other
is refused with `422 justification_untrusted`.

**Errors** — `400 missing_vote_fields`, `400 invalid_justification`,
`401 admin_auth_failed`, `422 justification_untrusted` (v1.1.1),
`422 vote_failed`.

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

Since v1.1.1 `required_threshold` must be an integer from 1 to the number of
distinct `validator_sovereign_ids` (`400 invalid_threshold`), and the
justification proof must be one this NA signed (`422 justification_untrusted`).

**Errors** — `400 missing_proof_fields`, `400 invalid_threshold` (v1.1.1),
`401 admin_auth_failed`, `422 justification_untrusted` (v1.1.1),
`422 proof_assembly_failed`.

---

### `POST /consensus/verify`

Verify a `ConsensusProof`. Unauthenticated.

**Request**

```json
{
  "proof": { "<ConsensusProof>": "..." },
  "validator_public_keys": { "validator-1": "<base64>", "validator-2": "<base64>" },
  "assembler_public_keys": ["<base64-ed25519>"]
}
```

`validator_public_keys` is **required**: a mapping of
`validator_sovereign_id` → base64 public key, covering every validator whose
approve vote counts toward the threshold. A consensus proof is verified against
the *validators'* keys, not this service's — there is no default. A vote that is
unsigned, or whose validator has no key in this map, is rejected rather than
skipped.

`assembler_public_keys` is optional and defaults to this Network Authority's own
key, which only accepts a proof this service itself assembled and signed.

**Response** `200`

```json
{ "valid": true, "reason": "valid", "consensus_id": "..." }
```

`reason` is one of `valid`, `missing_signature`, `invalid_assembler_signature`,
`proof_id_mismatch`, `invalid_vote_signature`, `unknown_validator_key`,
`vote_not_in_validator_set`, `threshold_not_met`, `missing_context_digest`,
`cascade_detected`, `expired`.

The threshold counts **distinct approving validators**, not votes: several votes
from the same validator count once.

**Errors** — `400 missing_proof`, `400 invalid_proof`,
`400 missing_validator_public_keys`.

---

## Data usage

### `POST /admin/data-usage/policy`

Create and sign a `DataLicensePolicy` as licensor (NA). The signed policy is stored
in the authority database and becomes the active policy returned by
`GET /data-usage/policy`.

**Auth** — operator signature (privileged tier since v0.62.0: the policy grants
a licensee access to data sources). A standard-tier key gets
`403 insufficient_operator_tier`.

Migration `011_data_license_policies.sql` adds durable policy versions and an
atomic active-policy selection. Workers sharing the authority database observe
the same active version, which survives restarts. Separate authority databases
still require operator-managed policy distribution.

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

## Health and readiness (v0.60)

### `GET /healthz`

Process liveness only: `{"status": "ok"}`.

### `GET /readyz`

Load-balancer readiness. Returns 200 when the database is reachable and
writable at the expected schema version and the signing key is loaded. In HA
mode, the shared rate limiter must also be in use:

```json
{
  "status": "ready",
  "instance": "host:1a2b3c4d",
  "ha_mode": "off",
  "database": {"backend": "sqlite", "writable": true, "schema_version": 13, "expected_schema_version": 13},
  "signing_key": {"key_id": "na-local", "provider": "file", "fingerprint": "<sha256 of the public key>"},
  "rate_limiter": "memory",
  "db_path": "<SQLite path, or the PostgreSQL URL without its password>"
}
```

When not ready: `503 service_not_ready`, with the same checks in
`error.details`. The response never contains key material.

### Concurrency conflicts (v0.60)

With several NA instances, a request that loses a race the database decides
gets `409`, and the client may retry it:

| Code | Meaning |
|---|---|
| `boundary_policy_activation_conflict` | another version of the policy was activated at the same moment |
| `boundary_policy_version_conflict` | concurrent publishes of one policy kept taking the next version |
| `crl_publish_contention` | concurrent revocations kept taking the next CRL sequence |
| `retention_in_progress` | evidence retention is already running on another instance |

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
| 409 | Conflicts with stored state, or lost a concurrent race (retryable, see above) |
| 422 | Input is well-formed but rejected by the trust library |
| 500 | Unexpected internal error |
