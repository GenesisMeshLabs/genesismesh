# Trust & Sovereignty Examples

These examples are the architectural heart of Genesis Mesh, shown in running
code: portable trust between independently administered sovereigns, treaty-based
recognition, cross-boundary revocation propagation, and a human-visible
recognition graph.

Read this section if you want to understand or demonstrate how trust travels
across sovereign boundaries without a central authority.

```{toctree}
:maxdepth: 1
:hidden:

sovereign-attestations
recognition-treaties
cross-sovereign-revocation
connectome
independent-sovereigns
```

## Start Here

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Sovereign Membership Attestations
:link: sovereign-attestations
:link-type: doc

One sovereign issues a signed membership attestation; another sovereign
accepts or rejects it based on local recognition policy.
:::

:::{grid-item-card} Recognition Treaties
:link: recognition-treaties
:link-type: doc

Explicit signed community-to-community recognition. Treaty-backed
attestation verification and revocable treaties.
:::

:::{grid-item-card} Cross-Sovereign Revocation Propagation
:link: cross-sovereign-revocation
:link-type: doc

Signed revocation feeds that propagate trust withdrawal across recognized
sovereigns without revoking the treaty itself.
:::

:::{grid-item-card} Connectome Operator View
:link: connectome
:link-type: doc

The recognition graph rendered for an operator, including trust-path
explanations and revocation blast-radius summaries.
:::

:::{grid-item-card} Independent Sovereigns Proof
:link: independent-sovereigns
:link-type: doc

The cross-cloud operational proof between sovereigns on Azure and
DigitalOcean, with separate keys, databases, and policies.
:::

::::
