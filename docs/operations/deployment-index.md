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

:::{grid-item-card} Network Authority VM Bootstrap
:link: vm-bootstrap
:link-type: doc

Provider-neutral Ubuntu VM bootstrap for a single-host Network Authority.
:::

:::{grid-item-card} Infrastructure
:link: infrastructure
:link-type: doc

General infrastructure expectations (networking, certificates, persistence)
that apply across providers.
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
