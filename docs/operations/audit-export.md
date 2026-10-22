# Audit Export

Genesis Mesh stores Network Authority audit events in the NA database (SQLite
or PostgreSQL). For managed sovereign operation, export those events regularly
enough that an operator can reconstruct trust decisions after an incident.

`genesis-mesh managed audit-export` reads a SQLite file only (`--db-path`).
With PostgreSQL, query the audit table with your database tools.

**The audit events are not signed.** They are rows in the NA database, so
whoever can write the database can change them, and an export shows what the
database holds, not that nobody changed it. For records that can be verified,
turn on the evidence store (`EVIDENCE_STORE=on`, off by default), keep copies
of its anchors ({doc}`evidence-anchors`) and build audit packs
({doc}`audit-packs`, {doc}`audit-verification`).

## Export Command

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /var/log/genesis-mesh/audit-events.jsonl
```

The default format is JSON Lines for SIEM-style ingestion. Use `--format json`
for a JSON array:

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output ./audit-events.json \
  --format json
```

Filter one event class:

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output ./treaty-issued.jsonl \
  --event-type recognition_treaty_issued
```

## Trust-Decision Fields

Trust-related audit events should be inspected for these fields when present:

- `event_id`
- `event_type`
- `created_at`
- `details.attestation_id`
- `details.treaty_id`
- `details.feed_id`
- `details.issuer_sovereign_id`
- `details.subject_sovereign_id`
- `details.accepted`
- `details.reason`
- `details.revoked_count`

Relevant event types include:

| Area | Event types |
| --- | --- |
| Attestations | `membership_attestation_issued`, `membership_attestation_revoked`, `membership_attestation_verified` |
| Treaties | `recognition_treaty_issued`, `recognition_treaty_revoked`, `recognition_treaty_verified`, `treaty_attestation_verified` |
| Revocation feeds | `sovereign_revocation_feed_imported`, `sovereign_revocation_feed_rejected` |
| Certificates and operators | `certificate_revoked`, `operator_key_revoked`, `admin_auth_failed`, `admin_auth_throttled` |
| Agreements | `agreement_accepted`, `agreement_verified`, `agreement_untrusted` |
| Database | `database_migrated` |
| Evidence store (with `EVIDENCE_STORE=on`) | `evidence_recorded`, `evidence_rejected`, `evidence_anchored`, `evidence_anchor_refused`, `evidence_archived`, `evidence_retention_applied`, `audit_pack_built`, `na_key_succession_recorded` |
| Out-of-band records, remediation, grants, edge nodes (each off by default) | `observation_recorded`, `break_glass_recorded`, `change_judged`, `remediation_enabled`, `remediation_recorded`, `review_decided`, `grant_issued`, `grant_revoked`, `grant_use_recorded`, `edge_node_enrolled`, `edge_node_revoked` |

The list is not complete: filter with `--event-type` on the names your NA
writes.

## Redaction

The export command defensively redacts fields whose names indicate secrets or
full request payloads, including:

- admin signatures
- invite tokens
- private keys
- request bodies
- nonce and token values

The export is still operationally sensitive because it exposes trust decisions,
certificate IDs, node IDs, operator key IDs, and timing. Store exports with the
same access controls used for incident records.

## Retention

For a managed sovereign, keep:

- at least 30 days of exported audit events online;
- at least one restore-tested database backup covering the same window;
- incident exports attached to incident tickets or support cases.
