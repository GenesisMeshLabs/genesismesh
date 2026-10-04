# Plan v0.65.0 — Mesh Demo Experience

## Context

v0.64 put the gateway online at mesh.genesismesh.org in front of a live NA
(network `genesis-mesh`, on the DigitalOcean droplet). A visitor without a
token sees the operation list and nothing else: no networks, no data, no way
to try anything. The read-only public reference on Azure (`gm-demo-public-na`,
ten demo sovereigns, nine treaties) is a separate site with no link to it.
This release makes the gateway a place to explore the mesh: demo access that
needs no credentials, several networks behind one console, a real treaty
between the live NA and the Azure reference, and guided scenarios that show
recognition, verification and revocation end to end.

## Scope

### In scope

- **Demo access (gateway).** A policy may mark one client per network
  `demo: true`. Its token is published at `GET /v1/demo` and offered by the
  console as **Try the demo**. Policy validation refuses demo clients with
  `authority_admin`, metrics, or groups outside an allowlist (public reads and
  verification routes), and caps their quota. Demo tokens can only do what an
  anonymous verifier could.
- **Several networks in one console (gateway).**
  - `genesis-mesh`: the live NA on the droplet (full catalog for real
    clients; public reads and verification for demo access).
  - `gm-demo-public-na`: the Azure reference, read-only: genesis, sovereign,
    treaties, revocation feeds, connectome and atlas. The reference gains a
    signed CRL in its snapshot (core) so the gateway can pin and refresh it
    like any other authority.
- **A real treaty.** The live NA recognizes `gm-demo-public-na` (operator
  signed, scoped to `role:demo`) and imports its signed revocation feed. The
  Azure reference's maintenance tooling signs the reverse treaty, so both
  connectomes show the link. Demo-network memberships are published to the
  gateway's public mesh view (`public_mesh: true`).
- **Guided scenarios (gateway console).** Cards that run with demo access and
  explain each result:
  1. Explore the mesh: networks, sovereigns, treaties and feed freshness,
     with the live graph.
  2. Verify a treaty from the Azure reference against its pinned key, then
     see a tampered copy rejected with the exact reason code.
  3. Cross-sovereign trust: a current demo membership is accepted, a revoked
     one is refused and listed in the signed revocation feed, and the
     reference's treaty accepts a member of the live NA.
  4. Evidence: a governed-action chain on the live NA (a demo secret
     rotating on a schedule), its resource head, and offline verification
     of the export in the browser.
- **Scheduled demo activity (droplet).** A small job issues and revokes demo
  attestations and runs governed actions with a dedicated executor key, so
  scenarios 3 and 4 always have fresh data. Issuing and revoking attestations
  and importing feeds need the privileged tier, so the job uses its own
  privileged `demo-ops` key, separate from the maintainer's key and revocable.
- **Operations.** The droplet stack (`infrastructure/mesh-demo/`): NA,
  gateway, demo job and Caddy, with backup, upgrade and reset notes. The
  console links to the Azure reference and the docs.

### Out of scope

- Public write access of any kind. Demo access never issues, revokes, signs
  or publishes; the demo job does that with keys that stay on the droplet.
- World Lab hosting.
- Multi-region or HA for the demo stack.

## Security notes

- A demo token is public by design. Its safety comes from policy validation
  (read and verify groups only, no admin forwarding, low quota), enforced by
  the gateway at startup, not by keeping the token secret.
- Operator and root keys for `genesis-mesh` stay off the droplet except the
  NA signing key and the demo job's `demo-ops` operator key and executor key.
- The Azure reference stays keyless; its CRL and the reverse treaty are signed
  by its offline maintenance process.

## Success Criteria

- [x] `GET /v1/demo` and **Try the demo** work; a policy with an unsafe demo
      client is refused at startup; tested
- [x] The console shows both networks; the Azure reference is pinned with its
      signed CRL and refreshed; tested
- [x] Treaty in both directions, verified by both sovereigns; revocation feed
      imported and fresh
- [x] The four scenarios run end to end with demo access on
      mesh.genesismesh.org
- [x] Demo job keeps fresh data; gateway stays ready across CRL refreshes
- [x] Documentation: gateway demo access, mesh-demo deployment, scenarios

Verified on mesh.genesismesh.org after release (2026-10-04): both networks
ready behind gateway 0.65.0; treaties in both directions (`genesis-mesh`
recognizes `gm-demo-public-na`; the reference's external treaty recognizes
`genesis-mesh`); the reference's revocation feed imported and current; all
four guided scenarios pass with demo access. The reference does not yet import
`genesis-mesh`'s feed, which the mesh view reports as "not imported".

## Release Gate

- [x] Version bumped to `0.65.0` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass (core SQLite and PostgreSQL, SDK suites, gateway, interop)
- [x] Tag `v0.65.0`, push, GitHub release created
