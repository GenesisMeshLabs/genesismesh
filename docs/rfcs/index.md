# Genesis Mesh RFCs

This section holds the Genesis Mesh protocol RFCs. They turn implemented
protocol behavior into reviewable, implementable standards documents so a future
operator, implementer, standards reviewer, or investor can understand the
protocol without reverse-engineering the Python reference implementation.

The program goals, principles, template, and acceptance bar are described in
{doc}`/development/rfc-program`. The strategic context is in
{doc}`/development/externalization`.

## Status of this batch

This is the first RFC batch. RFC-001 to RFC-006 map to behavior shipped in
the Python reference implementation and cite the modules that implement it.
RFC-007 and RFC-008 describe operator obligations and roles; parts of them
have no implementation yet.

RFC-001 to RFC-004, the normative RFCs for v1 interoperability, are
`Accepted` (2026-10-03): checked against the implementation, through operator
and security review, and frozen under `DEPRECATION_POLICY.md`. The others are
`Draft`: reviewable, not frozen. Decisions are recorded in {doc}`/development/rfc-decisions`.

Changes since acceptance are marked in each RFC with the release that made
them: the 1.2.0 canonical-form rules and the unknown-field rule (RFC-001), key
succession for the NA key (1.5.0; RFC-001, RFC-002, RFC-007) and the optional
`revoked_grant_ids` feed field (1.6.0; RFC-004). Dated implementation notes
mark where the reference implementation differs from an RFC: the identity
document the NA publishes (RFC-001) and multi-hop paths in trust decisions
(RFC-002, RFC-006).

| RFC | Title | Status | Primary implementation |
| --- | --- | --- | --- |
| {doc}`RFC-001 <rfc-001-sovereign-identity>` | Sovereign Identity | Accepted | `genesis_mesh/models/sovereign.py`; `GET /sovereign.json` in `genesis_mesh/na_service/routes/public.py` |
| {doc}`RFC-002 <rfc-002-recognition-treaties>` | Recognition Treaties | Accepted | `genesis_mesh/trust/treaty.py` |
| {doc}`RFC-003 <rfc-003-trust-bundles>` | Trust Bundles | Accepted | `genesis_mesh/workflows/trust_bundle.py` |
| {doc}`RFC-004 <rfc-004-revocation-feeds>` | Revocation Feeds | Accepted | `genesis_mesh/trust/treaty.py` |
| {doc}`RFC-005 <rfc-005-capability-manifests>` | Capability Manifests | Draft | `genesis_mesh/models/discovery.py` |
| {doc}`RFC-006 <rfc-006-connectome-model>` | Connectome Model | Draft | `genesis_mesh/trust/connectome.py` |
| {doc}`RFC-007 <rfc-007-operator-continuity>` | Operator Continuity | Draft | Operator guidance in `docs/operators/`; `genesis-mesh na doctor` |
| {doc}`RFC-008 <rfc-008-managed-operator-role>` | Managed Operator Role | Draft | `NA_DEPLOYMENT=managed`, `genesis-mesh managed`; {doc}`/operators/managing-partner-boundary` |

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
