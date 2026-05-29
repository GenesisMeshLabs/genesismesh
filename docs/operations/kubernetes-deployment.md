# Kubernetes Deployment Guide

Kubernetes is a good host for the Network Authority when you already operate a
cluster and want standard ingress, secret, volume, and monitoring primitives.
Genesis Mesh does not replace a Kubernetes service mesh; it provides the
membership, trust, certificate, policy, and revocation layer for nodes and
agents.

## Deployment Shape

```{mermaid}
flowchart TB
    ingress["Ingress / Load Balancer"]
    svc["Service :8443"]
    deploy["Network Authority Deployment"]
    secret["Kubernetes Secret<br/>Genesis + NA key"]
    pvc["PersistentVolumeClaim<br/>SQLite DB"]
    nodes["External Mesh Nodes"]

    ingress --> svc
    svc --> deploy
    secret --> deploy
    pvc --> deploy
    deploy -->|invite, cert, policy, CRL| nodes
    nodes <-->|Noise XX peer sessions| nodes
```

## Required Objects

A minimal production-oriented deployment needs:

- A `Secret` containing the signed genesis block and NA private key.
- A `Secret` or config value containing `OPERATOR_PUBLIC_KEYS_JSON`.
- A persistent volume for the SQLite database.
- A `Deployment` running the Genesis Mesh image.
- A `Service` exposing port `8443`.
- An ingress or load balancer with TLS termination.
- Health probes for `/healthz` and `/readyz`.

## Environment

The container expects the same environment variables used by `start.sh`:

```yaml
env:
  - name: SERVICE_ROLE
    value: na
  - name: GENESIS_FILE
    value: /run/secrets/genesis.signed.json
  - name: NA_PRIVATE_KEY_FILE
    value: /run/secrets/na.key
  - name: DB_PATH
    value: /data/genesis_mesh_na.db
  - name: OPERATOR_PUBLIC_KEYS_JSON
    valueFrom:
      secretKeyRef:
        name: genesis-mesh-operators
        key: operator-public-keys.json
```

Mount the genesis and NA key files read-only, and mount the database directory
on durable storage.

## Probes

Use `/healthz` for liveness and `/readyz` for readiness:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8443
readinessProbe:
  httpGet:
    path: /readyz
    port: 8443
```

## Important Boundaries

- Do not run multiple Network Authority pods against the same SQLite file.
  SQLite is treated as a single-writer deployment store.
- Use one replica unless you replace SQLite with a multi-writer backend and
  update the application accordingly.
- Keep the NA private key inside Kubernetes secrets or an external secret
  manager; admin callers should use operator keys, not the NA private key.
- Expose only the Network Authority HTTP API through ingress. Peer runtime
  WebSocket ports belong to mesh nodes, not the NA service.

## When To Use a Kubernetes Service Mesh Too

Use a Kubernetes service mesh when you need in-cluster workload traffic
management, retries, ingress policy, observability, and mTLS between Kubernetes
services.

Use Genesis Mesh when the important question is whether an external node,
agent, or worker is allowed to join a sovereign network, prove identity,
receive policy, route to peers, and be revoked.
