# Example: Cross-Sovereign Revocation Propagation

This example proves the v0.11 trust-withdrawal path across sovereign
boundaries. Sovereign A accepts a membership attestation issued by Sovereign B
through an active recognition treaty. Later, Sovereign B revokes that
attestation and publishes a signed revocation feed. Sovereign A imports the
feed and rejects the same attestation without revoking the treaty itself.

```{mermaid}
sequenceDiagram
    participant B as Sovereign B
    participant A as Sovereign A
    participant F as Signed Revocation Feed
    participant G as Recognition Graph

    B->>B: Issue MembershipAttestation for Alice
    A->>A: Activate RecognitionTreaty for Sovereign B
    B-->>A: Present attestation
    A-->>B: accepted through treaty
    B->>F: Publish feed revoking attestation
    A->>A: Verify feed under treaty subject key
    A->>A: Import revoked attestation ID
    B-->>A: Present same attestation
    A-->>B: rejected: attestation_locally_revoked
    A->>G: Export graph with propagated revocation
```

## What This Proves

- The issuer sovereign controls withdrawal of its own attestations.
- The accepting sovereign can import revocation state without removing the
  broader recognition treaty.
- Imported revocations affect treaty-backed attestation verification.
- The recognition graph exposes propagated revoked trust material.
- Stale feed imports are rejected by sequence number.

## Live Recording

```{image} assets/images/genesis-mesh-cross-sovereign-revocation.gif
:alt: Cross-sovereign revocation propagation demo
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-cross-sovereign-revocation.png
:alt: Static screenshot of the cross-sovereign revocation demo
:class: screenshot
```

## Run

From the repository root:

```powershell
python docs\examples\assets\scripts\cross-sovereign-revocation-demo.py
```

The script creates two temporary Network Authority instances in process:

- `sovereign-a`: the accepting sovereign
- `sovereign-b`: the issuing sovereign

No persistent state or external network is required.

## Expected Proof

```text
==> Sovereign B issued membership attestation
    attestation: <attestation-id>
    subject:     alice

==> Sovereign A recognized Sovereign B through active treaty
    treaty: <treaty-id>

==> Sovereign A accepted B's attestation before feed import
    accepted: True
    reason:   accepted

==> Sovereign B published signed revocation feed
    feed sequence: 1
    revoked IDs:   1

==> Sovereign A imported B's revocation feed
    accepted: True
    sequence: 1

==> Sovereign A rejected the same attestation after feed import
    accepted: False
    reason:   attestation_locally_revoked

==> Recognition graph includes propagated revoked attestation
    propagated revocations: 1
    recognition_edges:      1
```

## Operational Meaning

A recognition treaty says "this sovereign may issue trust material I am willing
to evaluate." A revocation feed says "the issuer has withdrawn this specific
piece of trust material."

Those are intentionally separate. Sovereign A can continue recognizing
Sovereign B for future attestations while rejecting the revoked attestation
immediately after importing B's signed feed.

## API Surfaces

The demo exercises these v0.11 endpoints:

- `GET /sovereign-revocation-feed`
- `POST /admin/sovereign-revocation-feeds/import`
- `POST /attestations/verify-with-treaty`
- `GET /recognition-graph`

## Verification

Focused tests:

```powershell
python -m pytest `
  genesis_mesh\tests\test_recognition_treaties.py `
  genesis_mesh\tests\test_na_treaties.py `
  -q
```

Expected result:

```text
18 passed
```
