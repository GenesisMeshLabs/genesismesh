# Monitoring

Genesis Mesh includes health-check and metrics components, and the Network
Authority exposes HTTP health endpoints.

## Network Authority Probes

- `GET /healthz`: liveness. Use this to determine whether the process can
  respond.
- `GET /readyz`: readiness. Use this to determine whether the service is ready
  to receive traffic.
- `GET /metrics`: Prometheus text exposition for Network Authority counters,
  including issued certificates, active nodes, revoked certificates, CRL
  sequence, and policy versions.

## Node Health

For a node, monitor:

- certificate validity
- peer connectivity
- route table state
- CRL freshness
- policy freshness
- heartbeat success

## Operational Signals

Track these signals in production-like deployments because they identify
membership, trust, and routing failures before users see message loss:

- join success and failure rates
- invite-token rejection rates
- heartbeat failures
- renewal failures
- revocation events
- peer handshake failures
- route withdrawal and route rejection counts
- database migration state
- database backup freshness

## Example Alert Thresholds

Use these as starting points for a managed sovereign pilot:

| Signal | Suggested alert |
|---|---|
| `/healthz` | Critical after 2 consecutive failures. |
| `/readyz` | Critical after 1 failure on a serving endpoint. |
| `/metrics` | Warning if scrape fails for 5 minutes. |
| Active cert count | Warning on unexpected drop to zero. |
| CRL sequence | Warning if unchanged after an expected revocation. |
| DB disk free | Warning below 20%, critical below 10%. |
| Backup freshness | Warning after 24 hours, critical after 48 hours. |
| Certificate expiry | Warning if operational certs expire within 7 days. |
| Treaty verification failures | Warning on sustained increase over baseline. |

## Managed Smoke Commands

Run these after deploys, restores, and incident remediation:

```bash
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS http://127.0.0.1:8443/readyz
curl -fsS http://127.0.0.1:8443/metrics | head
curl -fsS http://127.0.0.1:8443/connectome.json
```

For public endpoints, run the same probes from outside the VM or cluster so
ingress, TLS, DNS, and firewall state are included in the check.

## Logging

Avoid logging private key paths as proof of secret presence. Log certificate IDs,
node IDs, operator key IDs, and request IDs where useful, but never log private
keys or invite token secrets.
