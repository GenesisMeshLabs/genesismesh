# Operator Guides

These guides are for people running or validating a Genesis Mesh sovereign.
They focus on independent key ownership, public metadata, recognition proofs,
and evidence bundles.

Use this section when you need to stand up a Network Authority, verify that an
operator controls their own trust domain, or run a cross-sovereign recognition
workflow.

## Setup and Security

- [Operator Quickstart](quickstart.md): stand up a named sovereign on a VM.
- [Production Checklist](production-checklist.md): move the root key offline,
  turn on what is off by default, and check the host before others rely on
  your sovereign.
- [Security Checklist](security-checklist.md): confirm independent operator
  control before counting adoption evidence.
- [Maintainer-Operated Multi-Cloud Sovereigns](maintainer-operated-sovereigns.md):
  review the v0.18.0 maintainer-operated multi-cloud sovereign fleet and the
  continuity cadence for active sovereigns.
- [Key Succession and the Root Key](../operations/key-succession.md): replace
  the NA key while keeping the sovereign's identity.

## Federation and Recognition

- [Federation Bootstrap](federation-bootstrap.md): review another sovereign and
  issue the first direct-recognition treaty.
- [Trust Bundle Exchange](trust-bundle-exchange.md): export, inspect, and
  validate public trust material before federation review.
- [External Operator Proof](external-operator-proof.md): run and evaluate an
  independent-operator recognition and revocation proof.
- [Treaty Lifecycle](treaty-lifecycle.md): list, inspect, renew, replace, and
  revoke direct-recognition treaties.
- [Recognition Playbook](recognition-playbook.md): run direct recognition and
  revocation between sovereigns.
- [Exit and Fork](exit-and-fork.md): leave a federation or a managing partner,
  or fork the software.
- [Managing Partner Boundary](managing-partner-boundary.md): what a managing
  partner may do and what stays with the operator.

## Reference

- [Sovereign Dashboard](sovereign-dashboard.md): read local health, treaty
  risk, revocation freshness, and recent trust changes from one public,
  read-only page.
- [Proof Bundle Schema](proof-bundle-schema.md): understand the redacted JSON
  evidence bundle produced by remote proof workflows.
