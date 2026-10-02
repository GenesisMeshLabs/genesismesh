# Security Review for v1

**Date:** 2026-10-02 · **Release:** v0.62.0 · **Scope:** the v1 deployment
profile below, its Network Authority, CLI, signed artifacts and official SDKs.

This review was carried out by the maintainers against the code, with
automated checks added wherever a claim could be enforced. **It is not an
independent audit or penetration test.** One is recommended before
production use beyond a pilot.

## The v1 deployment profile

| Element | Profile |
| --- | --- |
| Network Authority | The Python NA under gunicorn, behind exactly the number of TLS-terminating reverse proxies set in `NA_PROXY_HOPS` (default 1) |
| Storage | One instance on SQLite, or one or more instances on PostgreSQL (`NA_HA_MODE=on`) |
| NA signing key | Azure Key Vault (managed identity) or a platform-injected environment seed; a key file only for a single SQLite instance |
| Operator keys | Generated and held by the operator; privileged keys for trust changes, standard keys for routine calls |
| Governed workloads | `BOUNDARY_POLICY_ENFORCEMENT=required`, `EVIDENCE_STORE=on` |
| Clients | The TypeScript, Go and .NET SDKs, or raw HTTP with the documented admin signature |
| Out of profile | Mesh routing and Noise transport (`genesis-mesh-node`), the Rust gateway, beta and internal surfaces |

## Findings

| ID | Area | Severity | Finding | Status |
| --- | --- | --- | --- | --- |
| SR-01 | Packaging | High | The wheels on PyPI never contained the migration SQL files. A Network Authority installed with `pip` started without its tables and failed on every admin request (it failed closed: no data was exposed). Source and container deployments were not affected. | **Fixed** in v0.62.0: `package-data` includes the migrations; `test_packaging.py` fails on any unshipped data file; CI runs a full NA workload from the built wheel; the published-artifact workflow runs the cross-language scenario from the registries. |
| SR-02 | Authorization | High | A standard-tier operator key could accept an agreement (granting capabilities that boundary decisions then authorize) and make the NA sign a data license policy (granting a licensee access to data). Both are trust changes, which the tier model reserves for privileged keys. | **Fixed**: both routes require the privileged tier (`test_trust_change_tiers.py`). |
| SR-03 | Availability | Medium | No request body limit. The public verify routes are unauthenticated, so an arbitrarily large JSON body could exhaust a worker's memory. | **Fixed**: bodies over `NA_MAX_REQUEST_BYTES` (default 2 MiB) get `413 request_entity_too_large` before parsing. |
| SR-04 | Rate limiting | Medium | The NA always trusted one `X-Forwarded-For` hop. Exposed without a proxy, a client could choose the address its rate limits apply to, admin limits included. | **Fixed**: `NA_PROXY_HOPS` sets the trusted hops; `0` ignores the headers. The profile requires it to match the deployment. |
| SR-05 | Recovery | Medium | A release started on a database migrated by a newer release ran on the unknown schema; only `/readyz` reported the mismatch. A rollback could therefore run old code on new data. | **Fixed**: start-up refuses with `NewerSchemaError`; rollback is a restore (`docs/operations/upgrade.md`). |
| SR-06 | Key handling | High | There is no procedure to rotate the NA signing key while keeping the sovereign's identity (RFC-001 open question). A compromised NA key means a new identity, with counterparts re-issuing treaties. | **Accepted residual risk** for v1. Mitigations: Key Vault custody with managed identity; HA mode refuses key files; operator keys, not the NA key, authenticate admin calls; documented in {doc}`../operators/exit-and-fork` and the incident response runbook. |
| SR-07 | Revocation freshness | Medium | Imported sovereign revocation feeds have no enforced maximum age. A sovereign keeps accepting a partner's attestation until it imports the feed that revokes it, so the stale window is the import interval. Within one NA, revocation is immediate. | **Accepted residual risk**: replay of older feeds is refused (`stale_sequence`); RFC-007 continuity checks set the import cadence; decisions can require freshness proofs. Tracked as an RFC-004 open question. |
| SR-08 | Trust bundles | Low | Trust bundles are unsigned, so they prove nothing about who assembled them (RFC-003). | **Accepted**: bundles are review hints only and never imported into trust state; keys come from the subject's endpoint or out of band. |
| SR-09 | Revocation import | Low | The feed import route accepts issuer keys supplied by the operator, falling back to the treaty's subject keys. | **Accepted**: an operator trust decision behind a privileged key; RFC-004 now says so explicitly. |
| SR-10 | Availability | Low | `/heartbeat` and `/renew` are not rate limited; each verifies a node signature and certificate. | **Accepted** for the profile (mesh nodes are out of it); put the NA behind a proxy or WAF with connection limits. |
| SR-11 | Dependencies | Info | The gateway depends on `rustls-pemfile`, flagged unmaintained (RUSTSEC-2025-0134); no vulnerability. | **Accepted**: the gateway is beta and outside the v1 contract. |

