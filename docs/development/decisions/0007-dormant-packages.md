# 0007: Dormant core packages are internal

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

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
