# Phase N -- Governed Changes and Edge Trust

**Versions**: v1.2.0 – v1.7.0
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
| 3 | v1.4.0 | Remediation (cancel by rotating forward), notification, one review record with second-person approval | Released |
| 4 | v1.5.0 | Audit packs, key succession, archive before prune, the offline verifier `genesis-mesh-verify` | Released |
| 5 | v1.6.0 | Pre-issued grants in the core and the SDKs | Released |
| 6 | v1.7.0 | The Rust edge agent | Released |

Each stage is a release of the whole train and ships when its gate is green.
Stages 5 and 6 were confirmed as the stage before them shipped; the
program is complete with v1.7.0. The plans are in
`ops/plan-v1.2.0.md` onwards.

Every new record kind is off by default: the evidence store and its anchors
need `EVIDENCE_STORE=on`, observations and break-glass need
`EVIDENCE_OUT_OF_BAND=on`, remediation needs `EVIDENCE_REMEDIATION=on`, and
grants need `EVIDENCE_GRANTS=on`. The outbox, break-glass, observations,
remediation helpers and grant holders exist only in the TypeScript and Rust
SDKs and in the edge agent.

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

**Observations, judgements and break-glass** (v1.3.0, `EVIDENCE_OUT_OF_BAND=on`):
an observer signs a change it sees at the source, such as an activity log
entry, as an observation. A controller that cannot reach the Network Authority
can run an action on a stated justification and sign a break-glass record,
never after a DENY. The Network Authority judges each record once, as of when
the change happened, under the policy versions its signed registry says were
active then. A judgement is never an approval. An authentic record refused
after its action happened is kept as a quarantine entry. The `out_of_band`
conformance suite carries the records ({doc}`../../operations/out-of-band-changes`).

**Review fixes** (v1.3.1): retention, anchoring and the Network Authority's own
verify refuse an incomplete store; judging replays only registry records the
Network Authority signed; `NA_PROXY_HOPS` defaults to `0`; and every
implementation verifies exports by the same rules.

**Remediation, reviews and notification** (v1.4.0, `EVIDENCE_REMEDIATION=on`):
a policy says what a denial leads to, per gate: cancel or alert only, after a
grace window. A controller cancels a credential by rotating forward to a new
version under a governed decision, then disabling the denied one. The Network
Authority keeps a due queue of open remediations. One signed record covers
reviews and waivers, decided by a privileged key of a holder other than the
requester and the observed actor. An urgent change runs under an emergency
capability with its own policy and a maximum lifetime
({doc}`../../operations/remediation-and-reviews`).

**Key succession, audit packs and the offline verifier** (v1.5.0): the NA key
can be succeeded by a record signed by the offline root key, the new key and
the outgoing key, and verifiers accept a record signed by the key valid at the
record's own time. A lost or compromised NA key cannot sign its own succession
and still means a new identity ({doc}`../../operations/key-succession`). A
read-tier key produces an audit pack for a range between two anchors, and a
security team verifies it offline from the root key and anchors it holds
({doc}`../../operations/audit-packs`). `genesis-mesh audit archive` writes and
verifies a pack before retention prunes. `genesis-mesh-verify` is a
hand-ported second implementation of the Python reference's verification: a
Rust port, shipped as static binaries, checked against a corpus the reference
generates.

**Pre-issued grants** (v1.6.0, `EVIDENCE_GRANTS=on`, beta): the Network
Authority signs, in advance, a capability grant for one registered executor
key, for at most 24 hours, within a budget and a parameter envelope every
applied policy allows. A holder acts within the grant while it cannot reach
the Network Authority, using NA-signed time tokens, and uploads its uses on
reconnect. The Network Authority admits each use that keeps to the grant and
quarantines the rest. Revoked grants are listed in the signed revocation feed
({doc}`../../operations/grants`).

**The edge agent** (v1.7.0, beta): `genesis-mesh-edge`, a static Rust agent
released with the Rust SDK, enrols with an edge invite and generates its node
and executor keys on the device. Local services ask it whether an action may
run. It asks the Network Authority for a node-scoped decision, acts within its
grants when the Network Authority cannot be reached, and only then breaks the
glass. Every record waits in a durable outbox. Revoking the node retires its
executor key and revokes its grants in one step
({doc}`../../operations/edge-agent`).

## Value Added

- Evidence of a governed action survives the Network Authority being
  unreachable, and the action's value is never lost with it.
- A record a verifier cannot fully read is refused by name instead of being
  accepted with a meaning it does not understand.
- One record gets one verdict in every implementation.
- Removing evidence from an anchored range is detectable by anyone holding a
  copy of the anchors, including against the Network Authority's operator.
- A change made outside a governed action, or under break-glass, is on the
  record and judged as of its time (`EVIDENCE_OUT_OF_BAND=on`).
- A change judged DENY is cancelled by rotating forward, or waived by a second
  person, on the record (`EVIDENCE_REMEDIATION=on`).
- The NA key can be succeeded under the offline root key. A compromised key
  still means a new identity.
- An auditor verifies an audit pack offline, with `genesis-mesh-verify` or the
  Python reference.
- A device acts within NA-signed grants while the NA is unreachable
  (`EVIDENCE_GRANTS=on`).
- `genesis-mesh-edge` (beta) runs governed actions on a device with keys it
  generated itself, and one revocation ends its authority.

## What Became Possible

Every governed change leaves a signed record, whether or not the Network
Authority could be reached. A security team can verify those records years
later, offline, from the root key and anchors it holds.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v1.2.0 | Stage 1, Nothing Lost, Anchored: evidence outbox, strict verifiers and the field registry, the canonicalization corpus, signed store anchors |
| v1.3.0 | Stage 2, Observations, Judgements and Break-Glass: changes made outside governed actions recorded and judged once as of their time, break-glass records, quarantine, the store's signed registry |
| v1.4.0 | Stage 3, Remediation, Reviews and Notification: a change judged DENY cancelled by rotating forward after a grace window, one review record for reviews and waivers decided by a second holder, emergency capabilities, the due queue and notices |
| v1.5.0 | Stage 4, Audit Packs and Independent Verification (release name): NA key succession with an offline root key, audit packs verified offline from held anchors, completeness against outside logs, archive before prune, read-tier evidence access, the offline verifier `genesis-mesh-verify` (a hand-ported second implementation) |
| v1.6.0 | Stage 5, Pre-Issued Grants: capability grants issued only for envelopes every applied policy allows, NA-signed time tokens, grant uses admitted or quarantined on one resource chain, revocation from a time listed in the revocation feed, grant holders in the TypeScript and Rust SDKs that fall back to break-glass |
| v1.7.0 | Stage 6, The Edge Agent: `genesis-mesh-edge` (beta) enrols with an edge invite and registers its executor key at join, asks node-scoped decisions only under attestations issued to it, acts within its grants and breaks the glass only when the Network Authority cannot be reached, and keeps every record in a durable outbox; revoking a node retires its key and grants in one step |
