# Genesis Mesh Pre-1.0 Roadmap

This roadmap keeps Genesis Mesh on pre-1.0 minor versions until the trust model,
operator experience, deployment model, and migration story are stable enough for
a `1.0.0` production contract.

## Current Baseline

Genesis Mesh already has a strong Layer 1 foundation:

- signed genesis blocks
- Network Authority enrollment
- invite-token controlled joining
- Ed25519 identities and signed join certificates
- Noise XX encrypted peer sessions
- CRL enforcement
- peer discovery and routing
- capability discovery
- trust-aware capability orchestration
- provenance-aware agent examples
- container and documentation workflows

The next work should avoid adding more demos for their own sake. The next
architectural milestone is portable trust across sovereign communities.

## Next Target: v0.9.0 - Sovereign Trust and Membership Attestations

### Goal

Prove that trust can move from one sovereign community to another without
creating a new centralized platform authority.

### Founding Demo

```text
Genesis Core endorses a member.
AI Research Community recognizes Genesis Core.
The member joins AI Research through that recognition.
Genesis Core revokes the member.
AI Research automatically changes trust state.
```

For the first release, both sovereigns may be operated by the maintainer. The
demo should say this plainly. The protocol still proves the important property:
two separately configured trust domains, with separate genesis blocks, Network
Authority keys, operator keys, policies, and state, can evaluate portable trust.
A third-party operator should be able to replace the second sovereign without
protocol changes.

### Scope

- `Sovereign` or trust-domain model
- `MembershipAttestation` model
- role and status claims inside attestations
- attestation signature verification
- attestation expiry handling
- attestation revocation
- local policy for whether a sovereign accepts a recognized issuer
- documentation and demo showing portable trust

In `v0.9.0`, recognition policy is local configuration on the accepting
sovereign. `v0.10.0` promotes that policy into a signed `RecognitionTreaty` so
the recognition relationship itself becomes a portable on-network artifact.

### Out of Scope

- marketplace behavior
- payment or settlement
- reputation scoring
- global ranking
- public discovery of every sovereign
- complex governance UI

### Success Criteria

- A member endorsed by one sovereign can be evaluated by another sovereign.
- Acceptance depends on explicit recognition policy.
- Revocation by the issuing sovereign changes trust state in the accepting
  sovereign.
- Negative paths are tested: unknown issuer, expired attestation, revoked
  attestation, non-recognized sovereign, invalid signature.

## Follow-Up Target: v0.10.0 - Recognition Treaties

### Goal

Move from one-off recognized issuers to explicit community-to-community trust
relationships.

### Scope

- `RecognitionTreaty` model
- treaty issuer and subject sovereigns
- treaty scope
- treaty validity window
- treaty signature verification
- treaty revocation or suspension
- treaty-backed admission checks
- audit trail for treaty decisions
- minimal recognition graph export

The graph export is intentionally earlier than the full Connectome. It gives
operators and contributors a machine-readable way to see whether recognition
edges are forming before a dedicated visualization product exists.

The export is protocol data, not a central product surface. Connectome viewers
should be interchangeable so no single viewer becomes the authority over what
the network can see or rank.

### Success Criteria

- Sovereign A can publish a signed treaty recognizing Sovereign B.
- Sovereign A can accept selected attestations from Sovereign B based on treaty
  scope.
- Revoking or expiring the treaty prevents future trust decisions.
- Existing relationships remain explainable through audit and provenance.
- Operators can export sovereigns, recognition edges, active treaties, and
  revoked trust material as structured data.

## Follow-Up Target: v0.11.0 - Revocation Propagation Across Sovereigns

### Goal

Make trust withdrawal portable, not only trust creation.

### Scope

- federated revocation events
- revocation propagation between recognized sovereigns
- trust-state synchronization
- replay protection
- safe handling of stale revocation state
- operational logs that explain why trust changed

### Success Criteria

- A revocation issued by the original sovereign reaches recognizing
  sovereigns.
- Active trust decisions update automatically.
- Revoked attestations cannot be used for admission, renewal, or capability
  execution.
- Revocation logs include issuer, subject, reason, and affected trust path
  without leaking private payloads.

## Follow-Up Target: v0.12.0 - Connectome Visualization and Operator Workflows

### Goal

Make the recognition network visible and operable through a human-facing
Connectome.

### Scope

- recognition graph visualization
- trust path visualization
- active treaties
- revoked credentials
- affected communities
- capability overlays as a secondary view
- operator-facing troubleshooting output

### Success Criteria

- Operators can answer why a member or agent is trusted.
- Operators can see which sovereigns recognize each other.
- Operators can see the blast radius of a revocation.
- Capability providers can be viewed as an overlay on trust, not as the primary
  graph.
- The Connectome consumes the graph export introduced earlier instead of
  inventing a second source of truth.

## Parallel Operational Track

These items are required for serious adoption but should not distract from the
portable-trust roadmap.

The operational track is sequenced independently. High-availability Network
Authority support and structured telemetry should land before inviting an
external operator to run a sovereign. The enterprise IdP bridge can wait until
the first enterprise pilot needs it.

### High-Availability Network Authority

- stateless NA process
- shared durable trust state
- safe CRL and policy publication
- deployable active-active or active-standby pattern

### Enterprise IdP Bridge

This is a reactive enterprise track rather than a fixed community-roadmap
milestone. Build it when the first enterprise pilot needs existing identity
systems integrated with mesh enrollment.

- OIDC/SAML exchange path
- Entra ID and Okta-friendly enrollment
- mapping enterprise groups to mesh roles
- clear separation between enterprise identity and mesh trust

### Structured Telemetry

- JSON logs
- CloudEvents-compatible security events
- OpenTelemetry traces for control-plane and runtime decisions
- SIEM-ready audit output

### Onboarding

- fewer required flags
- clearer default config
- invite links or short enrollment commands
- time-to-first-working-mesh under five minutes

## Deferred Until Later

Do not prioritize these before portable trust works:

- billing
- settlement
- token systems
- capability marketplaces
- reputation scores
- semantic registries
- generic agent framework features
- long-running workflow engines
- broad MCP platform features

## 1.0 Gate

Do not call Genesis Mesh `1.0.0` until these are true:

- core trust models are stable
- sovereign and recognition primitives are implemented and documented
- revocation works across the trust boundary
- migration expectations are clear
- deployment hardening is credible
- HA and backup guidance exist
- security and audit behavior is tested
- operator workflows are simple enough for non-authors to run

The 1.0 question is not "does the demo work?"

The 1.0 question is:

> Can independent operators run sovereign trust domains, recognize each other,
> revoke trust, and explain every trust decision without relying on Genesis Core
> as a permanent central authority?
