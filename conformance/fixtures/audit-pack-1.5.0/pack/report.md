# Audit pack 00000000-0000-4000-8000-000000000802

- Sovereign: sovereign-c
- Range: store entries 6 to 11, ending at anchor 3, starting after anchor 1
- Created: 2026-01-16T00:00:00Z for auditor-1

Verify it with `genesis-mesh audit verify <dir> --anchor <root public key> --known-anchors <anchors>`, from the root key and the anchors you hold. The remediation states and notices below are the Network Authority's operational records at pack time (states.json), not signed records.

## Checks

Verified by the Network Authority when it wrote the pack, against its own anchors: **yes**.

None.

## Totals

| Records | Count |
|---|---|
| archives | 1 |
| checked_entries | 6 |
| decisions | 1 |
| executions | 1 |
| judgements | 1 |
| key_successions | 1 |
| observations | 1 |

## Changes

| Entry | Kind | Resource | Action | Changed at | Governed by | State | Actor |
|---|---|---|---|---|---|---|---|
| 8 | execution | kv:vault/api-key | rotate | 2026-01-12T00:01:00Z | prior_decision | recorded | sovereign-b |
| 9 | observation | kv:vault/api-key | rotate | 2026-01-12T00:01:00Z | prior_decision | matched | principal-7f3a |

## Denials

None.

## Remediations

None.

## Reviews and deciders

None.

## Notices

None.

## Break-glass uses

None.

## Quarantined records

None.

## Key successions and archives

| Entry | Kind | ID | At |
|---|---|---|---|
| 6 | key_succession | 00000000-0000-4000-8000-000000000401 | 2026-01-11T00:00:00Z |
| 11 | archive | 00000000-0000-4000-8000-000000000701 | 2026-01-14T00:00:00Z |
