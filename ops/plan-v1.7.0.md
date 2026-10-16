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

### Candidates carried from Stage 5 (deferred out of 1.7.0, Decision 17)

- **Inclusion proofs for an audit pack's cited entries** (the Stage 4
  candidate, deferred from 1.6.0, and again from 1.7.0: moved to
  `roadmap.md` as a post-program item when `phase-n.md` closes). A pack's cited entries are tied to the
  store only by the packs an auditor verified before (`audit verify --prior`)
  or an anchor at their exact position (warning `cited_entry_unanchored`
  otherwise). Anchors over a Merkle tree of the store (a root in each anchor,
  an inclusion proof per cited entry, pack format version 2) would prove each
  cited entry against the held anchors alone. It changes `StoreAnchor`, a
  stable signed artifact, so it needs a new anchor version alongside the
  current one. Since 1.6.0 a pack also cites grants, grant uses and
  revocations, which the proofs would cover the same way.

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

- [x] The agent enrols, registers its executor key at join, renews, and is
      revoked with its key and grants in one step (`test_edge_nodes.py`;
      sdk-rust `edge/tests/scenario.rs` `lifecycle`)
- [x] A node-scoped decision is refused for another sovereign's request or a
      foreign attestation; the device holds no operator key
      (`test_node_routes.py`; the scenarios assert no admin header reaches the
      NA, and the agent's clippy configuration refuses admin signing)
- [x] With the NA stopped for two hours: N in-grant actions succeed through the
      local API; an out-of-envelope action is refused locally; an urgent
      action with a justification proceeds as break-glass; on reconnect every
      record uploads in order within T, refused ones quarantined (N and T set
      in the test: N = 8, T = 120 s). The soak on sdk-rust's release pull
      request ran 7,207 s with the NA stopped and passed, at 6,804 KiB
      resident (x86-64); every pull request runs the same scenario for 120 s
      on both architectures
- [x] An unauthenticated local client is refused (scenario `local_auth`)
- [x] Size and memory on arm64 and x86-64 are measured in CI and within the
      recorded budgets (`edge/footprint-budgets.json`: 12 MiB binary, 32 MiB
      resident). Measured on main at the merge: x86-64 binary 7,244,896 bytes,
      6,536 KiB over the 120-second offline run and 22,412 KiB with a
      2,000-record backlog; arm64 6,179,968 bytes, 5,896 KiB and 21,500 KiB
- [x] The console shows edge nodes; node tests cover the view (gateway
      `tools/test_ui_edge.mjs`, `tests/production.rs`)

## Release Gate

- [x] Stage 5 (1.6.0) released; this stage confirmed (the Maintainer's
      standing instruction to proceed with the next plan once 1.6.0 was
      green, 2026-10-14; Decision 5 of `plan-v1.2.0.md`)
- [x] Maintainer decisions recorded (2026-10-16: 1-48)
- [x] Version bumped to `1.7.0` across the release train; `docs/sdk/index.md`
- [x] CHANGELOG entries, `history.md`, `phase-n.md` closed for the program
- [x] `SECURITY.md`: 1.7.x supported, 1.6.x upgrade to 1.7; the edge agent
      covered
- [x] Public contract: the node routes and the agent classified
- [x] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [x] Merge order: the Rust SDK (`sdk-rust`), then core, then the gateway
      (Decision 16): core after re-running interop with all four SDK
      repositories on `feat/edge-agent`, the gateway right after core
- [x] Dry runs green; tags `v1.7.0`, releases, published-artifacts green
      (including the agent; 2026-10-16). The sdk-rust tag's edge release job
      failed on a path before it signed or published anything; with the
      Maintainer's approval the tag was re-pointed to the fix (sdk-rust #45,
      the workflow only), with the immutable-tag rule disabled for that push
      and enabled again
- [x] `"1.7.0"` added to the `upgrade.yml` matrix after the release
- [x] Both production hosts upgraded (2026-10-15). On the demo NA a test
      agent (the released image) enrolled with a recipient-bound edge
      invite, got an ALLOW and a final DENY, was revoked with its key in one
      step and reached state revoked; a pack of the whole store verified
      with the released `genesis-mesh-verify` 1.7.0. The read-only
      reference on Azure verifies its public records

## Decisions

