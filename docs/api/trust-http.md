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
and 30 failed admin authentications per operator key and address, after which
that key's failing requests there get `429 admin_auth_throttled` (v1.1.0, per
key since v1.2.0; a correctly signed request is still served since v1.3.1; see
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
| `GET /admin/evidence` | Search by `vendor_id`, `attestation_id`, `capability`, `resource_id`, `outcome`, `entry_kind`, `decision_id`, `grant_id` (v1.6.0: a grant's uses and its revocation), `since`, `until`; page with `after_sequence` and `limit` (1-1000). Since v1.5.0 this and every evidence read below (status, verify, histories, resource heads, export, executor keys) accept the `read` tier |
| `GET /admin/evidence/resources/<resource_id>` | One resource's history, decision to execution, with a verification result. At most 10,000 records (the oldest); `truncated: true` when a longer chain was cut, in which case read it through the export |
| `GET /admin/evidence/resource-heads/<resource_id>` | `{resource_id, resource_sequence, record_digest, entry_kind, record_id}`: what the next record of the resource must link to (the latest stored record, or the latest retention checkpoint), from one indexed lookup; `404 resource_not_found` when there is none (v0.63.1). `entry_kind` and `record_id` (v1.6.0, additive) say what the head is: `execution` (its `evidence_id`), `grant_execution` (its `use_id`) or `retention_checkpoint` (`record_id` `null`). Controllers use this, not the history, before each action |
| `GET /admin/evidence/vendors/<vendor_id>` | A vendor's decisions and the evidence under them, verified; `truncated` as for resources |
| `GET /admin/evidence/verify` | Verify every stored entry, chain and signature |
| `GET /admin/evidence/status` | Mode, entry count, last `store_sequence`, latest retention checkpoint, latest anchor and `unanchored_entries`; `unjudged_records`, reported whether `EVIDENCE_OUT_OF_BAND` is on or off since v1.3.1; `anchoring_blocked` while the latest anchor is dated ahead of this instance's clock (v1.3.1) |
| `GET /admin/evidence/export` | `gm.evidence.event` JSON Lines (`application/x-ndjson`) after `since_sequence`; see {doc}`../reference/evidence-event-schema` |
| `GET /admin/evidence/executor-keys` | Registered executor and observer keys, including retired ones, with their `role` and `resource_prefix` |
| `POST /admin/evidence/executor-keys` | Register `{key_id, public_key, executor_sovereign_id}`, and since v1.3.0 `role` (`executor`, the default, or `observer`) and `resource_prefix` (the key signs only for resources whose ID starts with it) (privileged; `409 executor_key_exists`, `400 invalid_key_role`, `400 invalid_resource_prefix`) |
| `POST /admin/evidence/executor-keys/<key_id>/retire` | Retire a key: it still verifies old records and signs no new ones (privileged) |
| `POST /admin/evidence/retention/apply` | `{ "older_than_days": N, "through_sequence": M }` (either or both; `through_sequence` since v1.5.0): remove a verifiable prefix behind a signed `RetentionCheckpoint` (privileged). `held_back` says when records not judged yet stop it (v1.3.1), or (v1.5.0, `"reason": "not_archived"`) when no archive covers what would go and `NA_RETENTION_REQUIRE_ARCHIVE` is on; `409 evidence_retention_refused` when the store does not hold every entry from its start, no longer continues from the latest anchor, or an entry to remove does not recompute (v1.3.1). Registry, key succession and archive entries are carried past the checkpoint with their first recorded time; since v1.5.0 a resource's latest record no longer stops it |
| `POST /admin/evidence/audit-pack` | An audit pack (v1.5.0): `{from_sequence or since, until_sequence or until}` (all optional; the range widens to the anchors around it). `{manifest, files}`: the signed `AuditPackManifest` and every other file as text; see {doc}`../reference/audit-pack-format`. `409 audit_pack_not_anchored`, `409 audit_pack_too_large` (over 50,000 entries), `400 invalid_audit_pack`, `429` beyond `NA_RATE_LIMIT_AUDIT_PACKS_PER_HOUR` (a limit of its own); `read` tier. The NA records each pack it builds (manifest digest, whether its own checks passed) |
| `GET /admin/evidence/archives` | Archive records, `archived_through_sequence` (how far an unbroken run of them covers the store) and `require_archive`; `read` tier (v1.5.0) |
| `POST /admin/evidence/archives` | Record an archive (privileged, v1.5.0): `{manifest, location}` for a pack written to immutable storage and read back intact. The NA checks the manifest is signed by it as received, is one it built byte for byte, and passed its own checks, that its end anchor is its anchor of the last entry, and that the pack continues the archives without a gap, then appends a signed `ArchiveRecord` (entry kind `archive`). `201` `recorded`, or `200` `duplicate` for the same manifest; `400 invalid_archive`, `422 archive_manifest_invalid`, `409 archive_pack_unknown` (not a pack this NA built), `409 archive_pack_unverified` (its own checks failed), `409 archive_anchor_mismatch`, `409 archive_not_contiguous`, `409 archive_conflict` |
| `GET /admin/evidence/anchors` | Signed `StoreAnchor`s in order, paged with `after_anchor` and `limit` (1-1000); `read` tier (v1.2.0) |
| `POST /admin/evidence/anchors` | Sign the store's current head now: `201` with `"status": "anchored"`, or `200` with `"status": "unchanged"` and the latest anchor while the head has not moved; `read` tier; `409 evidence_anchor_refused` when the store no longer continues from the last anchor or the last anchor is dated ahead of the NA's clock (v1.2.0), or (v1.3.1) when the anchored head was rewritten, or the store does not start at entry 1 or right after the latest retention checkpoint, or misses an entry |

Since v1.2.0 the NA signs the store's head (a `StoreAnchor`: `anchor_sequence`,
`sovereign_id`, `store_sequence`, `entry_digest`, `anchored_at`,
`previous_anchor_digest`, `issued_by`, `signature`) after an append once
`NA_ANCHOR_INTERVAL_SECONDS` have passed. Anchors are kept outside the store
chain and never removed. `GET /admin/evidence/verify` checks them, and
`GET /admin/evidence/status` reports the latest one and `unanchored_entries`.
See {doc}`../operations/evidence-anchors`.

