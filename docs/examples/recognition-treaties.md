# Example: Recognition Treaties

This example shows direct recognition between two independently administered
sovereign trust domains.

The goal is to prove the v0.10.0 primitive:

```text
Sovereign B issues a membership attestation.
Sovereign A signs a recognition treaty for Sovereign B.
Sovereign A accepts B's attestation through that treaty.
Sovereign A revokes the treaty.
The same attestation is rejected.
Sovereign A exports the recognition graph.
```

Recognition treaties are intentionally narrow. They are not reputation scores,
marketplace listings, or transitive trust. They are signed, scoped, revocable
direct-recognition artifacts that say one sovereign accepts attestations from
another sovereign under explicit local rules.

```{mermaid}
sequenceDiagram
    participant B as Sovereign B
    participant A as Sovereign A
    participant G as Recognition Graph

    B->>B: Issue MembershipAttestation(alice, role:service:maintainer)
    A->>A: Sign RecognitionTreaty(subject=Sovereign B, scope=maintainer)
    B-->>A: Present attestation
    A->>A: Verify treaty signature, scope, status, subject key
    A->>A: Verify attestation signature against treaty subject key
    A-->>B: accepted

    A->>A: Revoke RecognitionTreaty
    B-->>A: Present same attestation again
    A-->>B: rejected: treaty_locally_revoked
    A->>G: Export sovereign nodes, recognition edges, revoked trust material
```

Static walkthrough:

```{image} assets/images/genesis-mesh-recognition-treaty.png
:alt: Recognition treaty flow showing accepted trust, revocation, and graph export
:class: screenshot
```

Animated execution:

```{image} assets/images/genesis-mesh-recognition-treaty.gif
:alt: Recognition treaty demo animation
:class: screenshot
```

## What This Proves

- Two sovereigns can run with separate genesis blocks, NA keys, operator keys,
  and SQLite databases.
- A treaty can scope which roles are accepted from the recognized sovereign.
- A membership attestation can be accepted through a treaty without adding a
  local recognition policy by hand.
- Revoking the treaty changes trust state immediately in the accepting
  sovereign.
- Minimal recognition graph export exists before a full Connectome UI.

## Run Locally

The demo is in-process and does not require Docker, DNS, or external services.
It creates both sovereigns in a temporary directory and cleans them up at exit.

```powershell
python docs\examples\assets\scripts\recognition-treaty-demo.py
```

Expected proof:

```text
==> Sovereign B issued membership attestation
    subject:     alice
    roles:       role:service:maintainer

==> Sovereign A issued recognition treaty for Sovereign B
    scope:  role:service:maintainer

==> Sovereign A accepted B's attestation through the treaty
    accepted: True
    reason:   accepted

==> Sovereign A revoked the recognition treaty
    reason: trust_boundary_removed

==> Sovereign A rejected the same attestation after treaty revocation
    accepted: False
    reason:   treaty_locally_revoked

==> Sovereign A exported minimal recognition graph
    sovereigns:              2
    recognition_edges:       1
    revoked_trust_material:  1
```

## Recognition Graph Export

The `/recognition-graph` endpoint returns the data needed by future Connectome
viewers:

- sovereign nodes
- direct recognition edges
- active treaty count
- revoked treaty and attestation material

The export is deliberately data-first. Any operator can render their own trust
graph without depending on a central Genesis Mesh viewer.

## Boundaries

v0.10.0 treats recognition treaties as the base primitive for direct
sovereign-to-sovereign recognition. Derived or transitive recognition is a
later overlay computed on top of the treaty graph with explicit depth limits.
Unbounded transitive trust is intentionally avoided because it can become a
supply-chain attack surface.