1. **Agent image beta** until a release after 1.7.0 proves it in a
   deployment (taken as proposed, 2026-10-14; confirmed by the Maintainer, 2026-10-16; Decision 14).
2. **Executor key registered at join**, by the node's own signature, instead
   of a privileged admin call per device (taken as proposed, 2026-10-14; confirmed by the Maintainer, 2026-10-16;
   Decision 8).
3. **A node-scoped evaluate route** instead of operator keys on devices
   (taken as proposed, 2026-10-14; confirmed by the Maintainer, 2026-10-16; Decision 6).

From the implementation contract (2026-10-14). Each was taken as proposed,
2026-10-14, and confirmed by the Maintainer, 2026-10-16, except where it says
otherwise.

### The agent and the SDK

4. **The agent is the workspace member `sdk-rust/edge/`**: package and binary
   `genesis-mesh-edge`, `publish = false`, the SDK's version, released by the
   `sdk-rust` `v*` tag like the verifier.
5. **A default `client` feature in the Rust SDK** gates `reqwest`,
   `percent-encoding`, every HTTP client, governance, the grant holder and the
   error variants that wrap `reqwest`; the verifier depends on the SDK with
   `default-features = false`, and CI checks with `cargo tree` that neither
   pulls in an HTTP, async or database stack.

### The NA surface

6. **Node-scoped routes**: `POST /node/boundary/evaluate` (Decision 3), and
   two beyond the plan, `POST /node/state` (the attestations and grants
   issued to the node, which a device cannot otherwise read) and
   `POST /node/evidence/resource-head` (a device cannot read resource heads
   through the admin route). Operators get `GET /admin/edge-nodes` (read
   tier). All beta.
7. **Edge invites need the privileged tier**: `/admin/invite` with
   `node_sovereign_id` and `executor_resource_prefix`, since redeeming one
   registers an executor key, a privileged act. At most one active edge node
   per sovereign ID.
8. **The executor key is registered at `/join`**: the node key signs the
   request and the executor key co-signs it as proof of possession; its ID is
   `edge-` and the first 32 hex digits of SHA-256 of the raw key
   (Decision 2).
9. **Revoking an edge node** revokes all its unrevoked certificates in one
   CRL, retires its executor key and so revokes its grants, with the existing
   reason `bearer_key_retired`: no new reason code, no signed-enum or
   verifier change.

### Verification and the decision order on the device

10. **`GovernedVerification.any_bound_policies`** (Rust SDK, default
    `false`): when set, a decision's policy binding is not compared with
    `expected_policies`; the agent sets it and still checks the NA's
    signature, the context binding and the attestation binding. It breaks
    struct literals that list every field; the SDK is beta.
11. **Decision order**: the NA decides when connected, a grant when not,
    break-glass covers the rest. A request a held grant names but does not
    cover is refused locally even with a justification, as the 1.6 SDKs
    never fall back for a request the grant does not cover. Break-glass is
    allowed when no held grant names the capability, the covering grant has
    ended, is spent or revoked, or the snapshot is stale.
12. **Treaties are left out of the snapshot**: nothing on the device reads
    them (no policy evaluation, no peer verification on the device).

### Console, release and merge order

13. **The console is the gateway console's operator view**
    (`edge-list-edge-nodes`), not the public mesh view, which is anonymous;
    the mesh view is unchanged.
14. **The agent and its image are beta** (Decision 1): the image is signed by
    digest and tagged `X.Y.Z` only, with no `X.Y` or `latest` while beta.
15. **The two-hour scenario runs in real time**, weekly and on release pull
    requests (`edge-soak.yml`); a 120-second version of the same scenario
    runs on every pull request on both architectures and doubles as the
    footprint measurement.
16. **Merge order: `sdk-rust`, then core, then the gateway**, as for 1.6.0:
    the SDK first (its live tests skip when the core lacks `/node/state`),
    core after interop runs with all four SDK repositories on
    `feat/edge-agent`, the gateway right after core, whose catalog check
    needs the core's routes. `feat/edge-agent` is also pushed, unchanged, to
    `sdk-go`, `sdk-typescript` (with the fix in Decision 23) and `sdk-dotnet`
    so interop pairs the branches. The gate line above is amended.

### Deferred

