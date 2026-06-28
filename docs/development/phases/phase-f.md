# Phase F -- Multi-Cloud Operation

**Versions**: v0.18.0 – v0.21.0
**Question**: Can separate sovereigns run across real cloud boundaries, and what still has to happen before external adoption is real?

## What Changed

Maintainer-operated sovereign deployments were represented through public
proof material — each with its own identity, Network Authority key,
operator key, policy, endpoint, and public proof artifacts. The Operator
Quality Test was named explicitly: did the operator ask to run a sovereign
or were they pushed; do they have a reason that exists even without
Genesis Mesh; would they keep operating after the proof; are they willing
to be named publicly?

Multi-cloud deployments across Azure, DigitalOcean, Cloudflare, and
Linode became an ongoing continuity model with documented expectations:
endpoint health, backups, treaty expiry review, trust-bundle refresh,
recurring attestation/revocation proof, and Connectome state checks.

The ecosystem baseline named the next proof surfaces explicitly: RFCs,
Atlas, governance, independent implementations, and one native application.

Eight protocol RFCs were published under `docs/rfcs/`, each
implementation-informed and mapped to a reference module: sovereign
identity, recognition treaties, trust bundles, revocation feeds,
capability manifests, the Connectome model, operator continuity, and
the managed operator role. The protocol became readable as a standard,
not only as Python.

## Value Added

- Maintainer-operated multi-cloud sovereigns are public, named, and
  have separate trust material with documented continuity expectations.
- The protocol can be read as a standard through eight published RFCs.
- The next external adoption risks are explicitly named: they are not
  technical; they are governance, independent implementation, and
  application-layer relevance.

## What Became Possible

With the protocol readable as a standard and the adoption risks named,
Phase G built the application layer that makes the fabric legible to
people who do not read RFCs.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.18.0 | Multi-cloud sovereign proof material; Operator Quality Test defined |
| v0.19.0 | Ongoing continuity model: health, backups, treaty review, feed freshness |
| v0.20.0 | Ecosystem baseline: RFCs, Atlas, governance, implementation roadmap |
| v0.21.0 | RFC Batch 1: eight protocol RFCs published under docs/rfcs/ |
