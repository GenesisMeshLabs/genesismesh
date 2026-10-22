# Governed Changes and Evidence

From 1.2 to 1.7 the Network Authority (NA) gained a second job beside
identity and decisions: it records the changes made to the resources it
governs, judges changes made outside the controlled path, authorises changes
in advance for devices that cannot reach it, and gives auditors material they
check offline. This page states, for each record, what it is, who signs it,
which setting turns it on, and where the runbook is. The runbooks are under
{doc}`../operations/governed-changes-and-audit`.

## Settings

Everything on this page is off by default. Each switch needs the one above it.

| Setting | Default | Needs | Turns on |
| --- | --- | --- | --- |
| `EVIDENCE_STORE` | `off` | none | The evidence store, store anchors, audit packs and archives (1.2, 1.5) |
| `EVIDENCE_OUT_OF_BAND` | `off` | `EVIDENCE_STORE=on` | Observations, break-glass records, judgements, quarantine and registry entries, operator key holders (1.3) |
| `EVIDENCE_REMEDIATION` | `off` | `EVIDENCE_OUT_OF_BAND=on` | Remediation and review records, and policies with `remediation`, `review_required` or `emergency` sections (1.4) |
| `EVIDENCE_GRANTS` | `off` | `EVIDENCE_OUT_OF_BAND=on` | Pre-issued grants, time tokens, grant uses and revocations (1.6, beta routes) |

The edge agent (1.7, beta) has no switch of its own: the edge routes do
nothing until an operator creates an edge invite, and the agent needs the
evidence store and out-of-band records on. Key succession needs no switch.
Settings are described in
{ref}`Evidence Features <config-evidence-features>`.

Turn each switch on only once every verifier that reads your exports runs
the release that added it: an older verifier refuses entry kinds it does not
know.

## Where each side runs

- **The NA** (Python) issues decisions, grants and time tokens, admits and
  judges records, and signs anchors, packs and the other NA records. Only the
  NA runs the policy engine.
- **The TypeScript and Rust SDKs, and the edge agent,** are the controller
  side: the outbox, break-glass, observation signing and reconciliation
  (`reconcileResources` in TypeScript), the remediation helpers and grant
  holders exist only there. The Go
  and .NET SDKs do not wrap the evidence store.
- **Verifiers** check exports and packs offline: the `genesis-mesh` CLI
  (`evidence verify-export`, `audit verify`), the TypeScript and Rust SDKs,
  and `genesis-mesh-verify`, a second verifier built from the Rust SDK.

## How a change is governed

Each change on a resource is shown with how the NA came to know it
(`governed_by`):

| `governed_by` | Meaning |
| --- | --- |
| `prior_decision` | A decision allowed it before it was made, and execution evidence records it |
| `after_the_fact` | It was made without a decision (observed, or break-glass) and the NA judged it afterwards under the policies active at the time |
| `grant` | A grant authorised it in advance and the holder uploaded the use later |

`GET /admin/evidence/changes/<resource_id>` lists a resource's changes with
their state. A DENY is never broken through: break-glass applies only when
the NA could not be asked at all.

## Evidence store and anchors (1.2)

The store is an append-only log, one hash chain: each entry carries the
digest of the one before it. It has been in the NA since 0.59; 1.2 added
signed anchors and the SDK outbox.

| Record | Signed by | What it is |
| --- | --- | --- |
| `decision`, `justification` | the NA | A boundary decision and its justification proof, stored as the NA signs them |
| `execution` | an executor key | `ExecutionEvidence`: what a controller did under a decision. The NA never signs it; it checks, links and keeps it |
| `retention_checkpoint` | the NA | A deliberate removal of the oldest entries by retention |
| `StoreAnchor` (outside the chain) | the NA | The store's head at one moment: a `store_sequence` and that entry's digest |

Executor keys are registered by a `privileged` operator key, each optionally
limited to a resource prefix. The SDK **outbox** keeps signed records on the
controller until the NA has them, so a record is not lost while the NA is
unreachable.

Anchors make a rewritten store detectable, not impossible. The NA's operator
holds the NA key and can sign new anchors, so only anchors copied out to
storage the operator cannot change protect history against them. See
{doc}`../operations/evidence-anchors` and the examples
{doc}`../examples/evidence-store` and
{doc}`../examples/execution-evidence-chain`.

## Observations and break-glass (1.3)

`EVIDENCE_OUT_OF_BAND=on` records changes made outside the controlled path.

| Record | Signed by | What it is |
| --- | --- | --- |
| `observation` | an observer key | A change an observer saw at its source: a cloud audit log entry, or a reconciliation finding. Its `actor` is reported by the source, not authenticated |
| `break_glass` | an executor key | A change a controller made while the NA could not be asked (network error, timeout, `5xx`, `429`), with the caller's justification |
| `judgement` | the NA | The NA's one verdict on an observation or break-glass record, as of when the change happened: allowed, denied or `indeterminate`, possibly flagged for review |
| `quarantine` | the NA | An authentic record the NA refused after its action happened, kept with the refusal |
| `registry` | the NA | The NA state judgements rest on: policy activations, executor and observer keys, operator key holders |

