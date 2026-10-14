# Pre-issued grants

*Unreleased.*

From Genesis Mesh 1.6.0 the Network Authority (NA) can authorise a change in
advance. A **grant** is a bounded authorisation the NA signs for one holder:
one bearer key, a few capabilities, a validity of at most 24 hours, a budget
of uses and a closed envelope of request parameters, checked when it is
issued against every policy that applies. The holder acts within it while
the NA cannot be reached and uploads what it did when it reconnects. Where
break-glass records a change made without a decision and has it judged
afterwards, a grant authorises the change before it is made.

This page covers the SDK side: issuing grants, holding one, verifying the
records. The operator's side, the issuance rules and the limits of offline
trust are in {doc}`../../operations/grants`, with a worked example in
{doc}`../../examples/pre-issued-grants`.
The routes are beta; the records' signed forms are stable from 1.6.0.

The NA must run with `EVIDENCE_GRANTS=on` (which needs
`EVIDENCE_OUT_OF_BAND=on`); until then every grant route answers
`404 grants_disabled`. Update every verifier that reads your exports, packs
and revocation feed to 1.6 before turning it on: a 1.5 verifier refuses the
new entry kinds and the feed's `revoked_grant_ids`.

## Issuing and revoking grants

`gm.grants` wraps the admin routes:

```ts
const issued = await gm.grants.issueGrant({
  bearer_key_id: 'site-7-device',               // a registered executor key
  capabilities: ['secret.manage'],
  attestation_id: vendorAttestation.attestation_id, // or agreement: AgreementRecord
  valid_until: new Date(Date.now() + 4 * 3600_000),
  max_uses: 3,
  max_uses_per_time_token: 2,
  parameter_envelope: {
    lifetime_days: { number_range: { number_type: 'integer', minimum: 1, maximum: 60 } },
  },
});
// issued.grant (signed), issued.time_token (the first one), issued.entry
```

A refusal is a `422` naming the first problem (`grant_gate_may_deny`,
`grant_undecidable_attributes`, ...; every problem in `error.details.problems`).
A `409 grant_issuance_conflict` means what the grant rests on changed while
the NA checked it: retry (`isRetryableConflict` says so). Hand the device the
signed grant and its first time token.

Reading (read tier):

- `listGrants({ status, bearer_key_id, limit, before })`: newest first by
  `issued_at`, then `grant_id`; `before` is the previous page's
  `next_before`, the ID of its last grant. `status: 'active'` includes grants
  whose summary says `scheduled` or `exhausted`;
- `getGrant(id)`: the summary, `remaining_uses`, `chain_length` (the
  positions of its use chain, admitted and quarantined), the signed grant,
  its policy versions and its revocation;
- `listGrantUses(id, { limit, before })` (beta): its use chain, newest first,
  each use `admitted` or `quarantined` (a refused use that continued the
  chain, with its `rejection_code`); `before` is a `use_sequence`;
- `evidenceStore.search({ grant_id })`: a grant's uses and its revocation;
  `evidenceStore.storedResourceHead(id)` names a resource's head, which may
  be a grant use (`entry_kind`, `record_id`).

`revokeGrant(id, reason)` revokes one (privileged): `reason` is stored as the
revocation's `detail`, and the revocation's `reason` is `operator`. The NA
also revokes a grant itself: `attestation_revoked`, `policy_deactivated`,
`policy_activated`, `bearer_key_retired`, and `agreement_untrusted` when its
agreement basis is no longer signed by parties the NA trusts.

## Holding a grant

`GrantHolder` acts within one grant for its bearer key. It needs a record
outbox: each use is kept there until the NA admits it.

```ts
import { FileRecordOutbox, GenesisMeshClient, GrantHolder, seedSigner } from 'genesis-mesh-sdk';

const gm = new GenesisMeshClient({ baseUrl, signingKeyBase64, keyId,
  recordOutbox: new FileRecordOutbox('/var/lib/device/gm-records') });
const holder = new GrantHolder({
  clients: gm,
  signer: seedSigner(deviceSeed, 'site-7-device'), // the bearer key
  naPublicKeys: history,                            // a key list, or the NA's key history
  grant: issued.grant, timeToken: issued.time_token,
  resourcePrefix: 'kv:site-7/',                    // the bearer key's registered resource_prefix, if any
  persist: state => saveJson('/var/lib/device/grant.json', state),
});

const result = await holder.act({
  capability: 'secret.manage',
  request_parameters: { lifetime_days: 30 },
  resource_id: 'kv:site-7/api-key', resource_action: 'rotate',
  fallback: { justification: 'the site is cut off and the key must rotate', verify },
}, async authority => {
  const version = await rotateSecret();  // authority.path: 'grant', 'decision' or 'break_glass'
  return { execution_parameters: { version_id: version } };
});
```

