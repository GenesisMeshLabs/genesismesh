# Sovereign Health and Trust Dashboard

The sovereign dashboard is a read-only operator view over local Network
Authority state. It summarizes health, treaty lifecycle risk, revocation-feed
freshness, recent trust-state changes, and links to raw JSON surfaces.

The dashboard is not a source of trust. It cannot create, mutate, authorize, or
revoke recognition. Treaties, revocation feeds, policy, and audit records remain
the source of truth.

## Open The Dashboard

For a local Network Authority:

```powershell
curl -fsS http://127.0.0.1:8443/dashboard
curl -fsS http://127.0.0.1:8443/dashboard.json
```

For the live Azure sovereign:

```powershell
curl -fsS https://na.genesismesh.connectorzzz.com/dashboard
curl -fsS https://na.genesismesh.connectorzzz.com/dashboard.json
```

Use the HTML page for operator review and screenshots. Use
`/dashboard.json`, `/connectome.json`, `/recognition-graph`, and
`/recognition-treaties` for automation or independent verification.

## What It Shows

- sovereign identity and readiness;
- active node count and tracked node count;
- Connectome counts;
- treaty lifecycle state and expiry risk;
- imported sovereign revocation feed freshness;
- recent trust-relevant audit events with sanitized details;
- verification links to the raw JSON and generated references.

## Empty States

A fresh sovereign may have no treaties, no imported revocation feeds, and no
recent trust-state changes. That is a valid state. It means the sovereign has
not yet recognized another sovereign or imported revocation material.

Use federation bootstrap to create the first direct-recognition treaty:

```powershell
genesis-mesh federation bootstrap `
  --acceptor https://na.genesismesh.connectorzzz.com `
  --issuer-bundle .\issuer-trust-bundle.json `
  --operator-key .genesis-mesh\keys\operator.key `
  --operator-key-id operator-local `
  --role service:maintainer `
  --validity-hours 24 `
  --yes
```

## Warning Thresholds

Treaty expiry risk is derived from persisted treaty validity:

- `high`: expires within 24 hours;
- `medium`: expires within 72 hours;
- `expired`: no longer within the validity window;
- `low`: active and not close to expiry.

Revocation-feed freshness is derived from local import time:

- `fresh`: imported within 24 hours;
- `watch`: imported within 72 hours;
- `stale`: older than 72 hours.

These thresholds are operator visibility signals. They do not change protocol
acceptance rules.

## What It Does Not Do

- It does not grant trust.
- It does not import trust bundles.
- It does not issue or revoke treaties.
- It does not execute browser admin actions.
- It does not replace audit export or raw JSON verification.
