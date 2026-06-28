# Phase D -- Operational Proof

**Versions**: v0.12.1
**Question**: Does the protocol work between actually independent infrastructure?

## What Changed

Two sovereigns were deployed on genuinely separate infrastructure: one on
Azure (`na.genesismesh.connectorzzz.com`), one on DigitalOcean — separate
VM, separate IP, separate keypair, separate database, separate policy.
They spoke the same protocol with no shared secrets or configuration.

The proof motion ran in full:

1. Both authorities started from empty Connectome state.
2. The Azure sovereign signed a recognition treaty for the DigitalOcean sovereign.
3. The DigitalOcean sovereign issued a membership attestation.
4. Azure accepted the attestation before revocation.
5. The DigitalOcean sovereign revoked the attestation and published its signed revocation feed.
6. Azure imported the feed.
7. Azure rejected the same attestation after revocation.

## Value Added

- The protocol claim moved from "could work across boundaries in principle"
  to "has worked across boundaries on these specific IPs and these
  specific keys at this specific time."
- Every step of the proof is a signed artifact that can be independently verified.

## What Became Possible

With real cross-infrastructure operation proven, the next question was:
how do new operators onboard without being the maintainer? Phase E
built the readiness surface that answers that question.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.12.1 | First live cross-cloud operational proof: Azure + DigitalOcean, full treaty-revocation cycle |
