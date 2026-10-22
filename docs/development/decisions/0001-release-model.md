# 0001: Release model: a pinned contract bundle, not lockstep

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

**Implemented:** not yet (2026-10-22). No contract bundle or compatibility table exists; the lockstep train in {doc}`../versioning` still applies. The bundle and the release model are Phase C of the plan, which is parked.

## Context

The six repositories released as one train: one version everywhere, SDK
and gateway tags allowed only behind the core's tag of the same version, and
conformance vectors byte-compared against core `main` through same-named
branches. Most SDK and gateway CI failures came from another repository; the
1.7.0 edge release needed its tag re-pointed; a gateway security patch waited a
day for a core release; half of the Go and .NET pull requests were empty
version bumps.

## Decision

- The core publishes a **versioned contract bundle** with each release:
  conformance vectors, the field and record-kind registry (with per-kind
  metadata), error codes, and a route manifest with request and response
  schemas (decision 0004 and the plan's Track 1). Every consumer pins a bundle
  version and checks against it, not against core `main`.
- A component's version is its own. While it shares the core's major
  version, its `major.minor` may not exceed the core's; patch releases need
  no core release, and nothing is released without a change.
- A component that takes a major version of its own (the Go and .NET 2.0s of
  decision 0002) leaves that ceiling and instead declares the range of
  contract bundles it supports; the compatibility table is the check.
- The Rust repository's verifier and edge agent get their own tag streams.
- The core publishes a generated compatibility table (latest released
  consumers against the current bundle), refreshed nightly.

## Consequences

Cross-repo work stops pairing branches by name; a consumer upgrades its
pinned bundle in its own pull request. Same-day release coordination remains
only for changes that need it.
