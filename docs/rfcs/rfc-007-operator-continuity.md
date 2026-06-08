# RFC-007 — Operator Continuity

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-001, RFC-002, RFC-003, RFC-004

## Abstract

Standing up a sovereign once is not the same as operating one. This RFC defines
the ongoing obligations of a sovereign operator after the initial proof: what
must stay online, what trust material must be refreshed, at what cadence health
and trust checks should run, and what an intentional offline state looks like.
Continuity is what turns a one-time demonstration into a dependable trust
domain.

## Motivation

Recognition (RFC-002) and revocation (RFC-004) are only meaningful if the
recognizing and issuing sovereigns remain reachable and current. An operator who
disappears silently leaves stale trust in the network. RFC-007 makes continuity
explicit and checkable so that an operator's "still here and trustworthy" state
is evidence, not assumption.

## Terminology

- **Continuity** — the operator's ongoing obligation to keep their sovereign
  reachable, current, and verifiable.
- **Continuity check** — a periodic verification that endpoints, treaties,
  feeds, and trust material are healthy.
- **Intentional offline state** — a declared, bounded pause distinct from silent
  abandonment.

## Normative requirements

1. An operator **MUST** keep the sovereign's public trust endpoints reachable:
   at minimum the identity/genesis material (RFC-001), the recognition material
   (RFC-002), and the revocation feed (RFC-004).
2. An operator **MUST** keep liveness endpoints (`healthz`/`readyz` in the
   reference implementation) serving accurate status.
3. An operator **MUST** review treaties approaching expiry (`expiring_soon`,
   RFC-006) and renew, replace, or intentionally let them lapse — but not let
   them lapse unobserved.
4. An operator **MUST** be able to publish a revocation feed and confirm that a
   recognizing sovereign rejects the previously accepted attestation
   (end-to-end revocation continuity).
5. An operator **SHOULD** refresh exported trust bundles (RFC-003) so reviewers
   are not relying on stale review material.
6. An operator **SHOULD** maintain backups of durable trust state sufficient to
   restore the sovereign without changing its `sovereign_id` or root key
   (RFC-001).
7. An operator that goes offline intentionally **SHOULD** declare it as a bounded
   state rather than disappearing silently, so recognizing sovereigns can
   distinguish a planned pause from abandonment.
8. Continuity evidence **MUST NOT** require disclosing private control material;
   it is built from the same public, redacted artifacts as the rest of these
   RFCs.

## Recommended cadence

The reference operator guidance (`docs/operators/`) recommends recurring checks.
Exact intervals are operator policy; the obligations are normative, the numbers
are reference:

| Check | What it confirms | Reference cadence |
| --- | --- | --- |
| Endpoint health | `healthz`/`readyz` serving, TLS valid | continuous / frequent |
| Treaty expiry review | no treaty lapses unobserved (RFC-002/006) | periodic |
| Revocation proof | publish feed, confirm downstream rejection (RFC-004) | periodic |
| Trust-bundle refresh | reviewers see current material (RFC-003) | periodic |
| Backup verification | sovereign restorable without identity change | periodic |
| Connectome review | recognition edges and blast radius as expected (RFC-006) | periodic |

## Security considerations

- Stale trust is a security problem: an unreachable issuer cannot propagate a
  revocation, and an unobserved expiring treaty can drop recognition silently.
  Continuity checks are how an operator detects these before they bite.
- Backups must preserve identity continuity (same `sovereign_id`, same root key)
  while never exposing the root private key in transit or at rest beyond the
  operator's control.
- An intentional-offline declaration must itself be verifiable so it cannot be
  forged by an attacker to mask a real outage.

## Operational considerations

- Continuity is the difference between maintainer-operated proof and adoption
  proof: the open question for any operator is not "did it work once?" but "is it
  still working and still theirs?"
- The founding community operator material and the external-operator proof
  workflow in `docs/operators/` are the practical expression of these
  obligations.

## Compatibility notes

- This RFC governs operator behavior, not wire format. An independent
  implementation interoperates at the continuity layer by exposing the same
  public endpoints and refreshing the same artifacts, regardless of internal
  tooling.

## Open questions

- Should continuity signals be aggregated into a signed, publishable "operator
  heartbeat" artifact, or remain a set of independent endpoint and trust-material
  checks?
- Should recognizing sovereigns automatically downgrade trust after a declared
  or detected continuity lapse, or always require operator review?