Observer keys are registered like executor keys, with the role `observer`,
and sign observations only. See {doc}`../operations/out-of-band-changes`,
{doc}`../operations/emergency-changes` and the example
{doc}`../examples/out-of-band-changes`.

## Remediation and reviews (1.4)

`EVIDENCE_REMEDIATION=on` makes a judged DENY lead somewhere. The NA states
what is to be done and by when; the controller does it. The NA never changes
a cloud resource itself.

| Record | Signed by | What it is |
| --- | --- | --- |
| `remediation` | an executor key | What a controller did about a judged change: `cancelled` (rotate forward, then disable; or disable) or `alerted` |
| `review` | the NA | A second person's verdict on a judged change or a decision (`uphold`, `deny` or `waive_until`), with the decider's signed admin request embedded so it can be checked offline |

The remediation state (`remediation_due`, `overdue`, `remediated`,
`upheld`, `waived`) is kept beside the store and is not signed: it follows from the signed records and the clock. A
review's decider must be a `privileged` key with a named holder different
from the requester's and the change's actor. Policies may also name an
**emergency capability**: an urgent change under an ordinary DENY is decided
under its own policy and reviewed afterwards. See
{doc}`../operations/remediation-and-reviews`.

## Audit packs, archives and key succession (1.5)

| Record | Signed by | What it is |
| --- | --- | --- |
| `AuditPackManifest` | the NA | `manifest.json` of an audit pack: one period of the store between two anchors, with everything its records cite, the key history and a report. Every file's SHA-256 |
| `archive` (`ArchiveRecord`) | the NA | A pack written to immutable storage and read back. That the storage is immutable is the word of the `privileged` key that recorded it |
| `key_succession` (`KeySuccessionRecord`) | the root key, the new NA key and the outgoing NA key | Names the NA's next key. Recorded in the store when it is on |

A pack needs only a `read` key to build. With `NA_RETENTION_REQUIRE_ARCHIVE`
on (the default), retention removes nothing an archive does not cover. A
pack is checked from the root public key and the anchors the auditor holds.
See {doc}`../operations/audit-packs`, {doc}`../operations/audit-verification`,
{doc}`../operations/independent-verification` and
{doc}`../operations/key-succession`; the formats are in
{doc}`../reference/audit-pack-format`.

Key succession replaces the NA key while keeping the sovereign's identity:
records signed by the old key keep verifying through the key history
(`GET /na/key-history`). It does not cover a compromised NA key. See
[Key succession](trust-model.md#key-succession) in the trust model.

## Pre-issued grants (1.6)

`EVIDENCE_GRANTS=on` lets the NA authorise a bounded kind of change in
advance, for a device or controller that may not reach it. The signed forms
are stable; the grant routes are beta.

| Record | Signed by | What it is |
| --- | --- | --- |
| `grant` (`CapabilityGrant`) | the NA | An authorisation for one bearer (executor) key: capabilities, a basis (attestation or agreement), validity (at most 24 hours), a budget and a closed parameter envelope. The NA checks at issuance that every active policy allows every request the envelope permits |
| `TimeToken` | the NA | A time the NA signed for the holder, bound to the head of its use chain. It bounds how far an offline holder can backdate |
| `TimeTokenRequest` | the bearer key | The holder's request for a fresh time token |
| `grant_execution` (`GrantExecutionEvidence`) | the bearer key | One use of a grant, chained to the holder's previous use, uploaded when the holder reconnects |
| `grant_revocation` (`GrantRevocationRecord`) | the NA | A revocation from a time; revoked grants are listed in the revocation feed (`revoked_grant_ids`) |

A grant never overrides a DENY. When a grant has ended, is spent or revoked
and the NA cannot be reached, the SDK falls back to break-glass. See
{doc}`../operations/grants` and the example
{doc}`../examples/pre-issued-grants`.

## The edge agent (1.7, beta)

The edge agent `genesis-mesh-edge` acts for one device that changes the
resources it holds and is often offline. It adds no new signed record; it
puts the records above on a device.

- **Edge invite:** a `privileged` operator key creates an invite naming the
  device's sovereign ID and the resource prefix its executor key may act on.
- **Enrolment:** at `/join` the device's executor key co-signs the request
  and the NA registers it. The device holds no operator key.
- **Node-scoped decisions:** the device asks `/node/boundary/evaluate` with
  requests its node key signs; the NA decides with the device as the
  requester, only under attestations issued to its sovereign ID.
- **Offline:** the device acts under the grants its executor key bears, or
  records break-glass, and uploads the records in order when it reconnects.
- **Edge revocation:** revoking any of the node's certificates revokes the
  node: all its certificates, its executor key and the grants that key bears.

The agent ships with the Rust SDK and as the image
`ghcr.io/genesismeshlabs/genesis-mesh-edge`. See
{doc}`../operations/edge-agent` and {doc}`../stability` (*Edge agent*).

## What each part proves

What is signed, checked and only detectable for each part is in the
{doc}`security-model`.
