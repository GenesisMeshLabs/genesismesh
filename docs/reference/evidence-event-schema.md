# Evidence event schema (`gm.evidence.event` v1)

`GET /admin/evidence/export` returns one `gm.evidence.event` per line (JSON
Lines). This is GenesisMesh's stable, versioned structured event model for the
evidence store (v0.59). SIEM-specific formats such as CEF or Elastic Common
Schema are not part of GenesisMesh core: map them from this model outside it.

The evidence store is off by default. With `EVIDENCE_STORE=off` the NA records
nothing and the evidence routes answer `404 evidence_store_disabled`. Turn it
on before the first decision you want recorded: entries are not written
retroactively. The entry kinds of 1.3.0, 1.4.0 and 1.6.0 need further
switches, listed with each kind below. Edge nodes (1.7.0) need
`EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`.

Each event has three parts:

- `entry`: the store envelope (`store_sequence`, `entry_kind`, `recorded_at`,
  `payload_digest`, `prev_entry_digest`) and the search fields (`decision_id`,
  `vendor_id`, `attestation_id`, `capability`, `outcome`, `resource_id`,
  `resource_action`, `resource_sequence`, `executor_sovereign_id`, ...). Since
  1.3.0 also `record_id`, `subject_id`, `matched_evidence_id` and
  `observation_sequence`, which are left out when absent, so entries written
  before 1.3.0 keep their digests.
- `entry_digest`: SHA-256 of the canonical envelope; the next event's
  `entry.prev_entry_digest` equals it, so the export is one hash chain.
- `payload`: the stored signed record, unchanged:

  | `entry_kind` | `payload` | Signed by |
  | --- | --- | --- |
  | `decision` | `{decision, context}` | the NA (the decision) |
  | `justification` | `JustificationProof` | the NA |
  | `execution` | `ExecutionEvidence` | an executor key |
  | `retention_checkpoint` | `RetentionCheckpoint` | the NA |
  | `observation` (1.3.0) | `ObservationRecord` | an observer key |
  | `break_glass` (1.3.0) | `BreakGlassRecord` | an executor key |
  | `judgement` (1.3.0) | `JudgementRecord` | the NA |
  | `quarantine` (1.3.0) | `QuarantineRecord` | the NA |
  | `registry` (1.3.0) | `RegistryRecord` | the NA |
  | `remediation` (1.4.0) | `RemediationRecord` | an executor key |
  | `review` (1.4.0) | `ReviewRecord` | the NA |
  | `key_succession` (1.5.0) | `KeySuccessionRecord` | the root key, the new NA key and the outgoing NA key |
  | `archive` (1.5.0) | `ArchiveRecord` | the NA |
  | `grant` (1.6.0) | `CapabilityGrant` | the NA |
  | `grant_execution` (1.6.0) | `GrantExecutionEvidence` | the grant's bearer key (a registered executor key); its nested time token by the NA |
  | `grant_revocation` (1.6.0) | `GrantRevocationRecord` | the NA |

  Entry kinds are added within schema version 1. A verifier refuses a kind it
  does not know by name (`unknown_entry_kind`) and keeps it in the chain. The
  NA writes the 1.3.0 kinds only with `EVIDENCE_OUT_OF_BAND=on`, and the
  1.4.0 kinds only with `EVIDENCE_REMEDIATION=on`, so a store stays readable
  by the verifiers of the release before until the switch is turned on. Since
  1.4.0 a `quarantine` record's `record_kind` may also be `remediation`. The
  1.5.0 kinds are written only when an operator records a key succession or
  an archive: upgrade the verifiers that read your exports before you do. The
  1.6.0 kinds are written only with `EVIDENCE_GRANTS=on`, which also lets a
  `quarantine` record's `record_kind` be `grant_execution` and a judgement's
  `governed_by` be `grant`. A `grant_execution` entry's `resource_sequence`
  is the position the NA assigned the use in its resource's chain when it
  admitted it: it is in the envelope, not in the signed use, and the next
  record of that resource links to the use's digest.

  Since 1.5.0 an NA signature is checked with the NA's key history: the key
  valid at the entry's `recorded_at` (a retention run carries registry,
  key succession and archive entries past its checkpoint with the time they
  were first recorded). Entries are recorded in time order: an entry's
  `recorded_at` is at most 300 seconds behind any entry before it, except
  the entries a retention run carried forward. The windows, the time order
  and the record times of records outside the store are in
  {doc}`audit-pack-format`.

Verify an export offline with `genesis-mesh evidence verify-export` (see the
{doc}`CLI reference <cli/evidence-audit>`).

## Verifying an export

