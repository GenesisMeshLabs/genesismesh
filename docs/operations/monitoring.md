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

Genesis Mesh configures process logging through the shared observability layer.
Network Authority, CLI, and node entrypoints honor these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `GENESIS_LOG_LEVEL` | `INFO` | Minimum process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `GENESIS_LOG_FORMAT` | `text` | Log rendering format. Use `json` for machine-ingested logs. |

Network Authority API responses include an `X-Request-ID` header. The service
logs every HTTP request with the request ID, method, path, status, duration, and
remote address, and centralized API error handling logs failures through the
same request ID.

When `GENESIS_LOG_FORMAT=json` is set, request metadata is emitted as
first-class JSON keys, not embedded in the message string:

```json
{
  "duration_ms": 0.31,
  "level": "INFO",
  "logger": "genesis_mesh.na_service.access",
  "message": "API request",
  "method": "GET",
  "path": "/healthz",
  "remote_addr": "127.0.0.1",
  "request_id": "req-123",
  "status": 200
}
```

The local `genesis-mesh na start` development server also routes its startup
and Werkzeug request messages through this configured logging path. Production
deployments should still use `start.sh` and Gunicorn.

The shared logging layer redacts common secret shapes before writing logs,
including invite tokens, bearer tokens, signatures, passwords, private-key
markers, and common private-key file paths. Avoid logging private key paths as
proof of secret presence. Log certificate IDs, node IDs, operator key IDs, and
request IDs where useful, but never intentionally log private keys, invite token
secrets, request bodies, or authorization headers.
