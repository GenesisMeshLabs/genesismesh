# Phase G -- Application Layer

**Versions**: v0.22.0 – v0.25.0
**Question**: Can the trust fabric be made legible to non-protocol buyers — through applications, demos, and a visible graph explorer?

## What Changed

Two independently-keyed Network Authorities recognized each other through
a signed treaty and propagated a revocation across that boundary,
demonstrating that the cross-sovereign mechanics work with genuinely
independent operators.

A fleet CLI gave operators managing many Network Authorities a dedicated
command surface: `fleet bootstrap`, `fleet status`, `fleet federate`,
`fleet revoke`. The edge-fleet example showed a multi-sovereign operational
scenario where nodes at different locations federate with a hub sovereign.

`TrustDecision` evaluated the recognition path between two sovereigns and
produced a structured verdict (`allow`, `warn`, `escalate`, `block`) with
reason codes. `TrustEvidence` packaged the verdict as a signed artifact —
the first Genesis Mesh record that makes a trust assertion portable and
offline-verifiable beyond the NA that produced it. A second sovereign can
verify the evidence without calling the first sovereign's NA.

The Trust Atlas made TrustEvidence records navigable: sovereigns as nodes,
recognition relationships as edges, treaty scope visible on hover,
TrustEvidence overlay showing verdict and digest binding. It exists as a
live console page and as a static snapshot. It does not rank sovereigns;
it surfaces what the signed protocol state already says.

## Value Added

- The trust fabric is useful to people who do not read RFCs.
- Trust decisions are portable, signed, and offline-verifiable — they
  can be shared between parties without a live NA call.
- A fleet of independently-keyed sovereigns can be managed through a
  single CLI surface.
- The recognition graph is navigable visually through the Atlas.

## What Became Possible

With a legible application layer and portable trust evidence, the full
trust architecture could be built. Phase H constructed the complete
pipeline from relationship agreement through execution evidence with
machine-checked security properties.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.22.0 | Cross-sovereign pattern demonstration: two independently-keyed NAs |
| v0.23.0 | Fleet Operations CLI: bootstrap, status, federate, revoke; edge-fleet example |
| v0.24.0 | TrustDecision + TrustEvidence: signed, offline-verifiable trust assertions |
| v0.25.0 | Trust Atlas MVP: live graph explorer and static snapshot |
