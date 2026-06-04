# Adoption & Positioning Examples

These examples are the material aimed at people evaluating Genesis Mesh for
their own use - maintainers considering running a sovereign, organizations
considering a managed deployment, and readers comparing it to adjacent
projects.

Read this section if you are deciding whether Genesis Mesh fits your
problem, or if you are explaining the project to someone who is.

```{toctree}
:maxdepth: 1
:hidden:

supply-chain-trust-gate
managed-sovereign-readiness
operator-onboarding-exchange
maintainer-sovereign-pitch
sigstore-comparison
```

## Start Here

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Supply-Chain Trust Gate
:link: supply-chain-trust-gate
:link-type: doc

A narrow CI/release gate that demonstrates how Genesis Mesh sits in a
publishing path - portable maintainer attestations honored across projects,
with revocation blocking the same maintainer after import.
:::

:::{grid-item-card} Managed Sovereign Readiness Example
:link: managed-sovereign-readiness
:link-type: doc

The operational claim behind a managed Network Authority - backup, restore,
audit, and incident workflows are demonstrable end to end.
:::

:::{grid-item-card} Federation Bootstrap And Trust Bundle Exchange
:link: operator-onboarding-exchange
:link-type: doc

The operator-onboarding path: export public trust material, validate it, record
a review receipt, and feed it into federation bootstrap without granting trust
automatically.
:::

:::{grid-item-card} Why A Maintainer Would Run A Sovereign
:link: maintainer-sovereign-pitch
:link-type: doc

A recruitment-oriented page aimed at open-source maintainers explaining the
concrete reasons to stand up a sovereign.
:::

:::{grid-item-card} Genesis Mesh vs Sigstore And SLSA
:link: sigstore-comparison
:link-type: doc

How Genesis Mesh differs from in-domain provenance signing systems, and why
portable trust across sovereigns is a distinct property.
:::

::::
