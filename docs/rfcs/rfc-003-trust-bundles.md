# RFC-003 — Trust Bundles

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-001, RFC-002, RFC-004

## Abstract

A *trust bundle* is a portable, redacted collection of a sovereign's public
trust material, assembled so that an operator can review another sovereign
*before* deciding to recognize it. This RFC defines what a bundle contains, what
validation of a bundle does and does not prove, and the redaction rules that
keep a bundle safe to share. A trust bundle is review input; it is never itself
a grant of trust.

## Motivation

Before a treaty (RFC-002) is issued, the accepting operator needs something to
review: the candidate sovereign's identity, genesis, recognition posture,
revocation feed, and recognition graph, fetched from public endpoints and frozen
into a single reviewable artifact. The trust bundle exists so that this review
material is portable, hashable, and auditable without exposing any private
control material.

## Terminology

- **Trust bundle** — the portable artifact defined here.
- **Source endpoint** — the public base URL the bundle was assembled from.
- **Bundle hash** — a content hash recorded by the importer as an audit anchor.
- **Import receipt** — the importer's record of what was reviewed and whether
  trust was granted afterward (out of band).

## Normative requirements

1. A trust bundle **MUST** identify itself with `bundle_type` and
   `bundle_version` so consumers can detect format changes.
2. A trust bundle **MUST** carry the subject's public identity material:
   `sovereign_id`, `sovereign_metadata`, and `genesis`.
3. A trust bundle **MUST** carry the subject's `recognition_policy` and
   `revocation_feed` (or an explicit skipped marker) so the reviewer can see the
   subject's current recognition and revocation posture.
4. A trust bundle **MUST** carry a `connectome` section summarizing recognition
   edges, active treaties, and revoked trust material (RFC-006).
5. A trust bundle **MUST** record `created_at` and `source_endpoint`.
6. A trust bundle **MUST NOT** contain any private material listed under
   Redaction rules.
7. Importing a trust bundle **MUST NOT**, by itself, grant trust. The act of
   granting trust is a separate, explicit operator action (typically issuing a
   treaty under RFC-002).
8. An importer **MUST** be able to compute and record a stable bundle hash for
   audit.

## Data model

The reference implementation builds the bundle in
`genesis_mesh/cli/trust_bundle.py` (`export_trust_bundle`):

```json
{
  "bundle_type": "<bundle type tag>",
  "bundle_version": "<format version>",
  "created_at": "<iso8601>",
  "source_endpoint": "https://na.example.org",
  "sovereign_id": "USG-NB",
  "network_version": "<version>",
  "sovereign_metadata": { "...": "RFC-001 identity material" },
  "genesis": { "...": "public genesis document" },
  "recognition_policy": { "...": "subject recognition posture" },
  "revocation_feed": { "...": "RFC-004 feed or {\"status\": \"skipped\"}" },
  "connectome": {
    "summary": { "...": "RFC-006 counts" },
    "recognition_edges": [],
    "active_treaties": [],
    "revoked_trust_material": []
  },
  "endpoint_checks": {
    "healthz": "<status>",
    "readyz": "<status>"
  }
}
```

## Verification rules

1. A reviewer **MUST** treat bundle contents as claims to be checked, not as
   trust. Signatures inside embedded objects (genesis, attestations, treaties,
   feeds) are verified under their own RFCs.
2. Validation of a bundle proves only that the public material is internally
   consistent and well-formed at fetch time. It does **NOT** prove the subject
   is honest, available, or worthy of recognition.
3. `endpoint_checks` reflect liveness at assembly time and **MUST NOT** be
   treated as a continuing guarantee.
4. An importer **SHOULD** record an import receipt that links the bundle hash to
   the subsequent trust decision so the decision is auditable.

## Security considerations

A trust bundle **MUST NOT** include any of the following (the redaction rules,
mirrored from the proof-bundle schema):

- Private keys.
- Operator signatures over admin actions.
- Admin nonces.
- Raw request headers.
- Full private genesis material beyond the public genesis document.
- Local filesystem paths.
- Database paths.

A bundle **MAY** include public endpoints, network names, public-key prefixes,
attestation/treaty/feed identifiers, verification reason codes, and Connectome
summary counts. Guiding rule: *if a bundle needs private material to be
convincing, the proof is not ready to share.*

## Operational considerations

- Bundles are assembled from public endpoints, so assembling one **SHOULD** be
  possible by any reviewer, not only the subject operator.
- Importers **SHOULD** keep import receipts as part of their audit trail,
  especially for adoption-proof workflows where the bundle backs a public claim.

## Compatibility notes

- `bundle_version` exists so consumers can branch on format. Consumers **MUST**
  reject a `bundle_version` they do not understand rather than guess.
- Embedded objects follow their own RFCs; a change to those formats is governed
  by those RFCs, not this one.

## Open questions

- Should the bundle carry a detached signature by the assembling operator to
  bind `created_at` and `source_endpoint`, or is the recorded bundle hash plus
  import receipt sufficient?
- Should bundles support incremental/delta refresh rather than full re-fetch for
  continuity checks (RFC-007)?
