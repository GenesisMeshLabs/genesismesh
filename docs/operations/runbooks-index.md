# Runbooks

These guides cover running a Genesis Mesh deployment day to day. They assume
the deployment is already standing - if you are installing for the first time,
start with [Deployment](deployment-index.md).

Use this section when you need to observe, audit, recover, or respond to an
operational event on a running Network Authority or sovereign.

```{toctree}
:maxdepth: 1
:hidden:

monitoring
audit-export
incident-response
backup-restore
revocation
managed-sovereign
```

## Start Here

::::{grid} 1 1 2 3
:gutter: 3

:::{grid-item-card} Monitoring
:link: monitoring
:link-type: doc

Healthz, readyz, metrics, and external uptime checks.
:::

:::{grid-item-card} Audit Export
:link: audit-export
:link-type: doc

Exporting trust-decision events for downstream review or SIEM ingest.
:::

:::{grid-item-card} Incident Response Runbooks
:link: incident-response
:link-type: doc

Step-by-step playbooks for operator key compromise, NA key compromise, bad
treaty, bad feed, database restore, and revocation blast-radius review.
:::

:::{grid-item-card} Backup and Restore
:link: backup-restore
:link-type: doc

Backup procedure, restore procedure, drill checklist, and validation of
restored Connectome state.
:::

:::{grid-item-card} Revocation
:link: revocation
:link-type: doc

Revocation procedures for credentials and trust material, including
propagation considerations.
:::

:::{grid-item-card} Managed Sovereign Operations
:link: managed-sovereign
:link-type: doc

Operational guidance for running a Network Authority on behalf of a
customer or design partner while keeping the trust boundary explicit.
:::

::::
