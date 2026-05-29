# Deployment

## Live Deployment

A public Network Authority runs on Azure (Sweden Central):

**https://na.genesismesh.connectorzzz.com**

Two nodes are enrolled from separate IP addresses with active heartbeats. The
deployment uses a `Standard_B2ts_v2` VM, Gunicorn behind Nginx with TLS, and
a systemd-managed NA service with SQLite persistence.

![NA dashboard showing 2 active nodes](../examples/assets/na-dashboard.png)

![/nodes endpoint showing two enrolled nodes with different remote addresses](../examples/assets/na-nodes.png)

---

Genesis Mesh supports local development startup and container-oriented Network
Authority startup.

```{mermaid}
flowchart TB
    subgraph host["Container Host"]
        secrets["Mounted secrets"]
        data["Durable DB volume"]
        container["Genesis Mesh container"]
    end

    ingress["Ingress on 8443"]
    gunicorn["Gunicorn"]
    flask["Network Authority app"]
    sqlite["SQLite DB"]

    secrets -->|GENESIS_FILE and NA_PRIVATE_KEY_FILE| container
    data -->|DB_PATH| sqlite
    ingress --> gunicorn
    gunicorn --> flask
    flask --> sqlite
    container --> gunicorn
```

## Local Development

Use the high-level CLI while developing or running smoke tests:

```bash
genesis-mesh init
genesis-mesh na start
genesis-mesh dev up
```

`genesis-mesh na start` uses the Flask local server and reads
`genesis-mesh.toml`. Production/container startup uses Gunicorn through
`start.sh`.

## Container Startup

The container entry point is `start.sh`. In Network Authority mode it runs
Gunicorn and requires mounted genesis and NA key files.

```bash
docker run --rm \
  -e SERVICE_ROLE=na \
  -e GENESIS_FILE=/run/secrets/genesis.signed.json \
  -e NA_PRIVATE_KEY_FILE=/run/secrets/na.key \
  -e OPERATOR_PUBLIC_KEYS_JSON='{"operator-local":"<base64-public-key>"}' \
  -e DB_PATH=/data/genesis_mesh_na.db \
  -p 8443:8443 \
  genesis-mesh:local
```

## Production Readiness Checks

Before production use, verify:

- the container starts as a non-root user
- required secret files are mounted
- startup fails when required secret files are missing
- `/healthz` and `/readyz` work behind the selected ingress
- SQLite data is persisted on durable storage
- backups are tested
- operator public keys are reviewed and rotated through policy
- logs do not expose private key material

## Container Smoke Checks

Build the image before release:

```bash
docker build -t genesis-mesh:local .
```

The container must fail closed when required Network Authority secrets are not
mounted:

```bash
docker run --rm genesis-mesh:local
```

Expected result: non-zero exit and a message containing `Refusing to start`.
With secrets mounted, the same image should serve `/healthz` and `/readyz`
through Gunicorn on port `8443`.

```bash
docker run --rm \
  -e SERVICE_ROLE=na \
  -e GENESIS_FILE=/run/secrets/genesis.signed.json \
  -e NA_PRIVATE_KEY_FILE=/run/secrets/na.key \
  -e DB_PATH=/data/genesis_mesh_na.db \
  -p 8443:8443 \
  genesis-mesh:local
```

Do not run two Network Authority processes against the same SQLite database
file. Genesis Mesh treats SQLite as a single-writer deployment store.

## Azure VM Deployment

The `infrastructure/azure/` directory contains a self-contained Terraform
configuration that provisions a complete Network Authority environment on Azure:
a resource group, virtual network, subnet, public IP, NSG, network interface,
and a Linux VM running Ubuntu 22.04.

The smallest supported VM size is **Standard_B1ms** (1 vCPU, 2 GB RAM). Run
Gunicorn with `WEB_CONCURRENCY=1` on that size.

### One-time setup

**Create a service principal:**

```bash
az ad sp create-for-rbac --name genesis-mesh-deploy \
  --role Contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>
```

Save the output — you need `clientId`, `clientSecret`, `subscriptionId`, and
`tenantId`.

**Create Terraform remote state storage:**

```bash
az group create -n terraform-state-rg -l swedencentral
az storage account create \
  -n tfstategenesismesh -g terraform-state-rg -l swedencentral --sku Standard_LRS
az storage container create -n tfstate --account-name tfstategenesismesh
```

### GitHub Actions deployment

The workflow lives at `.github/workflows/deploy-azure.yml`. It is triggered
manually from the Actions tab with a choice of `plan`, `apply`, or `destroy`.

**GitHub Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Value |
|--------|-------|
| `AZURE_CLIENT_ID` | `clientId` from service principal |
| `AZURE_CLIENT_SECRET` | `clientSecret` from service principal |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_TENANT_ID` | `tenantId` from service principal |
| `NA_SSH_PUBLIC_KEY` | Contents of `~/.ssh/id_rsa.pub` |
| `NA_ADMIN_CIDR` | Your IP as `x.x.x.x/32` for SSH access |

**GitHub Variables** (Settings → Secrets and variables → Actions → Variables):

| Variable | Value |
|----------|-------|
| `AZURE_LOCATION` | Azure region, e.g. `swedencentral` |
| `TF_STATE_RESOURCE_GROUP` | `terraform-state-rg` |
| `TF_STATE_STORAGE_ACCOUNT` | `tfstategenesismesh` |

**Running the workflow:**

1. Go to Actions → Deploy Network Authority to Azure → Run workflow.
2. Select `plan` and confirm the resources look correct.
3. Run again with `apply` to provision.
4. The workflow prints the public IP, SSH command, and NA endpoint on completion.

To tear down: run the workflow with `destroy`.

### Local Terraform run

If you prefer to run Terraform directly without the GitHub Action:

```bash
cd infrastructure/azure

terraform init \
  -backend-config="resource_group_name=terraform-state-rg" \
  -backend-config="storage_account_name=tfstategenesismesh" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=genesis-mesh-na.tfstate"

terraform plan \
  -var="ssh_public_key=$(cat ~/.ssh/id_rsa.pub)" \
  -var="admin_cidr=YOUR_IP/32"

terraform apply -auto-approve
```

Do not commit `terraform.tfvars` or `.terraform/` — they contain credentials
and provider binaries.
