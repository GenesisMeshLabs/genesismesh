# Terraform Deployment Guide

Genesis Mesh includes a provider-selectable Terraform module under
`infrastructure/`. Use it as a starting point for deploying a node host or
Network Authority host into an existing cloud network.

The module does not create a complete production environment by itself. It
expects you to provide cloud credentials, network IDs, image IDs, security
groups, and a secret-mounting strategy appropriate for the target provider.

## Validate the Module

Run validation from Linux, WSL, or a containerized Terraform runner:

```bash
cd infrastructure
terraform fmt -check -diff
terraform init -backend=false -input=false
terraform validate
```

Provider installation can fail if Terraform writes provider binaries directly
under a Windows-mounted filesystem. If that happens, copy `infrastructure/` to
a Linux temp directory and run the commands there.

## Plan a Generic SSH Target

The generic SSH path uses Terraform's `null_resource` provisioner and can be
planned without cloud provider credentials:

```bash
terraform plan \
  -refresh=false \
  -input=false \
  -target=null_resource.generic_ssh \
  -var='target_provider=generic_ssh' \
  -var='bootstrap_endpoint=https://na.example.com' \
  -var='genesis_uri=https://na.example.com/genesis.signed.json' \
  -var='generic_ssh_host=127.0.0.1' \
  -var='generic_ssh_private_key=dummy'
```

Use this only to validate Terraform shape. It is not a production deployment.

## Plan a Cloud Target

Before applying infrastructure for AWS, Azure, GCP, or Alibaba Cloud:

1. Authenticate to the cloud provider using the normal provider mechanism.
2. Provide real network IDs, image IDs, subnet or NIC IDs, and security groups.
3. Provide a reachable genesis URI and Network Authority bootstrap endpoint.
4. Decide how the host receives secrets such as the signed genesis block, NA
   private key, operator public keys, and database path.
5. Run `terraform plan` and review every resource before `terraform apply`.

Example shape:

```bash
terraform plan \
  -var='target_provider=azure' \
  -var='bootstrap_endpoint=https://na.example.com' \
  -var='genesis_uri=https://na.example.com/genesis.signed.json' \
  -var='azure_network_interface_id=/subscriptions/.../networkInterfaces/...' \
  -var='azure_resource_group_name=genesis-prod' \
  -var='azure_location=westeurope' \
  -var='azure_ssh_public_key=ssh-ed25519 ...'
```

Adjust the variables for the selected provider. Do not reuse the example values
as production input.

## Deployment Gate

A successful repository validation proves the Terraform files are syntactically
valid and provider schemas are satisfied. It does not prove that your cloud
account, network, image, firewall, DNS, ingress, and secret-mounting choices are
correct.

Treat a real `terraform plan` against the target account as a required release
gate before deployment.
