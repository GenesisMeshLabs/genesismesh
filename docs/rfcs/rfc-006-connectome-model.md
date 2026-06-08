# RFC-006 — Connectome Model

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-002, RFC-004

## Abstract

The *Connectome* is the graph model that makes recognition and trust-path state
visible without becoming a source of trust. This RFC defines the recognition
graph export (the machine-readable source data), the derived operator-facing
view, the trust-path explanation, and the strict boundary between
visualization-only data and protocol truth. Any number of interchangeable
viewers may consume the export; none of them becomes an authority over what the
network can see or rank.

## Motivation

Operators need to answer "why is this member or sovereign trusted?", "who
recognizes whom?", and "what is the blast radius of this revocation?" — without
inventing a second source of truth. The Connectome consumes the same signed
trust material defined in RFC-002 and RFC-004 and presents it as a graph. It
explains; it does not decide.

## Terminology

- **Recognition graph export** — the raw, machine-readable graph emitted by a
  sovereign's Network Authority.
- **Connectome view** — the sorted, summarized projection of the export for
  operators.
- **Recognition edge** — a directed edge from issuer to subject sovereign,
  backed by a treaty (RFC-002).
- **Trust path** — a sequence of active recognition edges connecting two
  sovereigns.
- **Blast radius** — the set of accepting sovereigns affected by an imported
  revocation (RFC-004).

## Normative requirements

1. The recognition graph export **MUST** contain `sovereigns`,
   `recognition_edges`, `active_treaties`, and `revoked_trust_material`.
2. Each recognition edge **MUST** carry `from`, `to`, `treaty_id`, `status`, and
   a `lifecycle_state`. Edges **SHOULD** also carry `expiry_risk`, `valid_from`,
   and `expires_at` for operator review.
3. An edge **MUST** be considered active only when its `status` is `active` and
   its `lifecycle_state` is `active` or `expiring_soon`. An edge is revoked when
   its `status` is `revoked` or its `lifecycle_state` is `revoked` or
   `replaced`.
4. A trust-path explanation **MUST** report a boolean `trusted` and a stable
   `reason` code, and **MUST** be derivable purely from the export (no hidden
   state).
5. The Connectome **MUST NOT** be treated as a trust authority. A viewer
   **MUST NOT** grant or deny admission based on the view; admission decisions
   come from RFC-002 and RFC-004 verification.
6. Imported revocations **MUST** be explainable as a blast radius linking each
   revoked attestation to the accepting sovereigns that recognized its issuer.
7. The export **MUST** be deterministic enough to compare across fetches; the
   reference implementation sorts sovereigns, edges, and revoked material by
   stable keys.

## Data model

The reference implementation produces the export in
`export_recognition_graph` (`genesis_mesh/na_service/db_trust.py`) and derives
the view and path explanation in `genesis_mesh/trust/connectome.py`:

```json
{
  "sovereigns": [{"sovereign_id": "USG"}, {"sovereign_id": "USG-NB"}],
  "recognition_edges": [
    {
      "from": "USG",
      "to": "USG-NB",
      "treaty_id": "<uuid>",
      "status": "active",
      "lifecycle_state": "active",
      "expiry_risk": "low",
      "valid_from": "<iso8601>",
      "expires_at": "<iso8601>"
    }
  ],
  "active_treaties": [{ "...": "RFC-002 treaty objects" }],
  "revoked_trust_material": [
    {
      "type": "membership_attestation",
      "id": "<attestation id>",
      "issuer_sovereign_id": "USG-NB",
      "feed_id": "<uuid>",
      "sequence": 1,
      "reason": "compromise",
      "revoked_at": "<iso8601>"
    }
  ]
}
```

The derived view adds a `summary` with counts (`sovereign_count`,
`recognition_edge_count`, `active_edge_count`, `revoked_edge_count`,
`revoked_trust_material_count`, `imported_revocation_count`) and a
`revocation_blast_radius`.

## Verification rules

Trust-path explanation (`explain_trust_path`) returns one of:

1. `active_treaty_path` — an active edge path exists from source to target;
   `trusted` is true and `path`/`hop_count` describe it. The reference
   implementation finds a shortest active path via breadth-first search.
2. `direct_treaty_revoked` — no active path, but a revoked direct edge explains
   the failure; `trusted` is false.
3. `no_active_treaty_path` — no active path and no explaining revoked edge;
   `trusted` is false.

These reason codes are explanations of state, not admission decisions.

## Security considerations

- The Connectome is read-only and derived from already-signed material. It adds
  no new trust authority, so a compromised or biased viewer cannot change what
  the protocol accepts.
- Because viewers are interchangeable, no single Connectome implementation can
  become a chokepoint that decides what the network is "allowed" to see.
- The export carries identifiers and coarse reasons, consistent with RFC-004's
  no-payload-leak rule.

## Operational considerations

- The export is intentionally earlier and simpler than any rich visualization
  product, so operators can verify recognition is forming before a viewer
  exists.
- A trust bundle (RFC-003) carries a Connectome summary so a reviewer sees graph
  context for the subject sovereign.
- Atlas, the public explorer described in {doc}`/development/atlas`, is intended
  to consume this export rather than introduce a second source of truth.

## Compatibility notes

- The export field set is the interoperability contract. Viewers **MUST** ignore
  unknown fields and **MUST NOT** require fields beyond those marked required
  here.
- Lifecycle vocabulary (`active`, `expiring_soon`, `expired`, `revoked`,
  `replaced`) is shared with RFC-002; changes are governed there.

## Open questions

- Should multi-hop trust paths be admissible (transitive recognition), or remain
  explanation-only? RFC-002 currently admits on direct treaties only.
- Should the export include capability overlays (RFC-005) as a first-class
  section, or remain a separate secondary view?
