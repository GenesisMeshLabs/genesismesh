# Sovereign Health and Trust Dashboard

The sovereign dashboard is a public, read-only view over local Network
Authority state. It needs no operator key, so anyone who can reach the NA can
read it. It summarizes health, treaty lifecycle risk, revocation-feed
freshness, recent trust-state changes, and links to raw JSON surfaces.

The dashboard is not a source of trust. It cannot create, mutate, authorize, or
revoke recognition. Treaties, revocation feeds, policy, and audit records remain
the source of truth.

## See It Run

```{image} ../examples/assets/images/genesis-mesh-sovereign-health-dashboard.gif
:alt: A recorded run of the sovereign health and trust dashboard
:class: screenshot
```

Recorded from the example scripts; the steps and output are in {doc}`../examples/sovereign-health-dashboard`.

## Open The Dashboard

For a local Network Authority:

```powershell
curl -fsS http://127.0.0.1:8443/dashboard
curl -fsS http://127.0.0.1:8443/dashboard.json
```

The public reference dashboard at na.genesismesh.org serves the same page
over its demo authorities (it is a read-only dashboard, not a Network
Authority API):

```powershell
curl -fsS https://na.genesismesh.org/dashboard
curl -fsS https://na.genesismesh.org/dashboard.json
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
- the newest complete accept, import, reject trust cycle;
- recent trust-relevant audit events with sanitized details;
- boundary policy health: the active policies, and a warning when a policy
  fails re-verification (every policy-aware evaluation is then denied);
- verification links to the raw JSON and generated references.

## Empty States

A fresh sovereign may have no treaties, no imported revocation feeds, and no
recent trust-state changes. That is a valid state. It means the sovereign has
not yet recognized another sovereign or imported revocation material.

Use federation bootstrap to create the first direct-recognition treaty:

```powershell
genesis-mesh federation bootstrap `
  --acceptor https://acceptor.example.org `
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

Only the newest imported sequence for each issuer contributes to this
freshness summary. Older retained sequences remain available as historical
evidence but do not count as separate current feeds.

The daily trust-cycle canary is `fresh` for 30 hours, `watch` through 48 hours,
and then `stale`. This window accommodates the timer's randomized start delay
without hiding a missed daily run. The audit record must show the same
attestation accepted, its issuer's newer signed feed imported, and that
attestation rejected as locally revoked. API liveness alone cannot produce a
verified trust-cycle result.

These thresholds are operator visibility signals. They do not change protocol
acceptance rules.

## What It Does Not Do

- It does not grant trust.
- It does not import trust bundles.
- It does not issue or revoke treaties.
- It does not execute browser admin actions.
- It does not replace audit export or raw JSON verification.
