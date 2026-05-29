# Monitoring

Genesis Mesh includes health-check and metrics components, and the Network
Authority exposes HTTP health endpoints.

## Network Authority Probes

- `GET /healthz`: liveness. Use this to determine whether the process can
  respond.
- `GET /readyz`: readiness. Use this to determine whether the service is ready
  to receive traffic.

## Node Health

Node health should include:

- certificate validity
- peer connectivity
- route table state
- CRL freshness
- policy freshness
- heartbeat success

## Operational Signals

Track these signals in production-like deployments:

- join success and failure rates
- invite-token rejection rates
- heartbeat failures
- renewal failures
- revocation events
- peer handshake failures
- route withdrawal and route rejection counts
- database migration state
- database backup freshness

## Logging

Avoid logging private key paths as proof of secret presence. Log certificate IDs,
node IDs, operator key IDs, and request IDs where useful, but never log private
keys or invite token secrets.
