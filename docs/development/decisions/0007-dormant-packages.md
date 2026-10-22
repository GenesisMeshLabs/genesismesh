# 0007: Dormant core packages are internal

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

**Implemented:** in part (2026-10-22). The module map in {doc}`../architecture` marks the packages dormant. The public contract marks them internal only by omission (unlisted symbols are internal); see the note below.

## Context

`gossip`, `routing`, `transport`, `monitoring` and `node` (about 7k
lines) have had little or no change since September, but are part of the
package any contributor reads first.

## Decision

- Mark them **internal** in the public contract and the module map, with
  a note that new work does not build on them without a decision. Nothing is
  moved or removed now.

## Consequences

Contributors know where not to extend; removal can be decided later with
evidence.

## Correction (2026-10-22)

- "Little or no change since September" was not exact: 1.5.0 (2026-10-14)
  changed `node/node.py`, `node/runtime.py` and `node/peer_identity.py` so
  that nodes read the NA's key history and check certificates, policies and
  CRLs at their issue time (key succession).
- The packages are not listed in `contract/public-surface.json`, so they are
  internal only by the general rule that unlisted symbols are internal. But
  stable surfaces run them: the `genesis-mesh join` and `dev up` commands and
  the container image's `SERVICE_ROLE=node`. "Dormant" therefore means no new
  features. A change that breaks those surfaces is still a breaking change.
