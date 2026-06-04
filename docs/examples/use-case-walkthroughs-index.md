# Use-Case Walkthroughs

Domain-specific deployment patterns. Each walkthrough takes the same
underlying primitives - identity, trust, recognition, revocation - and
shows what they look like inside a particular operating domain.

Read this section if you are mapping Genesis Mesh onto a specific
environment such as an edge fleet, a sovereign organization, or a
distributed compute cluster.

```{toctree}
:maxdepth: 1
:hidden:

edge-fleet
sovereign-organization
compute-cluster
```

## Start Here

::::{grid} 1 1 2 3
:gutter: 3

:::{grid-item-card} Edge Fleet
:link: edge-fleet
:link-type: doc

Industrial IoT and edge-device patterns - a mesh of constrained devices
admitted, authorized, and revocable from a central operator without
trusting the network they sit on.
:::

:::{grid-item-card} Sovereign Organization
:link: sovereign-organization
:link-type: doc

An organization running its own trust domain for internal services,
members, and agents, with no dependency on a third-party identity
provider.
:::

:::{grid-item-card} Distributed Compute Cluster
:link: compute-cluster
:link-type: doc

A compute cluster where workers only accept jobs from identities the
operator has explicitly let in, and where the operator can pull back any
identity at any time.
:::

::::
