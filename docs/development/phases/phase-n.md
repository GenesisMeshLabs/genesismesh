# Phase N -- Governed Changes and Edge Trust

**Versions**: v1.2.0 – (in progress)
**Question**: Can every change leave a signed record, whether or not the
Network Authority could be reached, and can a security team verify those
records years later without trusting whoever runs the Network Authority?

Phases K, L and M were the TypeScript, Go and .NET SDK releases (v0.53.0 to
v0.55.0); the history narrative records them.

## The Program

Phase N is a program of six stages, one per minor release. The Network
Authority stays the Python reference and the only issuer of decisions.

| Stage | Release | Delivers | Status |
|-------|---------|----------|--------|
| 1 | v1.2.0 | Durable SDK evidence outbox; strict, forward-compatible verifiers and the canonicalization corpus; signed store anchors copied to storage the auditor controls | Released |
| 2 | v1.3.0 | Observations, after-the-fact judgements, break-glass when the Network Authority is unreachable, quarantined records | Released |
| 3 | v1.4.0 | Remediation (cancel by rotating forward), notification, one review record with second-person approval | Planned |
| 4 | v1.5.0 | Audit packs, key succession, archive before prune, the independent verifier `genesis-mesh-verify` | Planned |
| 5 | v1.6.0 | Pre-issued grants in the core and the SDKs | To be confirmed |
| 6 | v1.7.0 | The Rust edge agent | To be confirmed |

Each stage is a release of the whole train and ships when its gate is green.
Stages 5 and 6 are confirmed or deferred once Stage 4 ships. The plans are in
`ops/plan-v1.2.0.md` onwards.

## What Changed

**Evidence outbox** (v1.2.0): before 1.2.0, a governed action whose evidence
could not be submitted raised an error that carried neither the signed
evidence nor the action's value, so the record was lost. With an outbox
(`ClientOptions.outbox` in TypeScript, `with_outbox` in Rust), the SDK writes
each record to storage the caller supplies before submitting it, returns the
action's value, and removes the record only once the Network Authority admits
it. A record refused for good is dead-lettered with its code. A second action
on the same resource chains from the pending record instead of conflicting
with it. The outbox is opt-in, because the TypeScript SDK's `governedAction`
is stable.

**Strict, forward-compatible verifiers** (v1.2.0): verifiers used to copy
unknown fields into the canonical form, so a field a verifier did not know
still verified and could change a record's meaning silently. A field
registry generated from the Python models now ships in every SDK. Every
verifier checks the signature over the record as received, refuses a signed
field it does not know (`unknown_field`) and an export entry of an unknown
kind (`unknown_entry_kind`). The conformance suite `field_registry` carries
the cases.

**Canonical input and form** (v1.2.0): the five implementations read some
JSON differently. .NET kept both of two duplicate keys, Python wrote `NaN`
back as non-JSON, Go replaced a lone surrogate, and Rust read a large
integer as a float. Python also re-wrote a received record before checking
it. Every implementation now refuses such input by a named reason, admits a
record only in its canonical form (`non_canonical_form`), and checks a record
in one order, so a record with two faults gets one reason everywhere. The
conformance suite `canonical` (97 vectors) carries the cases.

**Signed store anchors** (v1.2.0): the evidence store's hash chain proved
order, not completeness: whoever could write the database could remove an
entry and rebuild the chain. The Network Authority now signs its store's
head (`StoreAnchor`) on an interval and on request. `genesis-mesh evidence
anchors fetch` copies anchors to storage the auditor controls, and
`--known-anchors` makes verification fail on an export that removed,
rewrote or truncated an anchored range.

**Request handling** (v1.2.0): forwarded headers are honoured only from
trusted proxies, and `NA_PUBLIC_URL` fixes the advertised origin. Failed
admin authentications count per key, so one operator's failures behind a
shared address no longer lock out the others. The gateway forwards the
authority's `Retry-After` and its request ID.

## Value Added

- Evidence of a governed action survives the Network Authority being
  unreachable, and the action's value is never lost with it.
- A record a verifier cannot fully read is refused by name instead of being
  accepted with a meaning it does not understand.
- One record gets one verdict in every implementation.
- Removing evidence from an anchored range is detectable by anyone holding a
  copy of the anchors, including against the Network Authority's operator.

## What Becomes Possible

With records kept and anchored, Stage 2 can let a change proceed when the
Network Authority is unreachable and judge it afterwards, and Stage 4 can
hand an auditor a pack to verify independently.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v1.2.0 | Stage 1, Nothing Lost, Anchored: evidence outbox, strict verifiers and the field registry, the canonicalization corpus, signed store anchors |
| v1.3.0 | Stage 2, Observations, Judgements and Break-Glass: changes made outside governed actions recorded and judged once as of their time, break-glass records, quarantine, the store's signed registry |