Every verifier of exports (the Python reference and CLI, the TypeScript SDK,
and the Rust SDK with `genesis-mesh-verify`) checks an export the same way
and names each failure by the same reason, with the
`store_sequence` of the entry it concerns. The shared cases are the
conformance suites `field_registry`, `out_of_band`, (1.4.0) `remediation`,
(1.5.0) `audit` and (1.6.0) `grants`. The Go and .NET SDKs do not verify
exports.

### Reading the lines

A line is read strictly (see {doc}`canonical-form`, *Accepted input*), and it
must be a `gm.evidence.event` as every verifier reads it (1.3.1): exactly
`schema`, `schema_version` (the integer 1), `entry`, `entry_digest` and
`payload`; an envelope with each search field present as a string or `null`,
`store_sequence` a positive integer and the sequence numbers integers, and
`recorded_at` a timestamp `YYYY-MM-DDTHH:MM:SS` with up to six fraction
digits and `Z` or an offset. A line that is not is refused while the export
is read (`invalid evidence event envelope or unsupported schema`), as a
`store_sequence` written `"6"` is.

Everything is checked as received (1.3.1): the envelope's digest is computed
over the envelope as it arrived (its 1.3.0 fields read the same absent or
`null`), and the chains link to each execution record as it arrived. An
envelope respelled after it was written (a `recorded_at` offset written
`+00:00`) no longer matches its digest or a held anchor. Before 1.3.1 the
reference hashed the envelope as it reads it, which hid such a change.

### Failures

The store chain:

| Reason | The entry |
| --- | --- |
| `entry_digest_mismatch` | its envelope, as received, is not what `entry_digest` names |
| `payload_digest_mismatch` | its payload is not what the envelope's `payload_digest` names |
| `store_sequence_gap`, `store_chain_break` | does not follow the previous entry, or does not link to its digest |
| `unknown_entry_kind` | is of a kind this release does not know; it still takes its place in the chain |
| `duplicate_record` (1.3.1) | holds a record whose ID an earlier entry of the same kind holds: a copied entry, not a second record |

Each record:

