# Evidence store and policy clients

`gm.evidenceStore` wraps the execution evidence store. `gm.evidence` remains the
separate trust-evidence client. The NA must run with `EVIDENCE_STORE=on` (off
by default); until then the store routes answer `404 evidence_store_disabled`.

| Operation | SDK method |
|---|---|
| Submit executor-signed evidence | `submit(evidence)` |
| Search one page or all matching entries | `search(params)`, `iterate(params)` |
| Resource and vendor histories (up to 10,000 records; `truncated` beyond that, read the export) | `resourceHistory(id)`, `vendorHistory(id)` |
| Current resource chain head (one lookup on the NA since 0.63.1) and recorded states | `resourceHead(id)`, `resourceStates()` |
| Store health and verification | `status()`, `verify()` |
| Raw NDJSON, parsed page or paged export | `exportText(params)`, `export(params)`, `exportAll(sinceSequence, pageSize)` |
| Executor keys | `registerExecutorKey(params)`, `listExecutorKeys()`, `retireExecutorKey(id)` |
| Retention (1.5.0: `throughSequence`, held back where no archive covers) | `applyRetention(olderThanDays, { throughSequence })`, `latestCheckpoint()` |
| Store anchors (beta routes) | `anchors(params)`, `allAnchors()`, `anchor()` |
| Audit packs and archives (1.5.0, beta routes) | `auditPack(params)`, `archives()`, `recordArchive(manifest, location)` |

All evidence-store reads use signed admin GETs. Submission uses the evidence's
executor signature and does not send operator headers. The executor sovereign
and key ID must match a registered key. A retired key verifies historical
records but cannot submit new records. Submission returns `status: 'recorded'`
or `status: 'duplicate'`.

`ExecutionRecorder.record` supports both chains: `prior_record` links records
under one decision, and `prior_resource` links changes to one resource across
decisions. Resource ID and action must be supplied together. Resource heads from
retention checkpoints can be used as predecessors.

`status()` reports the store's size, its latest retention checkpoint and
anchor (`latest_anchor`, `unanchored_entries`, `anchoring_blocked`), records
not judged yet, and with out-of-band records on the registry's health
(`policy_history_started`, `registry_healthy`, `registry_problems`). From
1.5.0 every store read accepts a read-tier key, so an auditor's key can ask
for anchors and audit packs; see
[Key succession, audit packs and offline verification](audit-packs.md).

Search uses `after_sequence` and returns `next_after_sequence`. Export uses
`since_sequence`; `exportAll` follows the last returned store sequence. Page sizes
are 1 through 1000. Iterators reject non-advancing cursors instead of looping.
Retain export ordering when verifying a complete store chain.

## Attestations and policies

`gm.attestation` exposes `issue`, `revoke`, `get`, `list`, `verify`, `savePolicy`,
`getPolicy` and `revocationFeed`. Attestation verification needs either an explicit
recognition policy or an active policy saved on the NA. Allowed roles and accepted
statuses belong to each `recognized_issuers` entry.

`gm.policy` exposes `validate`, `publish`, `list`, `active`, `history`, `activate`,
`deactivate` and `verify`. Publishing creates an inactive version. Activating an
older version is rollback. Observe-mode gate failures are reported without denying
the operation. Required policy enforcement does not imply that a matching policy
exists; use explicit expected policies in governed actions to detect an empty or
unexpected policy set.

`gm.boundary.evaluate` takes exactly one basis, `agreement` or `attestation_id`,
and returns `{ decision, justification_proof }`. A policy denial is a signed
response, not an HTTP exception. The legacy `boundary.decide` route (beta) is
not the policy-aware route; an NA that requires policy enforcement refuses it
with `409 boundary_policy_required`.

## Transport and errors

Supply `signer: { keyId, sign(bytes) }` for synchronous or asynchronous Ed25519
signing. The signature must be 64 bytes. The seed-based signer is still available;
an explicit signer takes precedence over a configured seed. Signer failures
propagate without fallback or key caching.

Retries are disabled by default. Configure `retry: { attempts: 2, baseDelayMs: 200 }`
for bounded exponential backoff on network failures and HTTP 429, 502, 503 or 504.
Eligible: every GET; the submission of execution evidence, observations,
break-glass and remediation records and grant uses; time token requests; the
admin POSTs the NA answers the same way when replayed (`judgeObservation`,
`judgeBreakGlass`, `anchor()` and `recordArchive()`); and the verification
routes of boundary decisions, attestations and policies. In 1.7.0 the
agreement, trust-evidence, consensus, disclosure (`prove` and `verify`) and
data-usage verification routes are not retried; from 1.8.0 they
are. Other admin POSTs, including evaluation, issuance, policy publication and
audit packs, are not retried. Admin retry attempts receive fresh signatures
and nonces.

HTTP 403, 409 and 503 map to `ForbiddenError`, `ConflictError` and
`ServiceUnavailableError`. Errors expose `code`, `status`, `details` and
`requestId` for correlation with NA responses.
