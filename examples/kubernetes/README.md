# Kubernetes Deployment Example

Minimal manifests to run the Genesis Mesh Network Authority on Kubernetes.

## Files

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates the `genesis-mesh` namespace. |
| `na-secrets.yaml` | Mounts the signed genesis block, NA private key, and operator public keys. **Edit before applying.** |
| `na-pvc.yaml` | 5 GiB PVC for the SQLite database. |
| `na-deployment.yaml` | Single-replica Deployment running the Gunicorn NA. |
| `na-service.yaml` | ClusterIP Service on port 8443. |

## Prerequisites

- A Kubernetes cluster (`kubectl` configured)
- The Genesis Mesh container image published to a registry your cluster can pull
- A locally generated signed genesis block, NA private key, and operator public key

Generate the inputs locally:

```bash
genesis-mesh init
```

This produces `.genesis-mesh/genesis.signed.json`, `.genesis-mesh/keys/na.key`,
and `.genesis-mesh/keys/operator.pub`.

## Apply

1. Edit `na-secrets.yaml` and replace the `REPLACE_WITH_...` placeholders with
   real base64-encoded values:

   ```bash
   base64 -w0 .genesis-mesh/genesis.signed.json
   base64 -w0 .genesis-mesh/keys/na.key
   cat       .genesis-mesh/keys/operator.pub
   ```

2. Apply the manifests:

   ```bash
   kubectl apply -f examples/kubernetes/namespace.yaml
   kubectl apply -f examples/kubernetes/na-secrets.yaml
   kubectl apply -f examples/kubernetes/na-pvc.yaml
   kubectl apply -f examples/kubernetes/na-deployment.yaml
   kubectl apply -f examples/kubernetes/na-service.yaml
   ```

3. Verify:

   ```bash
   kubectl -n genesis-mesh get pods,svc,pvc
   kubectl -n genesis-mesh logs deploy/genesis-mesh-na
   ```

4. Probe health (via port-forward, ingress, or a LoadBalancer service):

   ```bash
   kubectl -n genesis-mesh port-forward svc/genesis-mesh-na 8443:8443 &
   curl http://127.0.0.1:8443/healthz
   curl http://127.0.0.1:8443/readyz
   ```

## Production Boundaries

- SQLite is treated as single-writer. **Do not raise `replicas` above 1** unless
  you replace SQLite with a multi-writer backend.
- Add an `Ingress` (or LoadBalancer service) with TLS termination if you expose
  the NA outside the cluster.
- Keep `genesis-mesh-na` and `genesis-mesh-operators` secrets in an external
  secret manager (Vault, External Secrets, etc.) instead of plaintext YAML.
- Peer runtime WebSocket ports belong to mesh nodes, not the NA Service.

## See Also

- [Kubernetes deployment guide](../../docs/operations/kubernetes-deployment.md)
- [Live Azure VM deployment](../../docs/operations/deployment.md)