| Reason | The record |
| --- | --- |
| `payload_invalid` | cannot be read as its model, or carries a field outside its signature where none may be: a retention checkpoint and every kind since 1.3.0 (observation, break-glass, judgement, quarantine, registry, remediation, review, key succession, archive) |
| `invalid_signature` | is not signed, as received, by a key allowed to sign it; also, with no `store_sequence`, a retention checkpoint passed to the verifier that the NA did not sign (1.3.1; nothing else is then checked) |
| `unknown_field` | is authentic and carries a signed field this release does not know |
| `non_canonical_form` | is authentic and signed over a form the reference does not write |
| `na_key_not_valid_at_time` (1.5.0) | is signed by a key of the NA's key history that was not valid at the entry's `recorded_at`, or (review fixes) not at the latest `recorded_at` of the entries before it, when that is later |
| `recorded_at_out_of_order` (1.5.0) | is recorded more than 300 seconds before an entry stored ahead of it (entries a retention run carried forward excepted: `registry`, `key_succession` and `archive` entries in an unbroken run right after a `retention_checkpoint` entry) |
| `decision_outlives_key` (1.5.0) | is a decision that stays valid past what the key that signed it may vouch for: that key's end (its succession, or its enforced `valid_to`), the 300-second hand-over and 300 seconds |
| `evidence_unknown_executor`, `evidence_executor_key_retired` (1.5.0, in a pack) | is a key-signed record whose key the registry records place after it, or retired before it |
| `succession_invalid_root_signature`, `succession_invalid_new_key_signature`, `succession_not_in_history`, `succession_backdated` (1.5.0) | is a key succession the root key or the new key did not sign, one the key history the verifier holds does not contain, or one recorded less than 60 seconds before it takes effect (or issued after it) |
| `envelope_mismatch` (1.3.0) | is a 1.3.0 kind whose envelope names something its payload does not: the fields below (since 1.3.1 all of them; 1.3.0 checked `record_id`, `resource_id` and a judgement's `subject_id`) |
| `quarantine_digest_mismatch` (1.3.0) | is a quarantine record whose `record_digest` is not the digest of the record it holds |

A record carrying a field outside its signature (stored as submitted before
1.1.1) gets the warning `unsigned_field`; since 1.3.1 the rest of it is still
checked as received. That holds for decisions, justification proofs and
execution evidence, whose models read extra fields; a retention checkpoint
and every kind since 1.3.0 are read strictly, so such a field also makes the
record `payload_invalid` (the conformance vector
`export-checkpoint-unsigned-field` pins it).

The envelope fields a 1.3.0 entry takes from its record, which must match
(`envelope_mismatch`); an absent field is `null`:

| Kind | Envelope field: payload field |
| --- | --- |
| `observation` | `record_id`: `observation_id`, `resource_id`, `resource_action`: `action`, `capability`, `executor_sovereign_id`: `observer_sovereign_id` |
| `break_glass` | `record_id`: `break_glass_id`, `resource_id`, `resource_action`, `capability`, `executor_sovereign_id`, `attestation_id`, `outcome` |
| `judgement` | `record_id`: `judgement_id`, `subject_id`, `resource_id`, `resource_action`: `action`, `capability`, `outcome`: `verdict`, `matched_evidence_id` |
| `quarantine` | `record_id`: `quarantine_id`, `resource_id`, `outcome`: `rejection_code` |
| `registry` | `record_id`: `registry_record_id`, `outcome`: `event` |
| `remediation` (1.4.0) | `record_id`: `remediation_id`, `subject_id`, `resource_id`, `executor_sovereign_id`, `outcome` |
| `review` (1.4.0) | `record_id`: `review_id`, `subject_id`, `resource_id`, `capability`, `outcome`: `verdict` |
| `key_succession` (1.5.0) | `record_id`: `succession_id` |
| `archive` (1.5.0) | `record_id`: `archive_id` |
| `grant` (1.6.0) | `record_id`: `grant_id`, `executor_sovereign_id`: `bearer_sovereign_id` |
| `grant_execution` (1.6.0) | `record_id`: `use_id`, `subject_id`: `grant_id`, `resource_id`, `resource_action`, `capability`, `executor_sovereign_id`, `outcome`, `exec_sequence_no`: `use_sequence`; `resource_sequence` is set exactly when `resource_id` is |
| `grant_revocation` (1.6.0) | `record_id`: `revocation_id`, `subject_id`: `grant_id`, `outcome`: `reason` |

The chains and links between records:

| Reason | The entry |
| --- | --- |
| `evidence_chain_break`, `resource_chain_break` | an execution record that does not follow the previous record of its decision or its resource |
| `evidence_decision_denied`, `evidence_outside_decision_window`, `evidence_capability_mismatch` | an execution record its decision in the export does not cover |
| `evidence_cites_judgement` | an execution record resting on a judgement or a record of one |
| `observation_chain_break` | an observation out of its resource's positions |
| `duplicate_judgement` | a second judgement of one record (a record is its kind and ID) |
| `judgement_subject_mismatch`, `judgement_subject_missing` | a judgement whose record is another kind, digest or position, or is not in the export where the export reaches back to the record's position |
| `judgement_match_missing` (1.3.1) | a judgement matching execution evidence or a break-glass record that the export does not hold before it, in an export from entry 1 |
| `match_reused` | a second judgement matching the same record |
| `retention_count_mismatch` (1.3.1) | a retention checkpoint that removed fewer or more entries than lay between the checkpoint before it (or entry 1) and its last removed position |
| `cited_record_missing` (1.5.0) | in an audit pack, a record citing a decision, subject or matched record that neither the range nor the pack's cited records hold |

Remediations and reviews (1.4.0). "From its start" means a run from entry 1
or right after the retention checkpoint passed to the verifier: retention
keeps a remediation or review with its subject, and the subject of an open
remediation, so such a run holds them all.

| Reason | The entry |
| --- | --- |
| `duplicate_remediation` | a second remediation of one judgement or decision |
| `remediation_subject_mismatch` | a remediation of another resource or change than the judgement it names, disabling another version than that change made, or naming as its change execution evidence of another decision or resource |
| `remediation_subject_missing`, `remediation_rotation_missing` | a remediation whose judgement or decision, or whose forward rotation's execution evidence, is not in a run that holds the store from its start |
| `remediation_rotation_mismatch` | a remediation whose forward rotation is of another resource |
| `remediation_rotation_other_executor` | a remediation whose forward rotation another executor sovereign made |
| `remediation_rotation_before_change` | a remediation whose forward rotation is stored before the record of the change, or executed before the change (an older version: a roll back) |
| `remediation_rotation_reused` | a remediation whose forward rotation an earlier remediation cites |
| `review_approval_invalid` | a review whose embedded admin requests do not prove it: a signature that does not verify over the request kept, another route, key, audience, verdict, waiver end, note, subject or justification than the review records, a `waive_until` or admin timestamp that is not RFC 3339 (`YYYY-MM-DDTHH:MM:SS`, a fraction of 1 to 6 digits, `Z` or `+HH:MM`), or signed more than 300 seconds from when the NA recorded it |
| `review_approval_key_mismatch` | a review whose decider or requester signed with another public key, or as another holder, than the holder registry in the export records for that operator key at the time; only registry records that verify as the NA's count |
| `review_same_holder` | a review decided by the requester's key or holder, or by the actor's (the actor may be the operator key that asked for a decision) |
| `review_subject_mismatch`, `review_subject_missing` | a review naming another digest than its judgement's or decision's, or whose subject is not in a run that holds the store from its start |
| `review_waiver_after_remediation` | a waiver of a change the export holds a remediation of before it |

A review's approvals are checked with the review alone and the NA's public
key (the audience); see *What a review proves offline* in
{doc}`../operations/remediation-and-reviews`.

Grants (1.6.0). A grant use is signed by its grant's bearer key, a
registered executor key (its key is placed in the store as any executor
key's); its nested time token by the NA key valid at the token's
`issued_at`. A grant whose own signature fails is not held: its uses and its
revocation are checked as for a grant the run does not hold.

A grant's **use chain** is its admitted uses and the quarantined uses that
continued it: a `quarantine` entry whose `record_kind` is `grant_execution`,
whose record is signed by the grant's bearer key and is at the next
position of the chain (`use_sequence` one past the head, `prev_use_digest`
the head's digest) becomes the chain's head, so the next use may link to it
and a time token may name it. The **budget** counts admitted uses, when the
run holds the chain from its first use (a whole store, a pack, or a run
whose first use of the grant is use 1); the **order and time rules** compare
a use with the last admitted use.

Each use is checked in this order (the chain first, then the use against its
grant; the first rule of `use_problem` that applies is reported; checks that
need the grant, the chain or an earlier use run only when the run holds
them):

| Reason | The entry |
| --- | --- |
| `grant_use_chain_break` | a use that does not continue its grant's chain (`use_sequence`, `prev_use_digest`), in a run that holds the chain from its start |
| `grant_missing` | a grant use or revocation whose grant the run does not hold, or holds unauthenticated, in a run that holds the store from its start (in a pack: `cited_record_missing`) |
| `grant_bearer_mismatch` | a use not signed by the grant's bearer key, or naming another executor sovereign than the grant's bearer |
| `grant_use_out_of_scope` | a use signed by a key with a resource prefix, naming no resource or one outside the prefix |
| `grant_mismatch` | a use or revocation naming another digest than its grant's (`grant_digest`) |
| `grant_capability_mismatch`, `grant_envelope_mismatch`, `grant_budget_exhausted` | a use of a capability the grant does not name, outside its closed envelope, or after the grant's admitted uses reached its budget |
| `grant_time_token_invalid` | a use whose time token is not signed by the NA (by the key valid at its `issued_at`), is another grant's, or is older than the grant (`issued_at`) |
| `grant_time_token_mismatch` | a use whose time token was issued after a later use (its `use_sequence` is not below the use's), or names another use (`use_head_digest`) than the run holds at that position, or one dated more than 300 seconds after the token |
| `grant_time_token_regressed`, `grant_time_token_exhausted` | a use citing an older token than the previous admitted use, or more than `max_uses_per_time_token` positions after the use its token names (`use_sequence` minus the token's `use_sequence`) |
| `grant_use_before_time_token`, `grant_use_out_of_order` | a use dated more than 300 seconds before its time token, or before the previous admitted use |
| `grant_use_outside_validity`, `grant_use_in_future`, `grant_use_uploaded_late` | a use dated outside its grant's validity, more than 300 seconds after its entry's `recorded_at`, or recorded longer after it was made than the grant's validity |
| `grant_revoked` | a use dated at or after a revocation of its grant the run holds before it |
| `duplicate_grant_revocation` | a second revocation of one grant |
| `duplicate_record` | also a use whose `use_id` is the ID of execution evidence or a break-glass record (observations match all three by ID), or such a record whose ID is a use's |
| `resource_chain_break` | a use whose envelope `resource_sequence` does not follow its resource's chain |
| `envelope_mismatch` | also a use given a `resource_sequence` without a resource |

### Where an export starts

An export from entry 1, or right after a retention checkpoint passed to the
verifier (the CLI passes the one the export holds), holds every chain from
its start. An export that starts anywhere else, such as a later page or an
export since a position, takes the first record it holds of each resource
and the first observation of each as where that chain starts (1.3.1; before,
a resource chain spanning its start failed `resource_chain_break`). A
judgement's matched record is then checked only in an export from entry 1,
and a checkpoint's count only against the checkpoint before it when the
export holds that one. An export after retention is tied to its checkpoint
only when it holds the checkpoint's entry; held anchors tie an export at its
start only as described in {doc}`../operations/evidence-anchors`.

## Versioning

- Adding an optional field keeps `schema_version` 1.
- Removing a field, renaming it or changing its meaning is a new schema
  version. The previous version stays available during the deprecation window
  in `DEPRECATION_POLICY.md`.
- `payload` records keep their own signing formats; their canonical forms do
  not change within a schema version.

## JSON Schema

Published in the repository as `docs/schemas/gm.evidence.event.v1.json`
(identifier `urn:genesismesh:schema:gm.evidence.event:v1`). A test fails if the
model and this file disagree.

```{literalinclude} ../schemas/gm.evidence.event.v1.json
:language: json
```