The holder verifies the grant and its time token (signed by the NA's key
valid at their `issued_at`) and that the signer is the bearer key, then
checks each request offline, in this order:

| Check | Refused as |
|---|---|
| No secret material in the request parameters | `grant_use_secret_material` |
| The resource is within the bearer key's `resourcePrefix` (a use without a resource is not) | `grant_use_out_of_scope` |
| The capability is one of the grant's | `grant_capability_mismatch` |
| The request parameters are inside the closed envelope | `grant_envelope_mismatch` |
| The budget, counting the holder's own uses | `grant_budget_exhausted` (fallback) |
| The validity | `grant_expired` past its end (fallback); `grant_use_outside_validity` before its start |
| The revocation feed it holds, and what the NA last answered | `grant_revoked` (fallback), or the NA's code |
| At most `max_uses_per_time_token` uses after the use its time token names | `grant_time_token_exhausted` (fallback), after asking the NA for a fresh token when it answers |

A request outside the grant throws `GrantRefusedError` and runs nothing. A
request within it runs `action` with `{ path: 'grant' }`; the use is signed
by the bearer key (`GrantExecutionEvidence`), chained to the previous use and
citing the latest time token, kept in the record outbox and submitted at once
when the NA is reachable. A use is never dated before its time token or the
previous use: the token proves the time is no earlier, so a clock behind the
NA's dates the use at the token's time. An action that throws is recorded as
a `failure` use and the error rethrown; metadata the secret guard refuses is
left out of the use and named in `dropped`. Calls to one holder run one at a
time, so two uses never take one place in the chain.

Every use the holder signs takes the next place in its chain. A use the NA
refuses for good is kept by the NA as a quarantine entry and becomes the
chain's head, so it stays a dead letter in the record outbox and the uses
after it are still uploaded, each judged on its own (the budget counts
admitted uses only). The holder never signs a use the NA would refuse without
storing it: secret material is checked first. A chain gap and a use dated
ahead of the NA's clock (`grant_use_in_future`) are retried.

Persist `holder.state` (the `persist` option is called after every change)
together with the record outbox, and resume with `new GrantHolder({ ...,
state })`: the state holds the grant, the latest time token, the head of the
use chain and the revocation feed.

### Reconnecting

```ts
const synced = await holder.sync();
```

`sync` reads the revocation feed, asks for a fresh time token naming the head
of the holder's chain (a `TimeTokenRequest` its bearer key signs), and flushes
the record outbox: the grant's uses go in the order they were made, after
break-glass records and before observations. The NA gives each use the next
position of its resource's chain as it admits it. Steps the NA does not
answer are skipped (`reachable: false`). When the NA answers that the grant
has ended (`grant_expired`, `grant_revoked`, `grant_budget_exhausted`,
`grant_bearer_key_retired`), the holder keeps that answer and stops using the
grant. `refreshRevocationFeed()` and `refreshTimeToken()` run one step alone;
`updateRevocationFeed(feed)` takes a feed read elsewhere. A feed must be
signed by the NA and issued by the grant's issuer, and an older feed never
replaces a newer one, so a holder refuses a revoked grant once the feed it
holds lists it.

### Expiry is not a block

When the grant has ended, its budget or time token is spent, or it is
revoked, `act` does not block the change. With `fallback` it goes through
`governedAction` with break-glass, naming the capability and the grant's
basis attestation (or `fallback.attestation_id`):

- an NA that answers decides: an ALLOW runs the action with
  `{ path: 'decision' }` and records execution evidence, and a DENY runs
  nothing (`result.authorized` is false). A DENY is never broken through;
- an NA that cannot be reached (a network error, a timeout, `5xx`, `429`)
  runs the action with `{ path: 'break_glass' }`, and its `BreakGlassRecord`
  waits in the record outbox to be judged after the fact.

The result is `{ path, unusable, result }`, `unusable` naming why the grant
could not be used. Without `fallback` such a request throws
`GrantUnusableError`. Break-glass needs an attestation-based evaluation and a
resource, as `governedAction` does.