## Areas reviewed

### Threat model

`SECURITY.md` was checked against the profile. Its in-scope defenses hold and
are tested. It was updated where the code had moved on: proxy trust is now
configurable (SR-04); `/join` is rate limited; and the out-of-scope entry for
NA key compromise no longer suggests a rotation procedure that does not
exist (SR-06).

### Dependency reports

| Package | Tool | Result |
| --- | --- | --- |
| genesis-mesh | `pip-audit` (runtime and dev requirements) | No known vulnerabilities |
| genesis-mesh-sdk (npm) | `npm audit` | 0 vulnerabilities; no runtime dependencies |
| sdk-go | `govulncheck` | No vulnerabilities |
| genesismesh-sdk-dotnet | `dotnet list package --vulnerable --include-transitive` | No vulnerable packages |
| sdk-rust | `cargo audit` | No advisories |
| gateway | `cargo audit` | One informational advisory (SR-11) |

### Key handling

- NA keys come from one `Signer` with providers `file`, `env` and
  `azure-keyvault`; Key Vault seeds stay in memory. HA mode refuses `file`.
- Key files are written owner-only (`0o600`) where the filesystem allows it.
- Operator keys authenticate admin calls; the NA key is never used for that.
  Operator keys have tiers, and a key revoked at runtime is refused before its
  signature is checked and before its nonce is consumed.
- Errors and logs go through `redacted_exception_text`; private keys and seeds
  are never logged or returned. `test_operator_independence.py` keeps key
  literals and built-in authorities out of runtime code.

### Revocation freshness

Within a Network Authority, revoking an attestation, treaty or operator key
takes effect on the next request (the upgrade rehearsal checks that a revoked
attestation is denied). Across sovereigns it depends on feed import (SR-07).
Node certificate revocation goes through the signed, monotonic CRL.

### Replay protection

- Admin requests: an Ed25519 signature over `{body, key_id, timestamp,
  nonce}`, a ±300 second timestamp window, and an atomic nonce claim in the
  database, so a nonce cannot be used twice on any instance.
- Boundary decisions expire (`decision_valid_until`); invocation tokens keep
  use records; revocation feeds must increase their sequence; evidence
  submission is idempotent (an identical resubmission is a `duplicate`).

### Authorization failures

- Every `/admin/*` route refuses an unauthenticated request
  (`test_admin_route_auth.py` walks the routes the NA registers, so a new
  route is covered automatically).
- Authentication failures are `401`; an authenticated key without the
  required tier gets `403 insufficient_operator_tier` and an audit event.
- Trust changes require the privileged tier (SR-02 closed the two gaps).

### Recovery

- Backup and restore: online SQLite backups and `pg_dump`; restored databases
  are verified by `na verify-db`. The upgrade rehearsal restores a backup and
  re-verifies every record on each CI run.
- Failover: two-instance failover under load is tested in CI (v0.60).
- Rollback: forward-only migrations, refusal of newer schemas, restore
  procedure (SR-05).
- NA key compromise: new identity (SR-06).

## RFC-001 to RFC-004

The security considerations of the four normative RFCs were checked against
the implementation; see {doc}`rfc-decisions`. RFC-004 now states that feed
issuer keys may be supplied by the importing operator (SR-09); its freshness
question stays open (SR-07). No finding blocks acceptance; the
acceptance itself is the maintainer's decision.
