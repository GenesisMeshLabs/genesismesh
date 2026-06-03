# Audit Export

Genesis Mesh stores Network Authority audit events in the NA SQLite database.
For managed sovereign operation, export those events regularly enough that a
customer or operator can reconstruct trust decisions after an incident.

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

- `membership_attestation_issued`
- `membership_attestation_revoked`
- `membership_attestation_verified`
- `recognition_treaty_issued`
- `recognition_treaty_revoked`
- `recognition_treaty_verified`
- `treaty_attestation_verified`
- `sovereign_revocation_feed_imported`
- `sovereign_revocation_feed_rejected`

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

For a managed sovereign pilot, keep:

- at least 30 days of exported audit events online;
- at least one restore-tested database backup covering the same window;
- incident exports attached to incident tickets or support cases.
