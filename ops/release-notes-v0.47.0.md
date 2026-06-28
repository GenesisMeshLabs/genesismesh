# Release Notes — v0.47.0 Data Usage Attestation Layer

## What is new

Signed pre- and post-execution attestation for data access.  Implements the
Data Plane from arXiv:2606.12320 (Five-Plane Reference Architecture).

### Models (`genesis_mesh/models/data_usage.py`)

- `DataSourceDescriptor` — data source identity and classification tags
- `DataLicensePolicy` — operator-issued allowlist, access types, prohibited
  tags, volume cap; signed by licensor
- `DataAccessIntent` — agent-signed pre-execution declaration; expires in TTL
- `DataAccessRecord` — agent-signed post-execution record linked to intent
- `DataUsageViolation` — structured violation record (7 typed reasons)

### Trust logic (`genesis_mesh/trust/data_usage.py`)

- `verify_data_access_intent()` — pre-execution compliance; returns
  `(ok, first_reason, all_violations)`
- `verify_data_access_record()` — post-execution compliance using same logic
  over `accessed_sources` / `access_types_used` / `actual_volume_bytes`
- `create_data_access_intent()` — signed intent builder
- `DataUsageGate` — `BoundaryEngine` gate; calls `verify_data_access_intent()`

### CLI (`genesis_mesh/cli/data_usage_ops.py`)

- `genesis-mesh trust data policy` — create signed `DataLicensePolicy`
- `genesis-mesh trust data intent` — create signed `DataAccessIntent`
- `genesis-mesh trust data record` — create signed `DataAccessRecord`
- `genesis-mesh trust data verify` — verify intent against policy; exit 1 on
  any violation

### Violation reasons

| Reason | Trigger |
|--------|---------|
| `source_not_licensed` | Source ID not in `allowed_source_ids` |
| `access_type_not_permitted` | Access type not in `allowed_access_types` |
| `prohibited_classification` | Source carries a prohibited tag |
| `volume_cap_exceeded` | Volume > `max_volume_bytes_per_session` |
| `intent_expired` | `at_time > intent.expires_at` |
| `policy_expired` | `at_time` outside policy validity window |
| `intent_exceeds_license` | Missing or invalid signature |

## Scope constraint

Payment, royalty calculation, and external settlement are **explicitly out of
scope**.  `DataAccessRecord` is an attestation artefact; downstream systems
decide what, if anything, to charge.

## Tests

20 new tests in `genesis_mesh/tests/test_data_usage_attestation.py`.
Full suite: 1024 passed, 1 skipped.
