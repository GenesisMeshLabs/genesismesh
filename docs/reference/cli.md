# CLI Reference

Genesis Mesh installs a single primary command:

```bash
genesis-mesh --help
genesis-mesh --version   # prints "genesis-mesh X.Y.Z" (v1.0.2)
```

The command is intentionally persona-oriented instead of file-oriented. Operator
commands manage the Network Authority and admin actions, node commands join and
inspect the mesh, and developer commands run local verification workflows.

Compatibility entry points such as `python -m genesis_mesh.cli` and
`python -m genesis_mesh.node` still exist for direct module execution, but
documentation and day-to-day workflows should prefer `genesis-mesh`.

Each command is **stable** or **beta**, as {doc}`public-contract` lists. A
beta command may change in a minor release; the command pages mark each one.
Commands that talk to a Network Authority depend on its settings: the
evidence store, out-of-band records, remediation and grants are off by
default ({doc}`configuration`), and the commands that need them say so.

## Operators

| Page | Commands |
|---|---|
| {doc}`cli/network-authority` | `init`, `na start`, `keygen`, `admin`, `na migrate-db`, `na verify-db`, `managed`, `genesis`, `info` |
| {doc}`cli/evidence-audit` | `evidence`, `audit`, `na succession`, `na doctor` |
| {doc}`cli/federation` | `sovereign`, `federation`, `fleet`, `trust-bundle`, `treaty`, `attestation`, `proof`, `supply-chain` |

```{toctree}
:hidden:
:caption: Operators

cli/network-authority
cli/evidence-audit
cli/federation
```

## Nodes and Developers

| Page | Commands |
|---|---|
| {doc}`cli/nodes` | `join`, `status`, `discover`, `send`, `dev` |

```{toctree}
:hidden:
:caption: Nodes and developers

cli/nodes
```

## Trust Protocols

The `trust` and `atlas` commands work offline over signed records and graph
exports.

| Page | Commands |
|---|---|
| {doc}`cli/trust-graph` | `trust decide`, `trust evidence`, `trust verify-evidence`, `atlas` |
| {doc}`cli/trust-agreements` | `trust agree`, `trust delegate`, `trust context`, `trust boundary-policy`, `trust data` |
| {doc}`cli/trust-evidence` | `trust execution`, `trust freshness`, `trust token`, `trust interop`, `trust disclose`, `trust purge` |
| {doc}`cli/trust-oversight` | `trust justify`, `trust oversight`, `trust consensus` |
| {doc}`cli/trust-agents` | `trust risk`, `trust attest`, `trust guard`, `trust discover`, `trust privacy`, `trust integrity` |

```{toctree}
:hidden:
:caption: Trust protocols

cli/trust-graph
cli/trust-agreements
cli/trust-evidence
cli/trust-oversight
cli/trust-agents
```
