# Evidence event schema (`gm.evidence.event` v1)

`GET /admin/evidence/export` returns one `gm.evidence.event` per line (JSON
Lines). This is GenesisMesh's stable, versioned structured event model for the
evidence store (v0.59). SIEM-specific formats such as CEF or Elastic Common
Schema are not part of GenesisMesh core: map them from this model outside it.

Each event has three parts:

- `entry`: the store envelope (`store_sequence`, `entry_kind`, `recorded_at`,
  `payload_digest`, `prev_entry_digest`) and the search fields (`decision_id`,
  `vendor_id`, `attestation_id`, `capability`, `outcome`, `resource_id`,
  `resource_action`, `resource_sequence`, `executor_sovereign_id`, ...).
- `entry_digest`: SHA-256 of the canonical envelope; the next event's
  `entry.prev_entry_digest` equals it, so the export is one hash chain.
- `payload`: the stored signed record, unchanged: a decision with its context
  (`entry_kind` `decision`), a justification proof, the controller's signed
  execution evidence, or a signed retention checkpoint.

Verify an export offline with `genesis-mesh evidence verify-export` (see the
{doc}`CLI reference <cli>`).

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