17. **Merkle inclusion proofs** (the Stage 5 candidate) are deferred out of
    1.7.0: they change `StoreAnchor`, a stable signed artifact (a second
    anchor version, verifiers updated first in three languages, a setting off
    by default, pack format 2 and a new frozen fixture), share no code with
    the agent, and the gap has workarounds (`audit verify --prior`, anchors
    at the cited position) and a named warning.
18. **Private-CA Network Authorities: deferred** (coordinator, 2026-10-14). No
    `ClientOptions::with_root_certificates` and no `authority.ca_file` in
    1.7.0; a deferred candidate.

### The agent's behaviour and keys

19. **An outcome not reported** within `report_timeout_seconds` is recorded
    as `outcome: "failure"`, with a detail saying it was not reported.
20. **Device keys are files** protected by permissions; platform key stores
    (TPM, PKCS#11) are deferred; armv7 is not built.
21. **No new switch on the NA**: the edge surface stays inert until an
    operator creates an edge invite; the only new settings are the two rate
    limits of the `/node/*` routes. Edge invites need `EVIDENCE_STORE=on` and
    `EVIDENCE_OUT_OF_BAND=on`; grants also need `EVIDENCE_GRANTS=on`, without
    which the agent works with decisions and break-glass only.

### Coordinator (2026-10-14)

22. **Revoking an edge node does not revoke its attestations**: retiring its
    key already revokes its grants, and the node can no longer authenticate.
23. **Grant budgets count quarantined uses only until the NA answers** (from
    the 1.6.0 live smoke): the Rust and TypeScript grant holders count every
    place of the use chain against `max_uses` while offline, the safe bound,
    and stop counting a use once the NA has answered it as quarantined; the
    chain position is still consumed (1.6 Decision 18). A use quarantined as
    `grant_budget_exhausted` keeps counting (review fixes).

### Review fixes (taken as proposed, 2026-10-14; confirmed by the Maintainer, 2026-10-16)

From the critic's and the skeptic's reviews of the branch.

The NA:

24. **A revoked edge node holds no valid certificate.** After retiring the
    node, the revocation re-lists its certificates and revokes any a renewal
    issued meanwhile; `/renew` and `/heartbeat` refuse a revoked node's key
    (`403 edge_node_retired`), a renewal that issued after the node was
    retired revokes its own certificate, and the start-up check revokes what a
    revoked node still holds.
25. **Enrolment is one write.** The executor key and the edge node are written
    in one transaction; what follows (audit events, the registry record) is
    best effort. A failure after the invite was consumed spends it. `/join`
    also needs out-of-band recording (`409 edge_requires_evidence_store`).
26. **An edge node's key is retired only with the node**: the generic retire
    route refuses it (`409 executor_key_is_edge_node`, a new code), and a node
    whose key is retired otherwise is refused at the `/node/*` routes.
27. **Delimited, disjoint prefixes**: an edge invite's prefix ends with `/` or
    `:` and overlaps no active executor key's or outstanding edge invite's
    prefix (`409 resource_prefix_overlap`, a new code). Keys without a prefix
    are not compared.
28. **An edge sovereign ID is no one else's**: not the NA's network name, an
    active executor key's, or an attestation subject's, unless it was a
    revoked edge node's (Decision 22); the console counts only the break-glass
    records the node's own key signed.
29. **Edge invites**: one outstanding per sovereign ID, one hour by default,
    and documented bound to the node key `genesis-mesh-edge init` prints.
30. **A limit per executor key** (`NA_RATE_LIMIT_EXECUTOR_PER_MINUTE`, 120) on
    break-glass records, observations (a batch counts once per key) and grant
    uses, counted once the signature verifies. It also applies to controllers
    and observers that are not edge nodes.
31. **No audit write before a signature**: a request naming a revoked
    certificate is audited only when the node key signed it.

The agent (sdk-rust):

32. **An NA that answers is obeyed**: any HTTP error from the NA, `429`
    included, is `na_refused`, never grants or break-glass; only
    connection-level failures count as offline. A local rate limit on
    `/v1/authorize`.
33. **A stale snapshot keeps the envelope**: a request a held grant names but
    does not cover is refused when the snapshot is stale too.
34. **A retired executor key means revoked**; a clock behind the snapshot
    makes it stale (`clock_behind`); `enroll` refuses non-loopback plain
    HTTP; `genesis-mesh-edge init` prints the node key.
35. **Footprint budgets are fixed targets** (binary 12 MiB, RSS 32 MiB), with
    the measured values recorded beside them, and a variant of the offline
    scenario in which the NA accepts connections and never answers.

Left open by the Maintainer at release (2026-10-16; from the skeptic's review):

- Is break-glass after an NA rate limit or `5xx` ever acceptable for devices?
  (Decision 32 says no.)
- When an operator revokes a grant, should the device be able to break glass
  for the same capability (Decision 11)?
- Do Decisions 12 and 22 hold when a sovereign ID is reused? Should edge
  attestations require `subject_public_key`?
- Is deferring private-CA support (Decision 18) acceptable for factory and
  site NAs, which it pushes towards plain HTTP for `run`?
- Should records that arrive after their key was retired, but are dated
  before it, be quarantined with a code of their own, so a reviewer can tell
  a legitimate backlog from forgeries?
- Are the fixed footprint targets (Decision 35) the right ones?

### Second review fixes (taken as proposed, 2026-10-14; confirmed by the Maintainer, 2026-10-16)

The agent (sdk-rust):

36. **Three answer classes** (revises Decision 32). An NA decision, or an NA
    error with its JSON error body and a `4xx` other than `429`, is an answer:
    final, no grant, no break-glass. An NA JSON error with `429` or `5xx`
    means the NA is throttled or failing: grants may be used, never
    break-glass. A connection failure, a timeout, or a `502`, `503`, `504` or
    `520`–`527` without the NA's JSON body (a proxy's page) means
    unreachable: grants, then break-glass with a justification. `/v1/status`
    reports `na_state` and `last_na_error`.
37. **The local API cannot be taken down**: accept errors never end the
    loop, a 10-second header timeout, at most 64 connections; exit code 2 is
    for configuration only.
38. **systemd**: `@chown` allowed for `socket_group`; the invite token
    credential falls back to an empty one, so the file may be removed after
    enrolment.
39. **No decision after SIGTERM**, and none for a client that disconnected
    before its answer.
40. **An expired certificate**: break-glass names the closest existing
    `evaluation_failure` (the record format has no value for it), the agent
    keeps trying to renew, and the docs give the recovery path.
41. **Holders are rebuilt from the uses already made**, never from use 0; a
    live grant that does not cover a request wins over an ended one
    (`outside_grant`), with table-driven tests of the decision.
42. **The device clock must be within five minutes of the NA's**; uploads run
    even when the node state cannot be read; `node_auth_failed` is shown;
    with `clock_behind` a grant that looks not yet valid counts as ended; the
    NA's heartbeat answers outrank the device's view of its certificate's
    expiry.
43. **Large backlogs**: counts and flushes page through the outbox, old
    authorizations are pruned, `outbox export [--dead-letters]` reads the
    backlog, and a scenario with thousands of records measures memory.
44. **Runbook**: `reset` (refuses while uploads are pending without
    `--discard-pending`, and while `run` holds the state lock), then `init`,
    a bound invite and `enroll`; `enroll` reads
    `/etc/genesis-mesh-edge/invite-token`; the agent refuses to start when its
    enrolment names another NA, or when its state is newer than it.
45. **Smaller fixes**: bounded configuration durations, `Retry-After` on
    uploads, a group- or world-writable state directory refused (exit 6), the
    local limit at 30 requests a minute, a pinned image builder, and the soak
    on x86_64 only for release pull requests (weekly unchanged).

The gateway console:

46. **Error texts** for the new codes, and the edge nodes table shows the
    certificate (and when it expired), the executor key and the resource
    prefix.

The core (documentation only):

47. **Grants after enrolment, re-enrolment with `reset`**: the edge example
    issues grants once the executor key exists, and its runbooks stop the
    agent after the backlog drained before revoking it.
48. **Rate-limit tests freeze the window** on PostgreSQL: the
    `DatabaseRateLimiter` counts in clock-aligned minutes, and a test whose
    requests straddled a minute boundary saw its count reset
    (`test_a_revoked_key_counts_like_an_unknown_one`, reproduced with a clock
    that crosses the boundary).

Also left open (second review):

- Renewing an expired certificate while keeping its executor key, so an
  expired device need not re-enrol (deferred).
- Time derived from the NA (signed times) rather than the device clock for
  freshness and grant validity (deferred).
