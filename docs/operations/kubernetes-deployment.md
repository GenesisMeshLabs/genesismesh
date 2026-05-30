# Kubernetes Deployment

Kubernetes is a good host for the Network Authority when you already operate a
cluster and want standard ingress, secret, volume, and monitoring primitives.
Genesis Mesh does not replace a Kubernetes service mesh — it provides the
membership, trust, certificate, policy, and revocation layer for nodes and
agents inside or outside the cluster.

The repository ships a working example under
[`examples/kubernetes/`](https://github.com/thaersaidi/genesismesh/tree/main/examples/kubernetes).

## Deployment Shape

```{mermaid}
flowchart TB
    ingress["Ingress / Load Balancer"]
    svc["Service genesis-mesh-na :8443"]
    deploy["Deployment genesis-mesh-na (1 replica)"]
    secret["Secret genesis-mesh-na<br/>genesis + NA key"]
    opsec["Secret genesis-mesh-operators<br/>operator public keys"]
    pvc["PVC genesis-mesh-na-data<br/>SQLite DB"]
    nodes["External mesh nodes"]

    ingress --> svc
    svc --> deploy
    secret --> deploy
    opsec --> deploy
    pvc --> deploy
    deploy -->|invite, cert, policy, CRL| nodes
    nodes <-->|Noise XX peer sessions| nodes
```

## Manifests

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates the `genesis-mesh` namespace. |
| `na-secrets.yaml` | Secret with the genesis block, NA key, and operator public keys. |
| `na-pvc.yaml` | 5 GiB PVC for the SQLite database. |
| `na-deployment.yaml` | Single-replica non-root Deployment with `/healthz` and `/readyz` probes. |
| `na-service.yaml` | ClusterIP Service on port 8443. |

## Quick Start

1. Generate the inputs locally with the CLI:

   ```bash
   genesis-mesh init
   ```

2. Edit `examples/kubernetes/na-secrets.yaml` and replace each `REPLACE_WITH_…`
   placeholder with the base64-encoded contents of:

   ```bash
   base64 -w0 .genesis-mesh/genesis.signed.json
   base64 -w0 .genesis-mesh/keys/na.key
   cat       .genesis-mesh/keys/operator.pub
   ```

3. Apply:

   ```bash
   kubectl apply -f examples/kubernetes/namespace.yaml
   kubectl apply -f examples/kubernetes/na-secrets.yaml
   kubectl apply -f examples/kubernetes/na-pvc.yaml
   kubectl apply -f examples/kubernetes/na-deployment.yaml
   kubectl apply -f examples/kubernetes/na-service.yaml
   ```

4. Verify the rollout:

   ```bash
   kubectl -n genesis-mesh get pods,svc,pvc
   kubectl -n genesis-mesh logs deploy/genesis-mesh-na
   ```

5. Probe `/healthz` and `/readyz` via port-forward:

   ```bash
   kubectl -n genesis-mesh port-forward svc/genesis-mesh-na 8443:8443 &
   curl http://127.0.0.1:8443/healthz
   curl http://127.0.0.1:8443/readyz
   ```

## Environment

The container expects the same environment variables used by `start.sh`. The
provided Deployment already sets:

```yaml
env:
  - name: SERVICE_ROLE
    value: na
  - name: GENESIS_FILE
    value: /run/secrets/genesis-mesh/genesis.signed.json
  - name: NA_PRIVATE_KEY_FILE
    value: /run/secrets/genesis-mesh/na.key
  - name: DB_PATH
    value: /var/lib/genesis-mesh/na.db
  - name: PORT
    value: "8443"
  - name: WEB_CONCURRENCY
    value: "4"
  - name: OPERATOR_PUBLIC_KEYS_JSON
    valueFrom:
      secretKeyRef:
        name: genesis-mesh-operators
        key: operator-public-keys.json
```

## Probes

`/healthz` is liveness only and does not touch the database. `/readyz` checks
DB, genesis block, and NA key state.

```yaml
livenessProbe:
  httpGet: { path: /healthz, port: http }
readinessProbe:
  httpGet: { path: /readyz, port: http }
```

## Important Boundaries

- **Do not run multiple Network Authority pods against the same SQLite file.**
  SQLite is treated as a single-writer deployment store. Keep `replicas: 1` and
  the rollout `strategy: Recreate`.
- Keep the NA private key and operator keys inside Kubernetes secrets or an
  external secret manager (Vault, External Secrets, etc.). Admin callers should
  use operator keys, not the NA private key.
- Expose only the Network Authority HTTP API through ingress. Peer runtime
  WebSocket ports belong to mesh nodes, not the NA Service.
- Add a `NetworkPolicy` if you only want specific namespaces to reach the NA.

## When To Use a Kubernetes Service Mesh Too

Use a Kubernetes service mesh when you need in-cluster workload traffic
management, retries, ingress policy, observability, and mTLS between Kubernetes
services.

Use Genesis Mesh when the important question is whether an external node,
agent, or worker is allowed to join a sovereign network, prove identity,
receive policy, route to peers, and be revoked.
