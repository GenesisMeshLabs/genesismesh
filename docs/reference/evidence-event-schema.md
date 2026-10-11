# Evidence event schema (`gm.evidence.event` v1)

`GET /admin/evidence/export` returns one `gm.evidence.event` per line (JSON
Lines). This is GenesisMesh's stable, versioned structured event model for the
evidence store (v0.59). SIEM-specific formats such as CEF or Elastic Common
Schema are not part of GenesisMesh core: map them from this model outside it.

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

  Entry kinds are added within schema version 1. A verifier refuses a kind it
  does not know by name (`unknown_entry_kind`) and keeps it in the chain. The
  NA writes the 1.3.0 kinds only with `EVIDENCE_OUT_OF_BAND=on`, and the
  1.4.0 kinds only with `EVIDENCE_REMEDIATION=on`, so a store stays readable
  by the verifiers of the release before until the switch is turned on. Since
  1.4.0 a `quarantine` record's `record_kind` may also be `remediation`.

Verify an export offline with `genesis-mesh evidence verify-export` (see the
{doc}`CLI reference <cli>`).

## Verifying an export

Every verifier (the reference, the CLI and the SDKs) checks an export the
same way and names each failure by the same reason, with the
`store_sequence` of the entry it concerns. The shared cases are the
conformance suites `field_registry`, `out_of_band` and (1.4.0)
`remediation`.

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
| `payload_invalid` | cannot be read as its model, or carries a field outside its signature where none may be (records of 1.3.0 kinds) |
| `invalid_signature` | is not signed, as received, by a key allowed to sign it; also, with no `store_sequence`, a retention checkpoint passed to the verifier that the NA did not sign (1.3.1; nothing else is then checked) |
| `unknown_field` | is authentic and carries a signed field this release does not know |
| `non_canonical_form` | is authentic and signed over a form the reference does not write |
| `envelope_mismatch` (1.3.0) | is a 1.3.0 kind whose envelope names something its payload does not: the fields below (since 1.3.1 all of them; 1.3.0 checked `record_id`, `resource_id` and a judgement's `subject_id`) |
| `quarantine_digest_mismatch` (1.3.0) | is a quarantine record whose `record_digest` is not the digest of the record it holds |

A record carrying a field outside its signature (stored as submitted before
1.1.1) gets the warning `unsigned_field`; since 1.3.1 the rest of it is still
checked as received.

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

Remediations and reviews (1.4.0):

| Reason | The entry |
| --- | --- |
| `duplicate_remediation` | a second remediation of one judgement or decision |
| `remediation_subject_mismatch` | a remediation of another resource than the judgement it names |
| `remediation_subject_missing`, `remediation_rotation_missing` | a remediation whose judgement or decision, or whose forward rotation's execution evidence, is not in the export before it, in an export from entry 1 |
| `remediation_rotation_mismatch` | a remediation whose forward rotation is of another resource |
| `review_approval_invalid` | a review whose embedded admin requests do not prove it: a signature that does not verify over the request kept, another route, key, audience, verdict, waiver end, note, subject or justification than the review records, or signed more than 300 seconds from when the NA recorded it |
| `review_approval_key_mismatch` | a review whose decider or requester signed with another public key, or as another holder, than the holder registry in the export records for that operator key at the time |
| `review_same_holder` | a review decided by the requester's key or holder, or by the holder the actor maps to |
| `review_subject_mismatch`, `review_subject_missing` | a review naming another digest than its judgement's or decision's, or whose subject is not in the export, in an export from entry 1 |
| `review_waiver_after_remediation` | a waiver of a change the export holds a remediation of before it |

A review's approvals are checked with the review alone and the NA's public
key (the audience); see *What a review proves offline* in
{doc}`../operations/remediation-and-reviews`.

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