Since v1.3.0 an authentic execution record refused for good (its decision
denied, mismatched or outside its window, the wrong capability, a chain
mismatch or a conflict, a retired key or a key outside its scope) is kept as
a `quarantine` entry; the `422` or `409` names it in
`error.details.quarantine_id`. Quarantine needs `EVIDENCE_OUT_OF_BAND=on`:
with the switch off nothing is quarantined and the refusal carries no
`quarantine_id`.

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
`observation_key_retired`, `observation_out_of_scope` or
`observation_secret_material`; `409 observation_conflict` for a different
observation of the same source event, another observation with the same
`observation_id`, or (since 1.3.1) a break-glass record with that id. An
observation refused with `observation_key_retired` or
`observation_out_of_scope` is authentic, so since 1.3.1 it is also kept as a
`quarantine` entry, named in `error.details.quarantine_id` (never one that
may carry secret material).

#### `POST /evidence/observations/batch`

`{ "observations": [...] }`, up to 100, admitted in order of their change
times. **Response** `200` `{ "results": [...] }` in request order, each with
`index` and the single route's body, or `"status": "refused"` with its
`error` (`code`, `message`, and since 1.3.1 `details` when the refusal names
a `quarantine_id`).

#### `POST /evidence/break-glass`

Submit one signed `BreakGlassRecord`, `{ "record": {...} }`. **Auth**: the
record's signature, by a registered, active executor key. Responses as for
observations; errors `break_glass_malformed`, `break_glass_invalid_signature`,
`break_glass_unknown_key`, `break_glass_key_retired`,
`break_glass_out_of_scope`, `break_glass_secret_material`,
`409 break_glass_conflict` (another record with the same `break_glass_id`, or
since 1.3.1 an observation with that id). `break_glass_key_retired` and
`break_glass_out_of_scope` quarantine the record as for observations.

#### Operator routes

