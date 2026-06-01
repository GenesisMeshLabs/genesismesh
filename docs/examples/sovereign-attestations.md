# Example: Sovereign Membership Attestations

This example demonstrates the first v0.9 trust-portability primitive: a
membership claim issued by one sovereign and evaluated by another sovereign
under local recognition policy.

The goal is intentionally narrow:

```text
Sovereign A issues a signed membership attestation.
Sovereign B recognizes Sovereign A locally.
Sovereign B accepts the attestation.
Sovereign A revokes the attestation.
Sovereign B rejects the same attestation after revocation input.
```

This is not a full treaty system yet. Recognition policy in v0.9 is local to
the accepting sovereign. Signed recognition treaties and cross-sovereign
revocation propagation are later roadmap items.

```{mermaid}
sequenceDiagram
    participant A as Sovereign A
    participant B as Sovereign B
    participant M as Member Alice

    A->>M: MembershipAttestation(role:service:maintainer)
    B->>B: Local RecognitionPolicy recognizes A
    M->>B: Present attestation from A
    B-->>M: accepted
    A->>A: Revoke attestation
    B->>B: Apply revocation input from A
    M->>B: Present same attestation
    B-->>M: rejected locally_revoked
```

Static walkthrough:

```{image} assets/images/genesis-mesh-sovereign-attestation.png
:alt: Sovereign membership attestation flow showing local recognition and revocation
:class: screenshot
```

Animated execution:

```{image} assets/images/genesis-mesh-sovereign-attestation.gif
:alt: Sovereign membership attestation demo animation
:class: screenshot
```

## Run

The demo runs both sovereigns in one Python process for repeatability. Each
sovereign still has its own genesis block, Network Authority key, operator key,
SQLite database, and local recognition policy.

```powershell
python docs\examples\assets\scripts\sovereign-attestation-demo.py
```

Expected output:

```text
==> Sovereigns initialized
    sovereign-a: independent genesis, NA key, operator key, DB
    sovereign-b: independent genesis, NA key, operator key, DB

==> Sovereign A issued membership attestation
    subject:     alice
    roles:       role:service:maintainer

==> Sovereign B recognized Sovereign A locally
    policy: sovereign-b-recognizes-a

==> Sovereign B verified A's attestation
    accepted: True
    reason:   accepted

==> Sovereign A revoked the attestation
    reason: membership_removed

==> Sovereign B rejected the same attestation after revocation input
    accepted: False
    reason:   locally_revoked

Result: cross-sovereign membership trust is portable and revocable.
```

## What This Proves

- A sovereign can issue a signed membership attestation.
- A different sovereign can evaluate it using local recognition policy.
- Unknown issuers are rejected by default.
- Acceptance is explainable through structured reason codes.
- Revocation changes the accepting sovereign's trust decision once revocation
  input is applied.

## What This Does Not Yet Prove

- Bilateral signed recognition treaties.
- Automatic revocation propagation across sovereign boundaries.
- Derived or transitive recognition.
- Package registry enforcement.
- Connectome graph visualization.
