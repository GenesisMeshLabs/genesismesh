# v1.0.0 Plan: Stable Sovereign Trust for Independent Operators

## Purpose

`1.0.0` declares a stable, supported platform for an independently operated
pilot: a defined public contract with compatibility rules, tested upgrades and
recovery, a published security review, and a deployment profile an operator
can run with its own keys, infrastructure, policy and revocation. Semantic
Versioning ties 1.0.0 to a stable public API, not to every long-term goal
being demonstrated.

## Decision: 2026-10-02, the gate is re-scoped

The maintainer re-scoped this gate for an upcoming pilot. The second
independently implemented sovereign (Workstream 1) and the first external
operator proof (Workstream 2) are no longer conditions for tagging 1.0.0. They
are **expected outcomes of the pilot**: if the pilot operator controls its own
keys, infrastructure, policy and revocation, the pilot produces the
external-operator evidence.

1.0.0 must not claim them in advance. Public wording is "ready for an
independently operated pilot", never "independent federation proven in
production". Until the evidence exists, the documentation says that the
federation proofs are pending.

This plan implements the pre-1.0 gate in
[`docs/development/strategy.md`](../docs/development/strategy.md) and the
operator and interoperability criteria in
[`docs/development/externalization.md`](../docs/development/externalization.md).
It is a release plan, not evidence that any unchecked criterion is complete.

## Prerequisites and remaining gap

- **v0.60.0** must deliver the optional PostgreSQL high-availability mode,
  two-instance failover, database-enforced concurrency guarantees, migration,
  and a backup and restore drill. The default SQLite mode remains supported.
  See [`plan-v0.60.0.md`](plan-v0.60.0.md).
- **v0.61.0** must deliver its CI-enforced Python, Go, TypeScript, and C#
  artifact interoperability scenario, with local verification rather than
  forwarding verification to the Python Network Authority. See
  [`plan-v0.61.0.md`](plan-v0.61.0.md).
- **The v0.61 scenario alone is insufficient for v1.** Its Go leg verifies an
  agreement and boundary decision, but does not exchange a recognition treaty,
  validate a trust bundle, or consume a revocation feed with an independently
  implemented sovereign. Since the 2026-10-02 decision that proof is an
  expected pilot outcome rather than a 1.0.0 condition. Do not label an SDK
  calling a Python verification endpoint as an independent implementation.
- Neither prerequisite supplies a real external operator, a v1 wire-format
  compatibility contract, or the remaining governance deliverables. Those are
  explicit v1 work items below.

## Release meaning and boundaries

`1.0.0` means the core sovereign trust protocol, Network Authority, and
documented stable surfaces of the official SDKs can be used by independent
operators under stated support and migration rules. It does not mean that
every optional gate, cloud adapter, application, or ecosystem service is stable.

The first v1 release does not claim completion of all Phase 2 objectives.
Atlas and a native application may follow if they are described as separate
work and no v1 announcement claims that Phase 2 is complete. If the release is
marketed as Phase 2 completion, satisfy the Atlas and native-workflow criteria
in `docs/development/externalization.md` before tagging it.

Keep beta surfaces explicitly marked beta. In particular, do not imply that
the PeerRiskSignal model has a current formal proof while the documented
Tamarin gaps remain. Do not treat a documentation or SDK version bump as a
substitute for protocol evidence.

## Workstream 1: Independent trust and revocation (pilot outcome, not gated)

- [ ] Run a treaty-backed exchange between the Python reference sovereign and
      a second independently implemented sovereign. Go is the Phase 2 target.
      Both sides must control their own identity and trust decision; a Go HTTP
      client calling Python does not count as the second implementation.
- [ ] Exchange and validate public identity, a scoped recognition treaty, and
      a trust bundle without sharing private keys.
- [ ] Issue an attestation within the treaty scope. Verify acceptance from the
      other sovereign using the second implementation's own verification code.
- [ ] Revoke the attestation, publish and import a signed feed, then verify
      rejection of that same attestation. Test stale-feed and wrong-key failures.
- [ ] Add a reproducible CI scenario with signed fixture artifacts, negative
      cases, and a human-readable account of what each implementation proved.
      Keep the v0.61 agreement and data-intent scenario as a separate leg.

Acceptance evidence: a green CI run plus signed public artifacts, verifier
results, and a concise account of each sovereign's independent decisions.

## Workstream 2: External operator proof (pilot outcome, not gated)

- [ ] Complete one proof with an operator outside Genesis Core using
      [`docs/operators/external-operator-proof.md`](../docs/operators/external-operator-proof.md).
      The operator chooses the network, generates and keeps the keys, controls
      the database and infrastructure account, sets policy, and runs the
      endpoint. Record any help the maintainer provides.
- [ ] Demonstrate explicit treaty approval, acceptance before revocation, and
      rejection after the operator revokes and publishes a feed. The operator
      must retain control of the revocation decision.
- [ ] Preserve a redacted proof bundle, public key fingerprints, source
      artifacts, and an account of setup friction. Publish the operator's name
      only with permission; an anonymous evidence note is acceptable when
      control and results remain reviewable.
- [ ] Check that no proof step requires the operator to transfer a private key,
      cloud credential, database, or policy authority to Genesis Core.

Acceptance evidence: an independently operated sovereign and a reviewable
before-and-after trust record, not another maintainer-operated cloud instance.