## The records

| Record | Signed by | Verify with |
|---|---|---|
| `CapabilityGrant` | the NA | `verifyCapabilityGrant(grant, naKeys)` |
| `TimeToken` | the NA | `verifyTimeToken(token, naKeys)` |
| `TimeTokenRequest` (beta) | the bearer key | `verifyTimeTokenRequest(request, bearerPublicKey)` |
| `GrantExecutionEvidence` | the bearer key | `verifyGrantUse(use, bearerPublicKey)` |
| `GrantRevocationRecord` | the NA | `verifyGrantRevocation(record, naKeys)` |

Each signs every field but `signature`, an absent optional field left out
(also a time token's `use_head_digest` nested in a use). Given the NA's key
history, an NA-signed record read alone is placed at its `issued_at` (a
revocation at its `revoked_at`). `grantDigest` and `grantUseDigest` give the
digests a use names its grant and its previous use by. `signGrantUse` and
`signTimeTokenRequest` build and sign the holder's records, refused first as
the NA would refuse them (`grant_use_malformed`, `grant_use_secret_material`,
`time_token_request_malformed`, or `StrictJsonError`); `useProblem` runs the
NA's use rules in their order with what the caller holds (the last admitted
use, how many uses were admitted, the use the token names), and
`continuesChain` says whether a use continues a chain's head. A `use_id` is a
UUID in its canonical lowercase form.

Numbers in an envelope follow one rule in every implementation:
`envelopeParameter` reads a parameter as the NA does (an integral number is an
integer, `5.0` is `5`; integers fit 64 bits, as a `bigint` beyond 2^53;
comparisons are exact; booleans are never numbers; set membership is
type-strict, `true` is not `1` and `1` is `1.0`), and `envelopeProblem` says
why request parameters are outside an envelope.

## Verification

`verifyEvidenceEvents` verifies the three new entry kinds and counts them
(`grants`, `grant_executions`, `grant_revocations`):

- `grant` and `grant_revocation` entries are signed by the NA, a
  `grant_execution` entry by its grant's bearer key, a registered executor key
  of its executor sovereign; a grant whose signature fails is not held;
- the uses of a grant form a chain (`grant_use_chain_break`), whose head may
  be a quarantined use (a `quarantine` entry of `record_kind`
  `grant_execution`, signed by the bearer key) that continued it;
- in a run from the store's start, a use and a revocation name a grant the run
  holds (`grant_missing`; in an audit pack `cited_record_missing`); a use is
  signed by the grant's bearer key (`grant_bearer_mismatch`), within that
  key's `resource_prefix` (`grant_use_out_of_scope`), and names the grant's
  digest (`grant_mismatch`); a grant is revoked once
  (`duplicate_grant_revocation`); a `use_id` is not the ID of execution
  evidence or a break-glass record (`duplicate_record`);
- then each use is checked by the NA's use rules, with the admission codes
  (`grant_envelope_mismatch`, `grant_time_token_invalid`,
  `grant_use_uploaded_late`, `grant_revoked`, ...): the budget counts admitted
  uses when the run holds the chain from its first use, and the order and time
  rules compare a use with the last admitted one;
- a use takes the next position of its resource's chain, which the NA assigns
  in the envelope (`resource_chain_break`); a use without a resource has none
  (`envelope_mismatch`), and the next execution evidence links to the use.

A judgement may be `governed_by: grant` (a change matched to a grant use),
and a quarantine entry may keep a refused use (`record_kind:
grant_execution`). `verifyRevocationFeedSignature` verifies a feed with or
without `revoked_grant_ids`. `verifyAuditPack` checks a grant's policy
binding and basis attestation as a decision's (`cited_policy_missing`,
`cited_attestation_missing`, `cited_attestation_mismatch`), and an agreement
basis from the pack's `trust/agreements.jsonl` (a file a pack holds only when
it holds a grant under an agreement): held (`cited_agreement_missing`), the
one the grant's `basis_digest` names, between the grant's parties
(`cited_agreement_mismatch`), and signed by both with keys the pack vouches
for (`agreement_invalid_signature`). A pack cites the whole chain of a grant
its range uses, quarantined uses too. `renderReport` lists uses as changes
governed by the grant, with *Grants* and *Grant revocations* sections in a
pack that holds them.

The conformance suite `grants` runs every vector but the NA's issuance check
(`issuance`), which an SDK does not run.
