# RFC-008 — Managed Operator Role

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-007

## Abstract

Some operators want the delivery confidence of a larger firm without giving up
sovereignty. This RFC defines the *managing partner* (or managed operator) role:
what a managing partner may do on behalf of an operator, what must remain under
the operator's exclusive control, and how a managing partner coordinates public
endpoints, runbooks, and trust material without becoming the protocol's owner.
The pattern is represented in the project by Connectorzzz.

## Motivation

Phase 2 introduces a coordinating party that helps independent operators onboard
and stay continuous (RFC-007). That help is valuable only if it cannot quietly
become control. RFC-008 draws the line: a managing partner operationalizes the
ecosystem; it does not hold the keys that define a sovereign. This keeps the
"no permanent central authority" guarantee intact even when a firm coordinates
many operators.

## Terminology

- **Operator** — the party that owns a sovereign: its genesis block, root key,
  policy, and revocation authority (RFC-001).
- **Managing partner** — a party that assists operators with onboarding,
  coordination, and continuity, without owning their trust material.
- **Managed operator** — an operator who has engaged a managing partner.
- **Control material** — root key, operator signing keys, and the authority to
  issue treaties and revocations.

## Normative requirements

1. Control material **MUST** remain under the operator's exclusive control. A
   managing partner **MUST NOT** hold an operator's root key or operator signing
   keys.
2. A managing partner **MUST NOT** issue treaties (RFC-002) or revocations
   (RFC-004) on an operator's behalf using the operator's identity. Those
   actions **MUST** be signed by the operator's own keys.
3. A managing partner **MAY** assist with public endpoint management, DNS,
   hosting, runbooks, continuity checks (RFC-007), trust-bundle assembly
   (RFC-003), and client-facing packaging.
4. A managed operator **MUST** retain the right to fork, revoke, exit, or change
   managing partners without protocol-level permission from anyone, including
   the managing partner.
5. Assistance **MUST** be auditable and attributable: where a managing partner
   acts, the action **MUST** be distinguishable from an operator-key action.
   Proof artifacts **MUST** record assistance notes rather than implying the
   managing partner controlled keys (consistent with the proof-bundle schema).
6. A managing partner **MUST NOT** be positioned as a required intermediary for
   trust decisions between sovereigns. Recognition and revocation **MUST**
   remain operator-to-operator.

## Role boundary

| Action | Operator | Managing partner |
| --- | --- | --- |
| Hold root key | yes | **never** |
| Hold operator signing keys | yes | **never** |
| Issue/revoke treaties (RFC-002) | yes | no |
| Publish revocation feed (RFC-004) | yes | no |
| Manage public endpoints / DNS | optional | yes (on request) |
| Maintain runbooks & continuity checks (RFC-007) | yes | yes (assist) |
| Assemble trust bundles (RFC-003) | yes | yes (assist) |
| Client-facing packaging & coordination | optional | yes |
| Fork / exit / switch partner | yes | cannot block |

## Security considerations

- The strongest guarantee Genesis Mesh offers is that no party becomes a
  permanent central authority. A managing partner that held control material
  would silently break that guarantee, so the key-custody boundary is the
  load-bearing rule of this RFC.
- Attribution matters: adoption proofs are only honest if assistance is recorded
  as assistance. The proof-bundle schema deliberately separates "operator
  controls keys/infrastructure" flags from "maintainer observed but did not
  handle private keys" assistance notes.
- An operator's exit rights are a security property: the ability to leave
  prevents lock-in from becoming de facto control.

## Operational considerations

- The managing-partner pattern is how the ecosystem scales onboarding without
  centralizing trust: Connectorzzz provides onboarding, coordination, endpoint
  management, and continuity support; operators keep identity, recognition,
  revocation, and trust-path authority.
- Governance roles, change authority, and the RFC process that frames this role
  are described in {doc}`/development/governance-baseline`.

## Compatibility notes

- This RFC governs roles and custody, not wire format. Any implementation can
  honor it by keeping control material with operators and recording assistance
  honestly.

## Open questions

- Should the managing-partner relationship itself be expressed as a signed,
  revocable on-network artifact (so an operator can publicly attest "X manages my
  endpoints, not my keys"), or remain an out-of-band agreement?
- Should there be a normative, machine-checkable assertion that a given action
  was operator-signed rather than partner-assisted, beyond the proof-bundle
  assistance notes?