| Route | Purpose |
|---|---|
| `POST /admin/evidence/observations/<observation_id>/judge` | Judge an observation once: `201` with `"status": "judged"`, or `200` with `"status": "existing"`; `404 judgement_subject_not_found`; `409 judgement_conflict` when a break-glass record with the same id holds the id's judgement (a store written by 1.3.0) |
| `POST /admin/evidence/break-glass/<break_glass_id>/judge` | The same for a break-glass record |
| `GET /admin/evidence/changes/<resource_id>` | Every change to a resource, oldest first: `kind`, `action`, `at`, `governed_by`, `state` (`recorded`, `matched`, `judged_allowed`, `judged_denied`, `indeterminate`, `observed`, `quarantined`; since 1.4.0 the remediation state, with a `remediation` object, for a change a remediation or review concerns), and the verdict, flag, hint or justification where there is one. Since 1.4.0 paged: `limit` (1-10000, default 1000) and `after_sequence` (the previous page's `next_after_sequence`); `truncated` when there are more; `400 invalid_page`; `read` tier |
| `GET /admin/evidence/operator-holders` | The holder the store records for each operator key; `read` tier |
| `POST /admin/operator-keys/<key_id>/holder` | Propose `{ "holder": "..." }` for an operator key (privileged): `201` with a `proposal_id` |
| `POST /admin/operator-keys/holder-changes/<proposal_id>/approve` | Approve it with a privileged key of a different holder; recorded in the store; `409 holder_change_needs_named_holders` (the proposing or approving key has no named holder in the store), `409 holder_change_needs_second_holder`, `409 holder_change_proposer_revoked` (since 1.3.1: the proposing key was revoked, removed from the configuration or re-keyed since it proposed), `409 holder_change_already_approved`, `404 holder_change_not_found` |

With the records on, `GET /admin/evidence/status` also reports
`unjudged_records` and, since 1.3.1, `policy_history_started` (how far back
the policy history reaches, or `null` when it has not started and every
change is judged `indeterminate`), `registry_healthy` and
`registry_problems` (a registry check that failed at start, a policy history
that has not started, active policies the registry has not recorded, or a
registry entry left out because it does not parse, is not signed by the NA or
repeats a record's ID).

### Remediation, reviews and notification (v1.4.0)

Remediation records, reviews and the due queue, with
`EVIDENCE_REMEDIATION=on` (otherwise `404 remediation_disabled`). The routes
are beta until 1.5.0; the records' signed forms are stable. See
{doc}`../operations/remediation-and-reviews` and
{doc}`../operations/emergency-changes`.

With the records on, a judgement's body (at admission, under `judgement`, or
from the judge routes) carries `remediation`, the remediation state it armed
or the review it opened (none when the change is already under review as a
decision or a break-glass record), and
`GET /admin/evidence/changes/<resource_id>` shows each change's Stage 3
`state` with a `remediation` object. `GET /admin/evidence/status` reports
`evidence_remediation` and, with the records on, `remediation`: the number of
states by state, and `review_pending`, the number with a pending review
whatever their state.

#### The remediation state

Every route below that returns a state returns this object:

| Field | Meaning |
| --- | --- |
| `subject_kind`, `subject_id` | The judgement (or decision) the state is about |
| `change_kind`, `change_id`, `change_version_id` | The record of the change: `observation`, `break_glass` or `execution`, its ID (`null` for a decision before its evidence is known) and the version it made, as recorded when the state was armed |
| `resource_id`, `capability`, `verdict` | What changed, as the records say |
| `actor`, `actor_holder` | The change's actor: the observed actor as the source reported it (its holder mapped when a review is decided), or, for a decision, the operator key that asked for it and that key's holder |
| `state` | `remediation_due`, `overdue`, `remediated`, `upheld`, `waived`, or, for an allowed change under review or with a lifetime running, `judged_allowed`, `matched` or `recorded` |
| `review_pending` | `true` while a review is pending (a flag beside the state: it stops no clock) |
| `mode`, `steps`, `fallback`, `grace_seconds`, `guidance_source` | The plan: `cancel` or `alert_only`; `rotate_forward_then_disable`, `disable` or `none`; why a cancel fell back (`not_versioned`, `not_rotatable`, `not_reversible`, `indeterminate`, `not_executed`); the grace; `gate`, `policy` or `default` |
| `remediation_due_at`, `overdue_since` | When the remediation is or was due, and when it became overdue |
| `lifetime_ends_at`, `waived_until` | When an emergency change's lifetime ends; when a waiver ends |
| `review_id`, `remediation_id` | The latest review, and the remediation record |
| `notified_at`, `notified_by` | The first notice recorded, and the operator key that recorded it |
| `created_at`, `updated_at` | When the state was created and last changed |
| `review` | With `review_pending`: the pending review's summary (below) |

A **review summary** (the pending `review`, each of `reviews`, and the body
of `GET /admin/evidence/reviews/<review_id>`) has `review_id`, `subject_id`,
`opened_for` (`requested`, `flagged_for_review` or `review_required`),
`requested_by` and `requester_holder` (`null` when the NA opened it),
`justification`, `requested_at`, and `decided_at` and `verdict` (`null` while
pending).

Times are UTC with six digits of microseconds (`2026-11-02T10:16:00.000000+00:00`).

#### `POST /evidence/remediations`

Submit one signed `RemediationRecord`, `{ "record": {...} }`, in its exact
serialized form. **Auth**: the record's signature, by a registered, active
executor key of its `executor_sovereign_id` whose prefix covers the resource
and the subject's resource. Rate limit `NA_RATE_LIMIT_EVIDENCE_PER_MINUTE`.

**Response** `201` with `entry`, `entry_digest`, `payload`,
`"status": "recorded"` and `remediation` (the state, now `remediated`); `200`
with `"status": "duplicate"` for the same record again.

**Errors**, in the order they are checked:

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_remediation` | 400 | `record` is not an object |
| `remediation_malformed` | 422 | Not a `RemediationRecord` in its exact form (checked before the signature), or `remediated_at` in the future |
| `remediation_invalid_signature`, `remediation_unknown_key` | 422 | Not signed by a registered key of its sovereign |
| `remediation_key_retired`, `remediation_out_of_scope` | 422 | A retired key, an observer key, or a resource outside the key's prefix (quarantined) |
| `remediation_secret_material` | 422 | Its versions or detail look like secret material (never stored) |
| `remediation_out_of_scope` | 422 | The subject's resource is outside the key's prefix (nothing about the subject is told; not quarantined) |
| `remediation_subject_not_found` | 422 | The NA holds no such judgement or decision (retry once it does) |
| `remediation_subject_mismatch` | 422 | Another change, resource or disabled version than the subject's (quarantined) |
| `remediation_steps_mismatch` | 422 | Not the steps the NA stated (quarantined) |
| `remediation_rotation_missing` | 422 | The forward rotation's execution evidence is not stored yet (retry after submitting it) |
| `remediation_rotation_mismatch` | 422 | That evidence is not a rotation of the resource to `version_id` (quarantined) |
| `remediation_rotation_other_executor` | 422 | Another executor sovereign made it (quarantined) |
| `remediation_rotation_before_change` | 422 | It was stored before the record of the change, or executed before the change (quarantined) |
| `remediation_rotation_reused` | 422 | Another remediation already cites it (quarantined) |
| `remediation_not_due` | 409 | The change is not due or overdue: an allowed change under review, an upheld or waived one (quarantined) |
| `remediation_already_recorded` | 409 | The subject is already remediated (quarantined) |
| `remediation_conflict` | 409 | Another record with this `remediation_id`, or another remediation recorded first |
| `evidence_store_unavailable` | 503 | The record could not be stored; retry |

"Quarantined": the authentic record is kept as a `quarantine` entry named in
`error.details.quarantine_id`.

#### Operator routes

| Route | Purpose |
|---|---|
| `GET /admin/evidence/remediations` | The due queue: `?state=` a state above or `review_pending` (every change with a pending review, whatever its state); without it, the due, overdue and waived ones and the others with a pending review, except remediated ones (v1.5.0). `limit` (1-500, default 100) and `after` (the previous page's `next_after`). `{state, count, remediations: [...], next_after}`, oldest first; `400 invalid_remediation_query`; `read` tier |
| `GET /admin/evidence/remediations/<subject_id>` | One state, with `reviews` (its newest 100 review summaries, pending or decided; `reviews_truncated` when there are more) and `records` (its newest 100 stored remediation and review entries; `records_truncated`); `404 remediation_not_found`; `read` tier |
| `POST /admin/evidence/remediations/<subject_id>/notified` | Record that the controller told the actor: `{ "channel": "email" }` (optional, 1 to 64 characters). Writes the audit event `remediation_notified` (with `before_due`) and, on the first notice, `notified_at`; returns the state. `400 invalid_notice`, `404 remediation_not_found`, `503 evidence_store_unavailable` |
| `POST /admin/evidence/reviews` | Request a review: `{ "subject_kind": "judgement" or "decision", "subject_id": "...", "justification": "..." }` (1 to 1024 characters), no query string. `201` with `review_id` and the state (`review_pending: true`). See the errors below |
| `GET /admin/evidence/reviews/<review_id>` | A review summary, and once decided `record` (its stored entry); `404 review_not_found`; `read` tier |
| `POST /admin/evidence/reviews/<review_id>/decide` | Decide it (privileged): `{ "verdict": "uphold" or "deny" or "waive_until", "waive_until": "<RFC 3339 time>", "note": "..." }`, no query string. `200` with `review` (the stored `ReviewRecord` entry) and the state. See the errors below |

Review errors:

| Code | Status | Route | Meaning |
| --- | --- | --- | --- |
| `invalid_review` | 400 | both | A body field other than those listed, a value of the wrong form, a query string, a `waive_until` or `X-Admin-Timestamp` that is not RFC 3339 (`YYYY-MM-DDTHH:MM:SS`, a fraction of 1 to 6 digits, `Z` or `+HH:MM`), a `waive_until` not after now |
| `review_approval_invalid` | 400 | both | The request, as the review would embed it, would not verify offline (for example signed nearly 300 seconds before it arrived); nothing is recorded |
| `review_subject_not_found` | 404 | request | No such judgement or decision is stored |
| `review_not_found` | 404 | decide | No such review |
| `review_needs_named_holder` | 409 | both | The requester's or decider's key has no named holder in the store |
| `review_requested_by_actor` | 409 | request | The requester's key or holder is the change's actor's |
| `review_already_pending` | 409 | request | A review of the change is pending |
| `review_after_remediation` | 409 | request | The change is remediated |
| `illegal_transition` | 409 | request | A denied decision: it changed nothing |
| `review_already_decided` | 409 | decide | The review is decided |
| `review_same_holder_as_requester` | 409 | decide | The decider's key or holder is the requester's |
| `review_same_holder_as_actor` | 409 | decide | The decider's key or holder is the change's actor's |
| `review_not_pending` | 409 | decide | No review of the change is pending |
| `review_waiver_after_remediation` | 409 | decide | A waiver of a remediated change |
| `review_conflict` | 409 | both | The change's state moved while the request was handled; retry |
| `review_waiver_too_long` | 422 | decide | The waiver ends after `NA_REVIEW_MAX_WAIVER_SECONDS` |
| `review_waiver_beyond_lifetime` | 422 | decide | The waiver outlasts an emergency change's lifetime |
| `evidence_store_unavailable` | 503 | both | The review could not be stored; retry |

The two `POST` review routes keep the operator's signed request as received
(headers and body) and embed it in the `ReviewRecord`, so the request is part
of what the record proves: sign the exact body you send.

A boundary policy published with a `remediation`, `review_required` or
`emergency` section while the records are off is refused with
`400 policy_remediation_disabled`; an invalid section with
`400 boundary_policy_invalid` and the issue codes `invalid_remediation`,
`invalid_emergency` or `emergency_justification_not_required`. With the
records off, an evaluation a policy with such a section applies to is refused
with `409 policy_remediation_disabled`. Activating an emergency policy whose
capability another active policy names, or a policy naming an active
emergency policy's capability, is refused with
`409 emergency_capability_conflict`.

### Pre-issued grants (v1.6.0)

Grants a holder uses while it cannot reach the NA, with
`EVIDENCE_GRANTS=on` (otherwise `404 grants_disabled`, after the caller is
authenticated). The routes are beta; the records' signed forms are stable.
See {doc}`../operations/grants` for the rules and
{doc}`../examples/pre-issued-grants` for a walkthrough.

#### `POST /admin/grants`

Issue a grant. **Auth**: operator signature, privileged.

**Request**

```json
{
  "bearer_key_id": "site-7-device",
  "capabilities": ["secret.manage"],
  "attestation_id": "<attestation id>",
  "valid_from": "2026-06-01T08:00:00Z",
  "valid_until": "2026-06-01T12:00:00Z",
  "max_uses": 3,
  "max_uses_per_time_token": 2,
  "parameter_envelope": {
    "lifetime_days": {"number_range": {"number_type": "integer", "minimum": 1, "maximum": 60}},
    "region": {"one_of": ["eu-west", "eu-north"]},
    "scopes": {"subset_of": ["read", "write"], "required": false}
  }
}
```

Exactly one of `attestation_id` (an attestation this NA issued) and
`agreement` (an `AgreementRecord` it trusts, with an optional
`context_freshness_seq`). `valid_from` defaults to now and lies between now
(within 300 seconds) and 24 hours from now; times are RFC 3339 with an
offset. `max_uses` is required; `max_uses_per_time_token` defaults to the
NA's limit (or `max_uses` when lower). An envelope parameter has exactly one
of `one_of` (1 to 256 scalars, distinct type-strictly), `subset_of` (1 to 256
distinct strings) and `number_range` (`number_type` `integer` or `number`,
`minimum`, `maximum`, optional `exclusive_minimum` and `exclusive_maximum`);
`required` defaults to `true`. Names match `[A-Za-z0-9_-]{1,64}`, at most 64.

**Response** `201`: `grant` (the signed `CapabilityGrant`), `time_token` (the
first `TimeToken`, `use_sequence` 0), and its store entry (`entry`,
`entry_digest`).

**Errors**, in the order they are checked:

| Code | Status | Meaning |
| --- | --- | --- |
| `unexpected_field` | 400 | A field other than those above |
| `invalid_grant_request`, `ambiguous_basis` | 400 | A missing bearer, capability list or budget; not exactly one basis; a freshness sequence with an attestation |
| `invalid_grant_validity` | 400 | A time that is not RFC 3339, `valid_from` not before `valid_until`, or outside now to 24 hours from now |
| `grant_limit_exceeded` | 400 | The validity, budget or uses per time token over this NA's limit (`details.limit`, `details.maximum`) |
| `invalid_grant_envelope` | 400 | An envelope parameter that is not one of the kinds above (`details.errors`), or an envelope whose names or values look like secret material |
| `grant_bearer_key_unknown`, `grant_bearer_key_not_executor`, `grant_bearer_key_retired` | 422 | The bearer is not an active registered executor key |
| `invalid_agreement`, `agreement_untrusted` | 400, 422 | The agreement basis, as for evaluation |
| `grant_basis_invalid` to `grant_gate_may_deny` | 422 | The issuance check refused it: the first problem's reason, with every problem in `details.problems` (`reason`, `detail`, and `capability`, `policy_id`, `policy_version`, `gate_id` where they apply). The reasons and their order are in {doc}`../operations/grants` |
| `grant_issuance_conflict` | 409 | What the grant rests on (an active policy version, the bearer key, the attestation, the agreement's trust) changed between the check and the write, twice: retry |
| `evidence_store_unavailable` | 503 | The grant could not be stored; retry |

A `503 grant_store_integrity_failed` from any grant route means a grant the
database holds no longer verifies under the NA's signature: it is not used.

#### Reading and revoking grants

| Route | Purpose |
|---|---|
| `GET /admin/grants` | Grants, newest first by `issued_at`, then `grant_id`: `?status=active` (not revoked, not past its end; it includes summaries that say `scheduled` or `exhausted`), `expired` or `revoked`, `?bearer_key_id=`, `?limit=` (1-500, default 100), `?before=` (the previous page's `next_before`: the ID of its last grant). `{grants: [...], next_before}`; each summary has `grant_id`, `status` (`active`, `scheduled`, `exhausted`, `expired`, `revoked`), `bearer_key_id`, `bearer_sovereign_id`, `capabilities`, `basis_kind`, `basis_id`, `valid_from`, `valid_until`, `max_uses`, `uses` (admitted), `issued_at`, `issued_by_operator`, `store_sequence`, `revoked_at`, `revocation_reason`. `400 invalid_grant_filter`, `400 invalid_page`; `read` tier |
| `GET /admin/grants/<grant_id>` | One grant: its summary, `remaining_uses`, `chain_length` (the positions of its use chain, admitted and quarantined), `grant` (the signed grant), `policy_versions` and `revocation` (the signed `GrantRevocationRecord`, or `null`); `404 grant_not_found`; `read` tier |
| `GET /admin/grants/<grant_id>/uses` | Its use chain, newest first: `?limit=` (1-500, default 100), `?before=` (a `use_sequence`, the previous page's `next_before`). `{grant_id, uses: [...], next_before}`; each use has `use_id`, `use_sequence`, `state` (`admitted`, or `quarantined` for a refused use that continued the chain), `rejection_code` (`null` when admitted), `executed_at`, `recorded_at`, `store_sequence`, `resource_id`, `resource_sequence` (the position the NA assigned; `null` when quarantined or without a resource) and `outcome`. A use refused as a conflict or a chain mismatch is not in the chain (see the `quarantine` entries). `404 grant_not_found`, `400 invalid_page`; `read` tier (beta, v1.6.0 review fixes) |
| `POST /admin/grants/<grant_id>/revoke` | Revoke it now (privileged): `{ "reason": "..." }` (optional, 1 to 1024 characters). The body's `reason` is stored as the revocation's `detail`; the revocation's `reason` is always `operator`. `200` with `revocation`, `entry`, `entry_digest`; `404 grant_not_found`, `409 grant_already_revoked`, `400 invalid_grant_revocation` |

#### `POST /grants/time-tokens`

A time token for a grant's holder. **Auth**: the request's signature, by the
grant's bearer key. Rate limit `NA_RATE_LIMIT_EVIDENCE_PER_MINUTE`.

**Request** `{ "request": { "<TimeTokenRequest>": "..." } }`: `grant_id`,
`use_sequence` (the uses the holder has made, 0 before the first),
`use_head_digest` (the digest of the last of them; left out for none),
`requested_at` (within 300 seconds of the NA's clock), `signature`, in its
exact serialized form.

**Response** `201` `{ "time_token": {...} }`, bound to that chain head.

**Errors**: `400 invalid_time_token_request`; `422 time_token_request_malformed`,
`422 time_token_request_invalid_signature`, `422 time_token_request_stale`;
`404 grant_not_found`; `409 grant_bearer_key_retired`, `409 grant_revoked`,
`409 grant_expired` (the holder falls back to break-glass),
`409 grant_budget_exhausted`; `409 time_token_request_behind` (the NA holds
more uses of the chain, admitted or quarantined, than the request reports),
`409 time_token_request_mismatch` (the use the NA holds at that position is
not the one the request names).

#### `POST /evidence/grant-executions`

Submit one signed `GrantExecutionEvidence`, `{ "evidence": {...} }`, in its
exact serialized form. **Auth**: the record's signature, by the grant's
bearer key. Rate limit `NA_RATE_LIMIT_EVIDENCE_PER_MINUTE`.

**Response** `201` with `entry`, `entry_digest`, `payload`,
`"status": "recorded"` and `resource_sequence` (the position the NA assigned
in the resource's chain, or `null` without a resource); `200` with
`"status": "duplicate"` for the same record again, also when the retry raced
its own admission.

**Errors**: `400 invalid_grant_use`, then the reasons in
{doc}`../operations/grants` (*What the NA refuses*), each `422` except
`409 grant_use_conflict`; a refusal of an authentic use no retry overcomes
names the `quarantine` entry that keeps it in `error.details.quarantine_id`
(the same one when the same use is uploaded again). Every check after the
signature runs inside the write that stores the use or its quarantine entry.
`503 evidence_store_unavailable`: retry.

With grants on, `GET /admin/evidence/status` reports `evidence_grants`,
`grants_issued`, `grants_active`, `grants_revoked` and `grant_uses`;
`GET /admin/evidence/changes/<resource_id>` lists each use as a change of kind
`grant_execution`, `governed_by: grant`, with `grant_id`, `use_sequence` and
`observed_by`; `GET /admin/evidence/resource-heads/<resource_id>` names the
head's `entry_kind` (`execution` or `grant_execution`) and `record_id`; and
`GET /sovereign-revocation-feed` lists `revoked_grant_ids`.

---

## Edge nodes (v1.7.0)

*Unreleased.*

*Beta.* The routes an edge agent calls, and the operators' view of edge
nodes. An edge node enrols with an edge invite and registers its executor key
at `/join` (see {doc}`../reference/network-authority-api`); the operations
guide is {doc}`../operations/edge-agent`.

**Auth** for the three `/node/*` routes: a request the node key signs (the
node request signature in {doc}`../reference/network-authority-api`), with
these fields in the signed body:

| Field | Value |
| --- | --- |
| `cert_id`, `node_public_key` | A certificate of the node and its key |
| `purpose` | `node_boundary_evaluate`, `node_state` or `node_resource_head`: the route's own |
| `audience` | This NA's public key (`network_authority.public_key` of `/sovereign.json`) |
| `timestamp` | RFC 3339 UTC, within 300 seconds of the NA's clock |
| `nonce` | A UUID, used once: the nonces of `/heartbeat` and every `/node/*` route share one scope per node key |
| `signature` | Ed25519 by the node key over the canonical body without `signature` |

The checks run in this order: `400 missing_certificate_identity`;
`403 certificate_not_found`, `403 certificate_key_mismatch`,
`403 certificate_revoked`; `401 node_auth_failed` (signature, timestamp,
nonce, then a wrong `purpose` or `audience`, which spends the nonce);
`403 certificate_expired`, `403 certificate_not_yet_valid`,
`403 certificate_superseded`; `403 edge_node_not_enrolled` (the key is not an
edge node's), `403 edge_node_retired` (the node was revoked).

**Rate limits**: `NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE` (600) per client
address, counted before authentication, and `NA_RATE_LIMIT_NODE_PER_MINUTE`
(120) per node key, after it; `429 rate_limit_exceeded`.

### `POST /node/boundary/evaluate`

A signed decision for the node, under an attestation issued to it, with the
node's sovereign ID as the requester. An attestation is issued to the node
when this NA issued it (`issuer_sovereign_id` is this sovereign), its
`subject_id` is the node's sovereign ID and its `subject_public_key` is unset
or the node key.

**Request**

```json
{
  "cert_id": "<certificate id>",
  "node_public_key": "<node public key, base64>",
  "purpose": "node_boundary_evaluate",
  "audience": "<NA public key, base64>",
  "attestation_id": "<attestation id>",
  "requested_capability": "secret.rotate",
  "context": {
    "context_id": "<optional UUID>",
    "request_parameters": {"lifetime_days": 30},
    "attributes": {"site": "site7"},
    "requester_sovereign_id": "site7-17"
  },
  "timestamp": "2026-10-14T09:30:00.000000+00:00",
  "nonce": "<UUID>",
  "signature": "<Ed25519 signature, base64>"
}
```

`context.requester_sovereign_id` is optional; when present it must be the
node's sovereign ID.

**Response** `201` `{ "decision": {...}, "justification_proof": {...} }`: the
same signed records as `POST /admin/boundary/evaluate`, stored in the
evidence store with `requested_by` `node:<executor key ID>`. A revoked,
expired or not yet valid attestation gives a signed DENY, as there.

**Errors** (after authentication): `400 node_basis_unsupported` (an
`agreement`), `400 invalid_attestation_id`, `400 missing_boundary_fields`,
`400 invalid_context`; `403 node_requester_mismatch` (another requester);
`403 node_attestation_foreign` (an attestation not issued to the node, or
unknown). Neither `403` signs or stores a decision.

### `POST /node/state`

The node's certificate, its executor key, the attestations issued to it and
the grants its executor key bears.

**Request**

```json
{
  "cert_id": "<certificate id>",
  "node_public_key": "<node public key, base64>",
  "purpose": "node_state",
  "audience": "<NA public key, base64>",
  "timestamp": "2026-10-14T09:30:00.000000+00:00",
  "nonce": "<UUID>",
  "signature": "<Ed25519 signature, base64>"
}
```

**Response** `200`:

| Field | Content |
| --- | --- |
| `server_time` | The NA's time |
| `node` | `node_public_key`, `node_sovereign_id`, `cert_id` and `cert_expires_at` of the node's newest valid certificate, `roles` |
| `executor_key` | `key_id`, `public_key`, `executor_sovereign_id`, `role`, `resource_prefix`, `registered_at`, `retired_at` |
| `attestations` | `[{"attestation": <signed MembershipAttestation>, "status": "active"}]`: those issued to the node, active and not expired |
| `grants` | The signed `CapabilityGrant`s whose `bearer_key_id` is the executor key, neither revoked nor past their end, newest first, at most 100; `[]` with `EVIDENCE_GRANTS=off` |

### `POST /node/evidence/resource-head`

Where the next record of a resource under the node's resource prefix must
link.

**Request**

```json
{
  "cert_id": "<certificate id>",
  "node_public_key": "<node public key, base64>",
  "purpose": "node_resource_head",
  "audience": "<NA public key, base64>",
  "resource_id": "edge:site7-17/kv/db",
  "timestamp": "2026-10-14T09:30:00.000000+00:00",
  "nonce": "<UUID>",
  "signature": "<Ed25519 signature, base64>"
}
```

**Response** `200`: the body of `GET /admin/evidence/resource-heads/<id>`.
**Errors**: `403 node_resource_out_of_scope` (a `resource_id` that is missing
or does not start with the node's prefix), `404 resource_not_found`,
`404 evidence_store_disabled`.

### `GET /admin/edge-nodes`

Edge nodes, newest enrolment first (by `enrolled_at`, then
`node_public_key`). **Auth**: operator signature, `read` tier. Query:
`?status=online|offline|revoked`, `?node_sovereign_id=`, `?limit=` (1-500,
default 100), `?before=` (the previous page's `next_before`: the
`node_public_key` of its last node).

**Response** `200`

```json
{
  "count": 1,
  "next_before": null,
  "edge_nodes": [{
    "node_public_key": "<node public key>",
    "node_sovereign_id": "site7-17",
    "executor_key_id": "edge-3f1c0d4e9a7b2c6d8e0f1a2b3c4d5e6f",
    "resource_prefix": "edge:site7-17/",
    "roles": ["role:client"],
    "status": "online",
    "enrolled_at": "2026-10-14T09:00:00.000000+00:00",
    "cert_id": "<certificate id>",
    "cert_expires_at": "2026-10-21T09:00:00.000000+00:00",
    "last_seen_at": "2026-10-14T09:29:40.000000+00:00",
    "remote_addr": "203.0.113.17",
    "agent": {"version": "1.7.0", "snapshot_age_seconds": 42, "pending_uploads": 0, "dead_letters": 0,
              "reported_at": "2026-10-14T09:29:40.000000+00:00"},
    "grants": {"usable": 2, "admitted_uses": 7},
    "break_glass": {"records": 1, "last_executed_at": "2026-10-13T22:10:05Z"},
    "revoked_at": null,
    "revocation_reason": null
  }]
}
```

`status` is `revoked` once the node was revoked, `online` while its newest
heartbeat (across its certificates) is under 300 seconds old, as for
`/nodes`, and `offline` otherwise. `agent` is the agent block of its latest
heartbeat (`null` before one); `grants` counts the usable grants its executor
key bears and their admitted uses (`null` with grants off); `break_glass`
counts the break-glass records of its sovereign ID since it enrolled (`null`
with the store off). **Errors**: `400 invalid_edge_status`,
`400 invalid_page`.

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
