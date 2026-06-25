# Genesis Mesh RFCs

This section holds the Genesis Mesh protocol RFCs. They turn implemented
protocol behavior into reviewable, implementable standards documents so a future
operator, implementer, standards reviewer, or investor can understand the
protocol without reverse-engineering the Python reference implementation.

The program goals, principles, template, and acceptance bar are described in
{doc}`/development/rfc-program`. The strategic context is in
{doc}`/development/phase-2-externalization`.

## Status of this batch

This is the first RFC batch. Every document is `Draft`. Each maps to behavior
already shipped in the Python reference implementation, and each cites the
modules that implement it. Draft status means the description is
implementation-informed and reviewable, not that the wording is frozen.

| RFC | Title | Status | Primary implementation |
| --- | --- | --- | --- |
| {doc}`RFC-001 <rfc-001-sovereign-identity>` | Sovereign Identity | Draft | `genesis_mesh/models/sovereign.py` |
| {doc}`RFC-002 <rfc-002-recognition-treaties>` | Recognition Treaties | Draft | `genesis_mesh/trust/treaty.py` |
| {doc}`RFC-003 <rfc-003-trust-bundles>` | Trust Bundles | Draft | `genesis_mesh/cli/trust_bundle.py` |
| {doc}`RFC-004 <rfc-004-revocation-feeds>` | Revocation Feeds | Draft | `genesis_mesh/trust/treaty.py` |
| {doc}`RFC-005 <rfc-005-capability-manifests>` | Capability Manifests | Draft | `genesis_mesh/models/discovery.py` |
| {doc}`RFC-006 <rfc-006-connectome-model>` | Connectome Model | Draft | `genesis_mesh/trust/connectome.py` |
| {doc}`RFC-007 <rfc-007-operator-continuity>` | Operator Continuity | Draft | `docs/operators/` |
| {doc}`RFC-008 <rfc-008-managed-operator-role>` | Managed Operator Role | Draft | `docs/development/governance.md` |

For the established standards and patterns each RFC generalizes — recorded as
design lineage, not as adoption claims — see {doc}`prior-art`.

## Normative language

The RFCs use **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** as
defined in RFC 2119 and RFC 8174. A normative requirement describes behavior an
interoperable implementation has to honor. Reference behavior describes how the
Python implementation happens to do it and MAY differ between implementations.

```{toctree}
:maxdepth: 1
:hidden:

rfc-001-sovereign-identity
rfc-002-recognition-treaties
rfc-003-trust-bundles
rfc-004-revocation-feeds
rfc-005-capability-manifests
rfc-006-connectome-model
rfc-007-operator-continuity
rfc-008-managed-operator-role
prior-art
```
