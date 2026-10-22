# Monitoring

Genesis Mesh includes health-check and metrics components, and the Network
Authority exposes HTTP health endpoints.

## Network Authority Probes

- `GET /healthz`: liveness. Use this to determine whether the process can
  respond.
- `GET /readyz`: readiness. Use this to determine whether the service is ready
  to receive traffic.
- `GET /metrics` (beta): Prometheus text exposition. It is not
  authenticated: restrict it at the proxy. It exposes six series:

  | Series | Type | Meaning |
  | --- | --- | --- |
  | `genesis_mesh_na_issued_certs_total` | gauge | Certificates issued |
  | `genesis_mesh_na_active_nodes` | gauge | Recently active nodes |
  | `genesis_mesh_na_revoked_certs_total` | gauge | Certificates marked revoked |
  | `genesis_mesh_na_crl_sequence` | gauge | Sequence of the active CRL |
  | `genesis_mesh_na_policy_versions_total` | gauge | Persisted policy versions |
  | `genesis_mesh_na_audit_write_failures_total` | counter | Auth-failure audit events that could not be written |

  Alert on any increase of `genesis_mesh_na_audit_write_failures_total`:
  the audit log is missing events.

`/readyz` is not ready (`503`) when the database is not writable or not at the
current schema, or when the NA key it loaded is not the key in effect: a successor before its
`effective_at`, a succeeded key, or an expired one (`na_key.state`, see
{doc}`key-succession`).

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
membership, trust, and routing failures before users see message loss. No
metric exposes the first seven yet: read them from the logs and the audit
events.

- join success and failure rates
- invite-token rejection rates
- heartbeat failures
- renewal failures
- revocation events
- peer handshake failures
- route withdrawal and route rejection counts
- database migration state
- database backup freshness

### Evidence store signals

With the evidence store on (`EVIDENCE_STORE=on`, off by default), also watch
these. Each needs an operator key (read tier):

- `GET /admin/evidence/status`: `unanchored_entries` and the age of
  `latest_anchor`; `anchoring_blocked` (an instance's clock ran ahead);
  `unjudged_records`; with out-of-band records on, the registry's health; with
  remediation on, remediations by state.
- `GET /admin/evidence/remediations` (with `EVIDENCE_REMEDIATION=on`): the
  due queue, including overdue remediations.
- The age of the newest anchor copy you hold
  (`genesis-mesh evidence anchors fetch`, {doc}`evidence-anchors`).
- Offline edge nodes and their pending uploads:
  `genesis-mesh admin edge-nodes --status offline` ({doc}`edge-agent`).

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

## Trust-Cycle Canary

A canary exercises the recognition and revocation path end to end, which
`/healthz` cannot. `genesis-mesh proof canary` runs one cycle between two
sovereigns you operate, through their signed HTTP APIs:

1. the issuer creates an attestation;
2. the acceptor creates a scoped recognition treaty;
3. the identical attestation is accepted;
4. the issuer revokes the attestation;
5. the acceptor imports the higher-sequence signed revocation feed;
6. the identical attestation is rejected as locally revoked.

It signs a receipt of the cycle (`--receipt-signing-key`), writes it to
`--receipt` and records it in `--audit-db`. Run it from a systemd timer or
another scheduler, and alert when a run fails or the last receipt is older
than your interval. See `genesis-mesh proof canary --help` for the options.

Treat `/healthz` and the canary as separate signals. Liveness proves that the
API responds. A fresh verified cycle proves that the recognition and
revocation path was exercised successfully.

### The public reference

The public reference at na.genesismesh.org runs no Network Authority, so it
does not use `proof canary`. Its `genesis-mesh-public-maintenance.timer` runs
hourly; once a day the run includes a canary that issues a demo attestation,
accepts it, revokes it and checks the rejection (see
{doc}`public-reference-dashboard`). A failed run starts
`genesis-mesh-public-alert.service`, which logs a line starting with
`PUBLIC_FEED_IMPORT_FAILED`. Check it with:

```bash
systemctl status genesis-mesh-public-maintenance.timer
systemctl show genesis-mesh-public-maintenance.service -p Result
```

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
