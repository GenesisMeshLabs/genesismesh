# Managed Sovereign Readiness

This example demonstrates the operational claim behind v0.16: a managed
Network Authority can be backed up, audited, restored, and reopened with
operator-visible health and Connectome state intact.

The demo is intentionally local and non-production. It uses a temporary SQLite
database, runs the real `genesis-mesh managed` CLI commands, and checks the
restored Network Authority through Flask endpoints.

```{mermaid}
sequenceDiagram
    participant NA as Managed NA
    participant DB as SQLite DB
    participant CLI as genesis-mesh managed
    participant Audit as Audit Export
    participant C as Connectome

    NA->>DB: Persist treaty + audit event
    CLI->>DB: managed backup
    NA->>DB: Mutate state after backup
    CLI->>Audit: managed audit-export
    CLI->>DB: managed restore
    NA->>NA: Reopen service
    NA->>C: GET /connectome.json
    C-->>NA: Restored treaty state
```

## Live Recording

```{image} assets/images/genesis-mesh-managed-sovereign.gif
:alt: Managed sovereign backup, audit export, restore, and endpoint drill
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-managed-sovereign.png
:alt: Static managed sovereign operations drill screenshot
:class: screenshot
```

## Run

Regenerate the documentation assets:

```powershell
python docs\examples\assets\scripts\managed-sovereign-demo.py
```

Expected proof:

```text
==> Online backup created
    backup:      managed-demo-backup.db

==> Redacted audit export written
    events:      2
    redacted:    True

==> Restored NA reopened cleanly
    healthz:     ok
    readyz:      ready
    treaties:    1
    active edges: 1

Result: managed sovereign backup, audit export, restore, and endpoint drill passed.
```

## What This Proves

- `genesis-mesh managed backup` creates a restorable SQLite snapshot.
- `genesis-mesh managed audit-export` produces a redacted support/SIEM artifact.
- `genesis-mesh managed restore` can roll back mutated trust state.
- A restored Network Authority can reopen the database.
- `/healthz`, `/readyz`, and `/connectome.json` still work after restore.

## What This Does Not Claim

- This is not active-active high availability.
- This is not a multi-tenant managed control plane.
- This does not include billing, SSO, or enterprise IdP integration.
- This does not replace a real customer pilot or external operator adoption
  proof.

## Related Runbooks

- [](../operations/backup-restore.md)
- [](../operations/audit-export.md)
- [](../operations/incident-response.md)
- [](../operations/managed-sovereign.md)
