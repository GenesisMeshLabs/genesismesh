# Deployment

These guides cover standing up a Genesis Mesh deployment from scratch. They are
ordered from broad strategy down to specific automation paths.

Use this section when you are choosing how to run a Network Authority or a
sovereign for the first time. Day-to-day operations on an already-running
deployment live in the [Runbooks](runbooks-index.md) section.

```{toctree}
:maxdepth: 1
:hidden:

deployment
container-images
high-availability
public-reference-dashboard
vm-bootstrap
infrastructure
terraform-deployment
kubernetes-deployment
```

## Start Here

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Deployment Options
:link: deployment
:link-type: doc

High-level overview of the supported deployment shapes and when to choose
each.
:::

:::{grid-item-card} Container Images
:link: container-images
:link-type: doc

The signed Network Authority, gateway and edge agent images: tags, verifying
signatures, the runtime contract, key providers, Compose and upgrades.
:::

:::{grid-item-card} High Availability
:link: high-availability
:link-type: doc

Two or more NA instances on a shared PostgreSQL database behind a load
balancer: configuration, key provider, failover, migration, backup and DR
(v0.60).
:::

:::{grid-item-card} Network Authority VM Bootstrap
:link: vm-bootstrap
:link-type: doc

Provider-neutral Ubuntu VM bootstrap for a single-host Network Authority.
:::

:::{grid-item-card} Public Reference Dashboard
:link: public-reference-dashboard
:link-type: doc

The read-only public instance at na.genesismesh.org: how it is deployed and
where its demo keys are.
:::

:::{grid-item-card} Infrastructure
:link: infrastructure
:link-type: doc

The layout of the `infrastructure/` and `deploy/` directories, the Azure
Container Apps scripts and Terraform checks.
:::

:::{grid-item-card} Terraform Deployment on Azure
:link: terraform-deployment
:link-type: doc

Infrastructure-as-code path for Azure deployments.
:::

:::{grid-item-card} Kubernetes Deployment
:link: kubernetes-deployment
:link-type: doc

Manifests and example layout for running on a Kubernetes cluster.
:::

::::
