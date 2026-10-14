# Pre-Issued Grants

*Unreleased.*

A grant is an authorisation the Network Authority (NA) signs in advance, so a
device or controller can make a change while it cannot reach the NA. Where
break-glass ({doc}`emergency-changes`) records a change made without a
decision and judges it afterwards, a grant authorises the change beforehand:
the NA checks, when it issues the grant, that every policy that applies
allows every request the grant permits. This page covers when to use grants,
how they are issued, used, uploaded and revoked, and what offline trust
cannot promise. The worked example is {doc}`../examples/pre-issued-grants`;
the routes are in {doc}`../api/trust-http` (*Pre-issued grants*).

Grants are off until `EVIDENCE_GRANTS=on` (it needs `EVIDENCE_OUT_OF_BAND=on`).
Turn it on once every verifier that reads your exports, packs and revocation
feed runs 1.6: a 1.5 verifier refuses the new entry kinds and the feed's
`revoked_grant_ids`. Turning it off again is covered in
[Turning grants off](#turning-grants-off).

## Grants or break-glass

| Situation | Use | Why |
| --- | --- | --- |
| A known, bounded kind of change a device must be able to make while it is disconnected (rotate its own credential, scale within limits) | a **grant** | the change is authorised before it is made, within an envelope the policies were checked against; it is governed (`governed_by: grant`), not judged after the fact |
| An urgent change nobody planned for, while the NA does not answer | **break-glass** | nothing authorised it; it is recorded with a justification and judged afterwards |
| A grant has ended, is spent or revoked, and the NA does not answer | **break-glass** | the SDK falls back to it: an urgent change is recorded and judged, never blocked |
| The NA answers | a **decision** | ask for one; a grant is for when the NA cannot be reached |

A grant never overrides a DENY: an envelope a policy could deny is not
granted. Keep grants for changes you would allow anyway, made where the
network is unreliable.

## Issuing a grant

`POST /admin/grants` (privileged) names:

- the **bearer**: one registered executor key (`bearer_key_id`). Only its
  holder can use the grant; one key per grant means its budget cannot be
  spent on several devices. A key with a resource prefix may use the grant
  only for resources inside it;
- the **capabilities** (exact IDs) and the **basis**: an attestation this NA
  issued (`attestation_id`) or an agreement it trusts (`agreement`);
- the **validity** (`valid_from`, by default now, and `valid_until`, RFC 3339):
  at most 24 hours, and at most `NA_GRANT_MAX_VALIDITY_SECONDS`;
- the **budget** (`max_uses`, required, at most `NA_GRANT_MAX_USES`) and the
  uses allowed per time token (`max_uses_per_time_token`, at most
  `NA_GRANT_MAX_USES_PER_TIME_TOKEN`);
- the **parameter envelope**: every request parameter a use may carry, each
  with `one_of` (a finite set of scalars), `subset_of` (a list of strings
  drawn from a set) or `number_range` (`integer` or `number`, with inclusive
  or exclusive bounds), and whether it is `required`. The envelope is closed:
  a use with any other parameter is refused. Every use carries these names
  and values, so an envelope that looks like secret material (a parameter
  named like a secret, a PEM block, a key or token) is refused
  (`invalid_grant_envelope`).

The NA then checks the basis (its status, a validity that covers the whole
grant, each capability, freshness) and every active policy, and signs the
grant, or refuses it naming the first problem and listing them all
(`error.details.problems`). Inside the write that stores the grant it checks
again that nothing the grant rests on changed since (the active policy
versions, the bearer key, the attestation, the agreement's trust). If
something did, it checks the grant once more; if something changes again,
it refuses with `409 grant_issuance_conflict`, and the operator retries.

### How policies are decided over an envelope

The NA decides each gate of each policy that applies for every request the
envelope permits, at every time of the grant's validity:

| Gate type | Decided when |
| --- | --- |
| `max_value.v1`, `min_value.v1` | the parameter is required and every value it may take is a number on the right side of the bound. Booleans are never numbers; exclusive bounds count; numbers are compared exactly (an integer range up to 2^53 + 1 exceeds a bound of 2^53) |
| `allowlist.v1`, `denylist.v1` | every value (a set, or the integers of a range) is, or is not, listed, compared type-strictly: `true` is not `1`, `"1"` is not `1`, `1` is `1.0` |
| `scope_membership.v1` | the parameter's set (`subset_of`) lies within the allowed scope |
| `required_parameter.v1` | the parameter is required and never null |
| `boolean_required.v1` | the parameter is pinned (`one_of: [true]`) |
| `time_window.v1` | the grant's whole validity lies inside the window |
| `attestation_claim.v1` | every value is in the claim of the grant's attestation, and none is null (the gate fails on a null value) |

A gate on a fact the grant fixes (the capability, the parties, the basis, the
attestation's facts, and `parent_kind`, which is `grant`) is evaluated on
that one value. A selector's `parameter_equals` narrows the envelope to the
requests it selects, and a policy selecting `parent_kinds` applies to a grant
when it names `grant` or the kind of the grant's basis (`attestation`, or
`agreement` and `direct`). A policy can forbid grants with a `denylist.v1`
gate on `parent_kind` listing `grant`.

### Why the NA refuses

Problems are reported in this order, for each capability and each policy in
turn:

| Reason | Meaning |
| --- | --- |
| `grant_basis_invalid` | the attestation is missing, not signed by this NA, revoked, or not the requester's |
| `grant_outlives_basis` | the grant's validity is not within the attestation's or agreement's |
| `grant_capability_out_of_scope` | the basis does not grant a capability |
| `grant_basis_not_fresh` | the agreement's freshness commitment is not met |
| `grant_policy_resolution_failed` | the active policy set cannot be trusted (an unsigned or invalid policy, two active versions of one policy, a stored policy that fails its digest): no grant is issued |
| `grant_review_required` | a policy that applies requires every change to be reviewed (or is an emergency policy); a grant cannot pre-authorise such a change |
| `grant_policy_scheduled` | a policy that would apply starts inside the grant's validity |
| `grant_outlives_policy` | a policy that applies ends before the grant |
| `grant_undecidable_attributes` | a gate or selector reads `attributes.*`: the facts and identifiers an external system supplies per request, which a grant cannot fix |
| `grant_undecidable_freshness` | a gate or selector reads `context_freshness_seq`, which changes over the grant's life |
| `grant_undecidable_time` | a gate other than `time_window.v1`, or a selector, reads `requested_at` |
| `grant_undecidable_gate_type` | a gate type other than the nine above (an operator's own), whose behaviour over a range is unknown |
| `grant_gate_may_deny` | an enforce-mode gate may deny a request inside the envelope |

Observe-mode gates never refuse a grant: how each was decided (`pass`,
`may_fail`, `undecidable`) is recorded in the grant's `policy_binding`, with
the policy versions it was checked against. Other refusals:

- **The request** (`400`): `invalid_grant_request`, `invalid_grant_validity`,
  `invalid_grant_envelope`, `grant_limit_exceeded`, `ambiguous_basis`,
  `unexpected_field`, `invalid_agreement`.
- **The bearer key** (`422`): `grant_bearer_key_unknown`,
  `grant_bearer_key_not_executor`, `grant_bearer_key_retired`.
- **A change during issuance** (`409`): `grant_issuance_conflict`.

The issuance check runs only at the NA: SDKs neither run it nor port the
policy engine, and the `issuance` vectors of the `grants` conformance suite
are for the NA alone.

## Using a grant

The holder keeps the grant and the time token the NA returned with it.

1. **Before each change** it checks, offline: the capability, the envelope,
   the budget (the uses it made), the validity, the uses its time token
   still allows, its key's resource prefix, and the revocation feed it last
   read.
2. **It records the use**: a `GrantExecutionEvidence` signed by the bearer
   key, with a UUID as its `use_id`, the grant's digest, its place in the
   grant's use chain (`use_sequence`, `prev_use_digest`), the latest time
   token, the request parameters, the resource and what was done (metadata
   only, as for execution evidence). It checks the metadata for secret
   material **before** signing: the NA never stores a use that carries any,
   so a holder never chains a use on one. The SDKs keep the use in their
   outbox.
3. **When it can reach the NA** it asks for a fresh time token
   (`POST /grants/time-tokens`, a request its bearer key signs naming the
   head of its use chain) and uploads its uses in order
   (`POST /evidence/grant-executions`).

The NA admits each use in its chain's order and gives it the next position of
its resource's chain: positions are assigned under the lock every write to
the store takes, so two devices that changed the same resource while
disconnected never fork its chain. Execution evidence made afterwards links
to the last use (`GET /admin/evidence/resource-heads/<resource_id>` names it,
with its `entry_kind` and `record_id`).

### A refused use keeps its place

A use the NA refuses for good is kept as a `quarantine` entry, and when it
continued the holder's chain (it is at the next position and links to the
chain's head) it stays in the chain: the holder's next use links to it and is
judged on its own. Concretely:

- the **chain** is the admitted uses and the quarantined uses that continued
  it; a time token may name a quarantined use as the head;
- the **budget** counts admitted uses only;
- the **order and time rules** compare a use with the last *admitted* use;
- a use refused **without being stored** (`grant_use_secret_material`,
  `grant_use_chain_gap`, `grant_use_in_future`) takes no position: upload the
  earlier uses first, or retry a future-dated use once the NA's clock
  reaches it;
- a use refused as a **conflict** or a **chain mismatch** is kept but takes no
  position, since it does not continue the chain;
- uploading a refused use again gives the same refusal (and the same
  `quarantine_id`), and uploading an admitted use again is a duplicate
  (`200`, `"status": "duplicate"`).

### Time

A disconnected holder controls its own clock, so the NA bounds what it can
claim:

- each use carries the latest **time token** the NA signed for the holder,
  bound to the head of its use chain when it asked. A use is never dated
  more than 300 seconds before its token, and at most
  `max_uses_per_time_token` uses follow the use the token names. This rule
  needs only the use and its token, so the NA, the export verifier and every
  SDK apply it alike, and several tokens taken at one head allow no more
  uses than one;
- a token is never older than its grant;
- a use is never dated before the previous admitted use, nor with an older
  token than it;
- a use is dated within the grant's validity, and no more than 300 seconds
  after the NA records it;
- a use is uploaded no later than the grant's validity after it was made.

### What the NA refuses

In the order it checks. "Kept" means the authentic use is stored as a
`quarantine` entry (named in `error.details.quarantine_id`), since the change
it describes already happened; "in the chain" means a kept use takes its
position in the holder's chain.

The record itself:

| Reason | Kept | Meaning |
| --- | --- | --- |
| `grant_use_malformed` | no | not a `GrantExecutionEvidence` in its exact serialized form, or a `use_id` that is not a UUID |
| `grant_not_found` | no | the NA holds no such grant |
| `grant_use_invalid_signature` | no | not signed by the grant's bearer key |
| `grant_use_secret_material` | no (never stored) | its parameters or metadata look like a secret |

The chain:

| Reason | Kept | Meaning |
| --- | --- | --- |
| `grant_use_conflict` (409) | yes, not in the chain | its position is taken, or its `use_id` is another use's or another record's (observations match execution evidence, break-glass records and uses by ID) |
| `grant_use_chain_gap` | no | an earlier use is not uploaded yet: upload it first |
| `grant_use_chain_mismatch` | yes, not in the chain | does not link to the chain's head |

The use against its grant (kept, in the chain):

| Reason | Meaning |
| --- | --- |
| `grant_bearer_mismatch` | the bearer's key, but another executor sovereign |
| `grant_bearer_key_retired` | the bearer key is retired |
| `grant_use_out_of_scope` | the bearer key has a resource prefix and the use names no resource or one outside it |
| `grant_mismatch` | another grant digest than the stored grant's |
| `grant_capability_mismatch` | a capability the grant does not name |
| `grant_envelope_mismatch` | a parameter outside the envelope, or a required one missing |
| `grant_budget_exhausted` | the grant's admitted uses already reach its budget |
| `grant_time_token_invalid` | the time token is not the NA's for this grant, or is older than the grant |
| `grant_time_token_mismatch` | the time token was issued after a later use, or names another use than the store holds |
| `grant_time_token_regressed` | an older token than the previous admitted use's |
| `grant_time_token_exhausted` | more than `max_uses_per_time_token` uses after the use the token names |
| `grant_use_before_time_token` | dated more than 300 seconds before its time token |
| `grant_use_out_of_order` | dated before the previous admitted use |
| `grant_use_outside_validity` | dated outside the grant's validity |
| `grant_use_in_future` | dated more than 300 seconds after the NA records it (not kept: retried) |
| `grant_use_uploaded_late` | uploaded later than the grant's validity after it was made |
| `grant_revoked` | dated at or after the grant's revocation |

## Expiry is not a block

When a grant has ended, its budget or time token is spent, or it is revoked,
and the NA cannot be reached (a network error, a timeout, `5xx`, `429`), the
SDK falls back to break-glass ({doc}`emergency-changes`): the change runs,
its `BreakGlassRecord` is kept in the outbox, and the NA judges it after the
fact when it is reachable again. An urgent change is recorded and judged,
never blocked. A DENY is never broken through: an NA that answers decides.

## Revocation

A grant is revoked from a time; a use made before it stands, one made at or
after it is refused (`grant_revoked`, kept). The NA revokes a grant:

| Reason | When |
| --- | --- |
| `operator` | `POST /admin/grants/<grant_id>/revoke` (privileged). The body's `reason` (optional text) is stored as the revocation's `detail`; the revocation's `reason` is always `operator` |
| `attestation_revoked` | its basis attestation is revoked |
| `agreement_untrusted` | its basis agreement is no longer signed by parties this NA trusts: a recognition treaty that vouched for a party was revoked, or has expired |
| `policy_deactivated` | a policy version it is bound to is deactivated, or replaced by another version |
| `policy_activated` | a policy is activated that may deny within its envelope: the NA checks every usable grant the policy may cover again, over the rest of its validity, and revokes those it may deny |
| `bearer_key_retired` | its bearer key is retired |

Each revocation is a `grant_revocation` entry in the store. A revocation that
follows another change runs after that change commits. The NA checks every
usable grant again (its key, its policy versions, its basis, the active
policies) at start, and at most once a minute while it serves the grant
routes and the revocation feed, so one an interrupted request or a failed
write missed is made then. One grant failing its check never stops the
others.

Holders learn of revocations from the **revocation feed**
(`GET /sovereign-revocation-feed`): with grants on, it lists in
`revoked_grant_ids` the revoked grants not yet past their end. Its `sequence`
counts every grant revocation as well as every revoked attestation, with
grants on or off, so it never goes back. A holder refuses a revoked grant once
its copy of the feed is fresh.

**A compromised device**: retire its executor key. Every use the key signs is
then refused, whenever it claims to have been made, and every grant it bears
is revoked. Revoking the grant alone still admits uses dated before the
revocation.

## Turning grants off

With `EVIDENCE_GRANTS=off` the NA issues no grant, admits no use, issues no
time token and leaves `revoked_grant_ids` out of the revocation feed, so a
holder could neither upload its uses nor learn that a grant was revoked. The
NA therefore refuses to start with grants off (or with
`EVIDENCE_OUT_OF_BAND=off`) while any grant it issued has not ended; the
error names how many and when the last one ends. To turn grants off:

1. stop issuing grants and let the last ones end (their `valid_until`), or
   revoke them and wait for their end;
2. turn `EVIDENCE_GRANTS` off.

Uses made under an ended grant and not uploaded by then are refused while
grants are off; turn grants back on to admit them, within each grant's
late-upload window. The feed's `sequence` keeps counting the grant
revocations already made.

## Limits of offline trust

A grant moves the decision before the change; it cannot make a disconnected
device honest. What remains:

- **Backdating within the time rules.** After a revocation it has not seen,
  a holder can make at most `max_uses_per_time_token` uses beyond the use
  its last time token names, each dated before the revocation, whatever
  tokens it kept. Each is still bounded by its token's time, the previous
  admitted use, the grant's validity and the late-upload window. Keep
  budgets and per-token limits small, and validities short.
- **A stolen key spends the remaining budget** until its key is retired. One
  bearer key per grant and a small budget keep that bounded.
- **Revocation reaches a holder only when it reads the feed.** Between a
  revocation and the holder's next fresh feed, a holder that has not seen it
  may act. Retiring the bearer key refuses those uses when they are
  uploaded; revoking the grant refuses only those dated after it.
- **Policies change after issuance.** A grant was checked against the
  policies active when it was issued; a stricter policy revokes it once
  activated, but a holder offline until then acts on the grant.

Every use is still recorded, signed and chained, quarantined when refused,
and visible in the evidence store and in audit packs.

## Monitoring and records

- `GET /admin/grants` (read tier) lists grants, newest first by `issued_at`
  and then `grant_id`. Its `status` filter accepts `active` (neither revoked
  nor ended), `expired` and `revoked`. Each summary's `status` is `active`,
  `scheduled` (not valid yet), `exhausted` (its admitted uses reach its
  budget), `expired` or `revoked`; the `active` filter includes `scheduled`
  and `exhausted` grants. Pages are stable: `next_before` is the last
  grant's ID, passed back as `before`.
- `GET /admin/grants/<grant_id>` shows one grant, its `uses` (admitted),
  `remaining_uses`, `chain_length` (admitted and quarantined positions) and
  revocation. `GET /admin/grants/<grant_id>/uses` lists its use chain, newest
  first: each use's `use_id`, `use_sequence`, `state` (`admitted` or
  `quarantined`, with its `rejection_code`), `executed_at`, `recorded_at`,
  `store_sequence`, `resource_id`, `resource_sequence` and `outcome`
  (`limit`, `before` a `use_sequence`, `next_before`).
- `GET /admin/evidence/status` reports `evidence_grants` and, with grants on,
  `grants_issued`, `grants_active`, `grants_revoked` and `grant_uses`.
- `GET /admin/evidence/changes/<resource_id>` shows each use as a change
  `governed_by: grant`. An observer's report of a change made under a grant is
  matched to the use (by version, as for execution evidence) and is governed
  by the grant; one the observer's own facts deny is flagged, and its
  remediation armed.
- Retention keeps a grant with its uses, its quarantined uses and its
  revocation until no more can be uploaded (its end plus its validity;
  `held_back` with `"reason": "usable_grants"`), and carries the resource's
  head in its checkpoint.
- Audit packs hold the grants, uses and revocations of their range. For each
  grant a range's uses (or quarantined uses) belong to, they cite the grant,
  its whole use chain before the range (the admitted uses and the
  quarantined uses that continued it) and its revocation, so the budget,
  the time-token heads and the chain are checked. They check the policy
  versions a grant is bound to and its basis: the attestation, or the
  agreement (held in `trust/agreements.jsonl`), and report grants and
  revocations ({doc}`../reference/audit-pack-format`).

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EVIDENCE_GRANTS` | `off` | `on` issues grants and records them; needs `EVIDENCE_OUT_OF_BAND=on`. Turned off only once every grant has ended |
| `NA_GRANT_MAX_VALIDITY_SECONDS` | `86400` | the longest validity this NA grants (60 to 86400) |
| `NA_GRANT_MAX_USES` | `100` | the largest budget (1 to 10000) |
| `NA_GRANT_MAX_USES_PER_TIME_TOKEN` | `10` | the most uses that may follow the use a time token names (1 to 1000); also the default of a grant that names none |

The late-upload window is each grant's own validity, and the clock skew (for
uses dated in the future, and before their time token) is 300 seconds, fixed
so every verifier applies the same rule.
