# Deployment Options

Genesis Mesh supports four deployment shapes. Pick the one that matches your
operational target.

```{mermaid}
flowchart TB
    secrets["Mounted secrets<br/>genesis.signed.json + na.key"]
    operator["OPERATOR_PUBLIC_KEYS_JSON"]
    container["Genesis Mesh container"]
    gunicorn["Gunicorn"]
    flask["Network Authority app"]
    sqlite["SQLite DB on durable volume"]
    ingress["Ingress / TLS termination"]

    ingress --> gunicorn
    gunicorn --> flask
    flask --> sqlite
    secrets -->|GENESIS_FILE, NA_PRIVATE_KEY_FILE| container
    operator --> container
    container --> gunicorn
```

## Public Instances

The project runs two public instances. Neither is a template for production:
both are demonstrations.

- **[https://na.genesismesh.org](https://na.genesismesh.org)** is the
  sanitized public reference: a read-only dashboard over ten demo
  authorities, on an Azure VM (Sweden Central, Terraform provisioned,
  `Standard_B2ts_v2`) with Nginx, TLS from Let's Encrypt and Gunicorn
  (2 workers). It serves no Network Authority API. The Network Authority that
  first ran on this VM is retired. The demo authorities' signing keys sit on
  the same VM; see {doc}`public-reference-dashboard`.
- **[https://mesh.genesismesh.org](https://mesh.genesismesh.org)** is a
  gateway console in front of its own Network Authority, on one small VM with
  Docker Compose (`infrastructure/mesh-demo/`). The NA is not published; only
  the gateway reaches it.

---

## 1. Local Process

The fastest way to run a Network Authority. Suitable for development, demos,
and CI smoke tests.

```bash
genesis-mesh init
genesis-mesh na start
```

`genesis-mesh na start` uses the Flask development server. For production
container or VM startup, use Gunicorn through `start.sh`.

See: [In-process smoke demo](../examples/demos-packaging.md#15-in-process-smoke-demo) and
[Live CLI process smoke demo](../examples/demos-packaging.md#16-live-cli-process-smoke-demo)

## 2. Docker

Each release publishes a signed Network Authority image,
`ghcr.io/genesismeshlabs/genesis-mesh`, and a signed gateway image. Verify the
signature and deploy by digest: [Container Images](container-images.md)
covers verification, the runtime contract, key providers and Compose.

The entry point is `start.sh`, run by `tini`. In Network Authority mode it
runs Gunicorn and requires the genesis block and the NA key; state lives in
`/data`, which the container's user (10001) must be able to write.

```bash
sudo chown 10001 secrets/na.key && sudo chmod 0400 secrets/na.key
docker run -d --name na \
  -e SERVICE_ROLE=na \
  -e GENESIS_FILE=/run/secrets/genesis.signed.json \
  -e NA_PRIVATE_KEY_FILE=/run/secrets/na.key \
  -e NA_KEY_ID=na-local \
  -e OPERATOR_PUBLIC_KEYS_JSON='{"operator-local":"<base64-public-key>"}' \
  -e OPERATOR_KEY_TIERS_JSON='{"operator-local":"privileged"}' \
  -e NA_PROXY_HOPS=1 \
  -v "$PWD/secrets:/run/secrets:ro" \
  -v na-data:/data \
  -p 127.0.0.1:8443:8443 \
  ghcr.io/genesismeshlabs/genesis-mesh@sha256:<verified-digest>
```

The key file must be readable by user 10001 (the first line hands it over).
The port is published to the local reverse proxy that terminates TLS; with
no proxy in front, set `NA_PROXY_HOPS=0`. To build the image from a checkout
instead, run `docker build -t genesis-mesh:local .` at the repository root.

For a Network Authority and a gateway together, use the Compose file in
[Container Images](container-images.md).

See: [Docker image smoke demo](../examples/demos-packaging.md#17-docker-image-smoke-demo)
and [Docker Compose example](../examples/demos-packaging.md#18-docker-compose-network-authority-example)

## 3. Kubernetes

A minimal set of manifests is provided under `deploy/kubernetes/`:

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/na-secrets.yaml
kubectl apply -f deploy/kubernetes/na-pvc.yaml
kubectl apply -f deploy/kubernetes/na-deployment.yaml
kubectl apply -f deploy/kubernetes/na-service.yaml
```

The Deployment runs a single non-root replica, mounts the genesis block and NA
key as a `Secret`, and persists the SQLite database to a `PersistentVolumeClaim`.

See: [Kubernetes deployment guide](kubernetes-deployment.md) and
[deploy/kubernetes/README.md](https://github.com/GenesisMeshLabs/genesismesh/tree/main/deploy/kubernetes)

## 4. Terraform on Azure

The `deploy/azure/` directory contains a self-contained Terraform module
that provisions a complete Network Authority environment on Azure: resource
group, virtual network, subnet, public IP, NSG, network interface, and an Ubuntu
22.04 VM.

```bash
cd deploy/azure
terraform init \
  -backend-config="resource_group_name=terraform-state-rg" \
  -backend-config="storage_account_name=tfstategenesismesh" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=genesis-mesh-na.tfstate"
terraform plan -out tfplan \
  -var="ssh_public_key=$(cat ~/.ssh/id_rsa.pub)" \
  -var="admin_cidr=YOUR_IP/32"
terraform apply tfplan
```

`admin_cidr` defaults to `*`, which opens SSH to the internet: always set it.
Apply the saved plan, so the variables you planned with are the ones applied.

This module provisioned the VM behind `https://na.genesismesh.org`.
Terraform runs locally with an operator's Azure credentials; there is no CI
workflow for infrastructure changes.

See: [Terraform deployment guide](terraform-deployment.md)

## Release CD to the Azure VM

Terraform provisions the VM. Code updates are handled by the single deployment
workflow, `.github/workflows/deploy-release-azure-vm.yml`.

The VM serves the sanitized public reference instance
(`examples/public_dashboard`, see
[public reference dashboard](public-reference-dashboard.md)). The original
Network Authority, router and canary services on the VM are retired: they stay
stopped and disabled. Their state, including the retired NA's key files, is
archived on the same VM under `/var/backups/genesis-mesh-offline` (root only,
never served). It is not moved off the host.

Run **Deploy Release to Azure VM** manually from the Actions tab, selecting
`main` as the workflow branch and a release tag (or another ref on `main`) as
the `ref` input. The job reports its deployment status to the
`azure-production` environment. Publishing a release does not automatically
run this workflow.

The workflow resolves the ref to an exact commit and refuses anything not on
`main`. It authenticates with Azure through GitHub OIDC and uses Azure VM Run
Command to run `infrastructure/scripts/deploy-public-dashboard.sh` from that
commit as root. The script backs up state to a root-only archive on the VM,
checks out the commit,
updates the public instance's virtual environment and systemd units, restarts
the public services (restoring the previous ones if a step fails), verifies
the signed evidence, and keeps the retired services stopped and disabled. The
workflow then checks that every retired unit is inactive and disabled, and
probes `GET /readyz` and `GET /dashboard.json` until the public instance
reports the deployed commit.

Required GitHub secrets:

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | Application ID of the Azure deployment service principal |
| `AZURE_TENANT_ID` | Azure tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |

Required GitHub variables:

| Variable | Description |
|---|---|
| `AZURE_RESOURCE_GROUP` | Resource group containing the VM |
| `AZURE_VM_NAME` | VM name |

Configure the `azure-production` environment to allow deployments from the
`main` branch only. Add a federated credential to the Azure application used
by `AZURE_CLIENT_ID` with these exact values:

```text
Issuer: https://token.actions.githubusercontent.com
Subject: repo:GenesisMeshLabs/genesismesh:environment:azure-production
Audience: api://AzureADTokenExchange
```

This repository currently uses the default, non-immutable OIDC subject format.
An environment-scoped job uses the environment subject instead of the branch
subject. No other workflow uses Azure. Remove any leftover branch-subject
credential (`repo:GenesisMeshLabs/genesismesh:ref:refs/heads/main`) that served
the old Terraform workflow.

The environment's previous failed entries remain historical records. A new
release deployment updates its current status only when the workflow runs;
changing the configuration alone does not deploy code or prove VM health.

The workflow deploys only the public reference at `/opt/genesis-mesh-public`.
It never starts the retired Network Authority or router units.

This workflow is intentionally Azure-specific because the next proof levels may
use a second VM on another cloud or a physical host. Add separate release-CD
workflows for those targets instead of hiding multiple deployment environments
behind one generic VM workflow.

## Production Readiness Checks

Before promoting any of the deployment shapes above to production:

- the container starts as a non-root user
- required secret files are mounted
- startup fails closed when required secret files are missing
- `/healthz` and `/readyz` work behind the selected ingress
- the database (a SQLite volume or PostgreSQL) is on durable storage
- backups are tested, with a restore drill ({doc}`backup-restore`)
- `NA_PROXY_HOPS` matches the number of proxies in front of the NA (default
  `0`). Behind one proxy, set `1`; otherwise every client shares the proxy's
  address for rate limits
- `NA_PUBLIC_URL` is set to the public origin when the NA runs behind a proxy
- the root private key is not on the host: check with
  `genesis-mesh na doctor --env-file <settings>`, and set
  `NA_DEPLOYMENT=managed` (default `local`) to make it a start condition
  ({doc}`key-succession`)
- operator public keys are reviewed and rotated through policy
- logs do not expose private key material

Do not run two Network Authority processes against the same SQLite database
file. Genesis Mesh treats SQLite as a single-writer deployment store. To run
several instances, use the PostgreSQL option described in
[High Availability](high-availability.md) (v0.60).
