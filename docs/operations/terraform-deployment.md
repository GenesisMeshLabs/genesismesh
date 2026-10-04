# Terraform Deployment on Azure

The repository ships a self-contained Terraform module at
[`infrastructure/azure/`](https://github.com/GenesisMeshLabs/genesismesh/tree/main/infrastructure/azure)
that provisions a complete Network Authority environment on Azure.

This is the same module used by the public deployment at
[https://na.genesismesh.org](https://na.genesismesh.org).

## Architecture

```{mermaid}
flowchart TB
    tf["Terraform"]
    rg["Azure Resource Group"]
    vm["Ubuntu 22.04 VM"]
    runtime["Gunicorn (systemd service)"]
    app["Genesis Mesh Network Authority"]
    nginx["Nginx + TLS (Let's Encrypt)"]
    public["Public endpoint:8443/443"]

    tf --> rg
    rg --> vm
    vm --> runtime
    runtime --> app
    app --> nginx
    nginx --> public
```

Terraform provisions the cloud resources; everything from Gunicorn upward is
configured during the post-provisioning steps documented below.

## What It Creates

- Azure Resource Group
- Virtual Network and subnet
- Static Public IP (Standard SKU)
- Network Security Group (SSH from `admin_cidr`, HTTP/HTTPS, peer ports 7443/7444)
- Network Interface
- Ubuntu 22.04 Linux Virtual Machine (`Standard_B2ts_v2` default)
- Cloud-init that bootstraps Docker and the genesis-waiting service

```{mermaid}
flowchart TB
    subgraph rg["Resource Group: genesis-mesh-rg"]
        vnet["VNet 10.0.0.0/16"]
        subnet["Subnet 10.0.1.0/24"]
        pip["Public IP (Static, Standard)"]
        nsg["NSG: 22, 80, 443, 7443, 7444"]
        nic["Network Interface"]
        vm["Ubuntu 22.04 VM"]
    end

    vnet --> subnet
    subnet --> nic
    pip --> nic
    nsg --> nic
    nic --> vm
```

## One-time Setup

### Service principal

```bash
az ad sp create-for-rbac --name genesis-mesh-deploy \
  --role Contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>
```

Save `clientId`, `clientSecret`, `subscriptionId`, `tenantId`.

### Terraform remote state

```bash
az group create -n terraform-state-rg -l swedencentral
az storage account create \
  -n tfstategenesismesh -g terraform-state-rg -l swedencentral --sku Standard_LRS
az storage container create -n tfstate --account-name tfstategenesismesh
```

## Deploy via GitHub Actions

There is no Terraform workflow. Provision and change infrastructure with
Terraform locally (below). Code releases are deployed by the
**Deploy Release to Azure VM** workflow; see
[deployment](deployment.md#release-cd-to-the-azure-vm).

## Deploy Locally

If you prefer to run Terraform directly:

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

## After Apply

The Terraform output prints the public IP. Continue the post-provisioning
steps:

1. Install the Genesis Mesh package and Gunicorn on the VM.
2. Mount the signed genesis block and NA private key.
3. Register `genesis-mesh-na.service` with systemd (see the live deployment
   walkthrough in [deployment.md](deployment.md)).
4. Terminate TLS with Nginx + Certbot on a real domain.

## Multi-cloud Module

A separate provider-selectable module under
[`infrastructure/`](https://github.com/GenesisMeshLabs/genesismesh/tree/main/infrastructure)
includes Terraform shapes for AWS, GCP, Alibaba Cloud, and generic SSH. It is
useful as a starting point, but expects you to provide network IDs, image IDs,
security groups, and a secret-mounting strategy appropriate for the target
provider. The Azure VM module above is the only end-to-end working example
maintained by this repository.
