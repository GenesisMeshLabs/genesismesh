# Plan v1.7.0 — Governed Changes and Edge Trust, Stage 6: The Edge Agent

Stage 6, the last of the program in `plan-v1.2.0.md`, confirmed or deferred
when Stage 4 ships (Decision 5 there). A small Rust agent,
`genesis-mesh-edge`, runs as a Genesis Mesh node on constrained devices,
enforces decisions and grants for local services, records evidence that
survives disconnection, and uploads it in order when the NA returns.

## Context

After Stage 5 grants exist in the core and the SDKs, and the Rust SDK
verifies every record of the program (Stage 4). A device still needs a
runtime: an identity, enrolment and renewal, a fresh trust snapshot, a local
enforcement point, and a durable outbox. `docs/examples/edge-fleet.md` already
describes edge fleets; this stage makes the agent real.

The reviews found:
- a node's join-certificate identity and an executor key are separate today,
  and executor keys are registered through a privileged admin route;
- asking for a decision when connected means `/admin/boundary/evaluate`, which
  needs a standard-tier operator key; with that key a device could request
  decisions under any attestation and call every other standard route;
- the gateway's `genesis-mesh` binary links everything the gateway does
  (aws-lc, ring, bundled SQLite, tokio, redis), and `federation.rs` mixes
  verification with fetching, which is a risk for small static builds.

## Scope

### In scope

1. **Rust foundations, only as the agent needs them**: the agent depends on
   the Rust SDK's verification (Stage 4) and the node protocol, with no
   network, async or database dependency in the verification layer (checked
   by `cargo tree` in CI); `federation.rs` verification separated from
   fetching if the agent uses it. A musl arm64 build runs in CI from this
   stage's start.
2. **Node-scoped decisions**: `POST /node/boundary/evaluate`, authenticated by
   the node certificate, with the requester bound to the node's sovereign and
   the basis limited to attestations issued to that node; no operator key on
   the device.
3. **Agent** `genesis-mesh-edge`:
   - node runtime: identity, `join`, `heartbeat`, `renew` with the existing
     node protocol;
   - device keys: the executor key is generated on the device and registered
     at join by the node's own signature; revoking the node retires its
     executor key and its grants;
   - trust snapshot: pinned authority keys, CRL, revocation feeds, treaties,
     grants and the latest NA-signed time token, with freshness limits;
   - enforcement: a local API on a Unix socket with peer credentials (or a
     per-service token on loopback where sockets are unavailable): "may I do X
     with these parameters?" answered by a node-scoped NA decision when
     connected, a grant check when not, and break-glass (Stage 2) when neither
     is available and the local service supplies a justification; a stale
     snapshot stops grant use beyond its bounds and falls back to break-glass,
     never to silent refusal of an urgent change;
   - evidence: execution, grant, break-glass and observation records signed by
     the device key, kept in a durable local outbox (SQLite), uploaded in
     order on reconnect; refused records are quarantined by the NA.
4. **Footprint**: release builds for Linux arm64 and x86-64 (musl); armv7 when
   a user needs it; binary size and resident memory measured in CI each
   release against budgets recorded here at release.
5. **Packaging**: a systemd unit and a signed container image (beta, by
   digest); configuration by file and environment.
6. **Console**: edge nodes in the mesh view (last seen, snapshot age, pending
   uploads, grants in use, break-glass uses).
7. **Docs**: extend `docs/examples/edge-fleet.md` with the agent; an
   operations page *Edge agent* (deploy, grants, break-glass, offline
   behaviour, freshness limits, recovery) in the sub-index.

### Out of scope

- An authority on the edge (a Rust NA, deferred).
- Policy evaluation on the device.

## Security notes

- No operator key lives on a device; the node-scoped route can decide only for
  the node itself.
- The local API is authenticated; tests prove an unauthenticated local process
  is refused.
- The device key is stored with file permissions or a platform key store,
  never logged; revocation of the node retires it.
- A stale snapshot stops grant use beyond its bounds; what proceeds after that
  is break-glass, recorded and judged.

## Success Criteria

- [ ] The agent enrols, registers its executor key at join, renews, and is
      revoked with its key and grants in one step
- [ ] A node-scoped decision is refused for another sovereign's request or a
      foreign attestation; the device holds no operator key
- [ ] With the NA stopped for two hours: N in-grant actions succeed through the
      local API; an out-of-envelope action is refused locally; an urgent
      action with a justification proceeds as break-glass; on reconnect every
      record uploads in order within T, refused ones quarantined (N and T set
      in the test)
- [ ] An unauthenticated local client is refused
- [ ] Size and memory on arm64 and x86-64 are measured in CI and within the
      recorded budgets
- [ ] The console shows edge nodes; node tests cover the view

## Release Gate

- [ ] Stage 5 (1.6.0) released; this stage confirmed (Decision 5 of
      `plan-v1.2.0.md`)
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.7.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md` closed for the program
- [ ] `SECURITY.md`: 1.7.x supported, 1.6.x upgrade to 1.7; the edge agent
      covered
- [ ] Public contract: the node routes and the agent classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.7.0`, releases, published-artifacts green
      (including the agent)
- [ ] `"1.7.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded

## Decisions

Open, for the Maintainer:

1. **Agent image beta** (proposed) until a release after 1.7.0 proves it in a
   deployment.
2. **Executor key registered at join** (proposed), by the node's own
   signature, instead of a privileged admin call per device.
3. **A node-scoped evaluate route** (proposed, after review) instead of
   operator keys on devices.
