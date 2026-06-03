# Genesis Mesh vs Sigstore And SLSA

Supply-chain trust already has strong tools: Sigstore, SLSA, npm provenance,
PyPI attestations, GitHub artifact attestations, and transparency logs. Genesis
Mesh is not a replacement for those systems.

The shortest distinction is:

> Sigstore and SLSA sign provenance inside one trust domain. Genesis Mesh
> carries portable trust across independent sovereigns and revokes it so a
> compromised maintainer is rejected everywhere that recognizes the issuer.

## What Sigstore And SLSA Are Good At

- Signing artifacts and provenance.
- Binding builds to identities and workflows.
- Making tampering and unsigned artifacts visible.
- Improving registry and build-system assurance.

Genesis Mesh should integrate with that world, not pretend it replaces it.

## What Genesis Mesh Adds

- Independent sovereigns that own their own keys, policy, and revocation feed.
- Recognition treaties between sovereigns.
- Portable maintainer attestations that can be accepted by another project.
- Revocation that changes downstream acceptance without local re-enrollment.
- A Connectome-style explanation of why one sovereign currently trusts another.

## Practical Combination

A release path can use both:

1. Sigstore or SLSA proves what was built and by which workflow.
2. Genesis Mesh proves whether the maintainer or release actor is currently
   trusted by a recognized sovereign.
3. Revocation feed import blocks the same maintainer if trust is withdrawn.

The v0.15 supply-chain gate is deliberately narrow. It proves the portable trust
decision, not the entire software supply-chain stack.