## Workstream 3: Public contract and migrations

- [x] Review the CLI, Python API, Network Authority HTTP routes, signed models,
      export schemas, and each official SDK. Publish a v1 inventory identifying
      stable, beta, and internal surfaces, with a specific support statement
      for each package. Do not promise feature parity where SDKs differ.
- [x] Define compatibility rules for HTTP request and response fields, stable
      error codes, canonical signing bytes, signed-artifact schema versions,
      conformance vectors, and persisted database state. Update
      [`DEPRECATION_POLICY.md`](../DEPRECATION_POLICY.md), which currently
      excludes the wire protocol, so implementers know how a v1 reader handles
      old and new artifacts. Formal lemmas are not a migration policy.
- [x] Define the supported upgrade path from the latest supported 0.x release
      and from a populated v0.59.1 pilot database. Test migrations and restored
      backups with existing treaties, revocations, policies, and evidence.
      Document rollback limits where a new schema makes rollback unsafe.
- [x] Fix known TypeScript consensus declarations that disagree with Python's
      `JustificationProof`, `ValidatorVote`, and `ConsensusProof` models. Remove
      the `as never` casts from the consumer smoke app and compile it against
      the packed SDK. Add coverage for counteroffers and retention checkpoint
      creation and verification, which the current smoke run does not exercise.
- [x] Install published or release-candidate artifacts into clean consumers
      and run the cross-language contract tests against the same core version.

Acceptance evidence: a published compatibility matrix, migration tests,
conformance results, and clean consumer builds without type escape hatches.

## Workstream 4: Governance and security claims

- [ ] Complete the RFC decision process and dated decision log. Move the
      normative identity, treaty, trust-bundle, and revocation RFCs through
      review before claiming they define v1 interoperability. Other RFCs may
      remain Draft if the release labels them accordingly.
- [x] Publish the operator exit and fork note and the managing-partner control
      boundary described in
      [`docs/development/governance.md`](../docs/development/governance.md).
      Show how an operator can leave without surrendering its identity or
      requiring Genesis Core approval.
- [x] Review the current threat model, dependency reports, key handling,
      revocation freshness, replay protection, authorization failures, and
      recovery procedures against the v1 deployment profile. Resolve critical
      findings and document accepted residual risks before release.
- [x] Reconcile formal-verification claims with
      [`docs/examples/formal-verification.md`](../docs/examples/formal-verification.md).
      Repair and rerun any model cited as evidence for current v1 behavior;
      otherwise remove that claim and keep the unproved surface beta. Record
      which proof checks run in CI and which are manual.

Acceptance evidence: dated governance decisions, an operator exit procedure,
a documented security review, and claims that match the checks actually run.

## Workstream 5: Operational and release proof

- [x] Complete every v0.60 acceptance criterion on both SQLite and PostgreSQL.
      Verify two-instance failover under active decisions, revocations, and
      evidence submission with no lost or duplicate state.
- [x] Drill PostgreSQL backup and restore to a new instance, verify the
      restored database and trust state, and rehearse the documented migration
      and rollback paths. Record the outcome and any recovery limits.
- [ ] Run the core unit and integration suites, conformance suite, SDK suites,
      interoperation scenarios, Sphinx warnings-as-errors build, type checks,
      dependency audits, and package installation checks on the v1 release
      candidate. Run the external-operator proof against that candidate.
- [ ] Apply the coordinated release train in
      [`docs/development/versioning.md`](../docs/development/versioning.md):
      matching versions and tags, security support table, changelogs, docs,
      registry packages or clearly documented Git distribution, and deployment
      validation. Distinguish a package available from a registry from one
      available only from Git.
- [ ] Test a release candidate built from the intended `1.0.0` commit before
      publishing it. Record defects and compatibility changes, rerun affected
      evidence after fixes, and tag `1.0.0` only when the gates below are
      green. If a separately tagged prerelease is wanted, first add prerelease
      support to the version and release-train checks. Do not make a time-based
      soak period stand in for the independent trust or recovery proofs.

## Go or no-go gate

Do not tag `v1.0.0` unless all of the following are true:

1. v0.60 HA, migration, concurrency, and restore criteria have passing
   evidence, including a two-instance failure test and a PostgreSQL backup
   restored to a new instance.
2. The v0.61 cross-language tests and the published-artifact scenario pass on
   the release candidate.
3. The pilot deployment profile is documented and rehearsed: operator-held
   keys, the chosen database, backup and restore, readiness and failover if HA
   is used, and a recognition-to-revocation flow. Who responds to a pilot
   incident and ships a 1.0.1 is named.
4. Stable public and wire surfaces, beta exclusions, migration guarantees,
   and SDK support levels are documented and tested. Known TypeScript type
   mismatches are fixed.
5. Governance decisions, operator exit rights, security review, and current
   formal-verification claims are documented and internally consistent.
6. The release candidate passes the coordinated core, SDK, documentation,
   security, installation, and deployment gates on the exact commits to tag.

Any failed criterion blocks the v1 tag. The next 0.x release may still ship a
completed subset without changing the meaning of this gate.

Workstreams 1 and 2 are not gate conditions (see the 2026-10-02 decision). The
1.0.0 release notes list them as pending evidence expected from the pilot.
