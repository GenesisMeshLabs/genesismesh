# Infrastructure

Infrastructure and deployment assets live under `infrastructure/` so the
repository root stays focused on package, build, and runtime entry files.

## Directory Layout

```text
infrastructure/
  README.md             Terraform module usage and provider notes
  main.tf               Polymorphic Terraform module
  variables.tf          Terraform inputs
  outputs.tf            Terraform outputs
  universal_boot.sh     Cloud-init and remote bootstrap script
  azure/
    deploy_to_azure.ps1 Azure Container Apps deployment script
    deploy_to_azure.sh  Azure Container Apps deployment script
  scripts/
    verify_flow.ps1     Local cryptographic CLI smoke flow
```

## Root Files Kept Intentionally

- `Dockerfile`: the Network Authority image, published signed for each
  release as `ghcr.io/genesismeshlabs/genesis-mesh` (see
  [Container Images](container-images.md)). It builds from the repository
  root; `.dockerignore` admits only the package, `start.sh` and the lock
  files, never keys, `.env` files or databases.
- `start.sh`: the image's entry point, kept at the repository root.
- `requirements.txt`, `setup.py`, `pytest.ini`, and `README.md`: package and
  development entry files.

## Sample Genesis Files

Sample genesis artifacts live in `examples/genesis/`:

- `examples/genesis/genesis.json`
- `examples/genesis/genesis.signed.json`

Production deployments should mount their own signed genesis block and NA
private key as secrets. The production startup path fails closed when those
files are missing.

Operator public keys are not private secrets, but they are security-critical
configuration. Container deployments pass them to the WSGI app with
`OPERATOR_PUBLIC_KEYS_JSON`, formatted as a JSON object from operator key ID to
base64 public key.

Each key must also be assigned a tier via `OPERATOR_KEY_TIERS_JSON`, a JSON
object from operator key ID to `read`, `standard` or `privileged`. There is no default:
the Network Authority refuses to start if any configured key has no tier.

## Azure Scripts

The Azure helper scripts live in `deploy/azure/`. They deploy the
published image at this checkout's `VERSION` to Azure Container Apps (set
`IMAGE` to deploy another reference, ideally a digest). With
`BUILD_FROM_SOURCE=true` they build this checkout in an Azure Container
Registry instead:

```powershell
.\infrastructure\azure\deploy_to_azure.ps1
```

```bash
bash deploy/azure/deploy_to_azure.sh
```

Both scripts target port `8443`, matching the image and `start.sh`. They take their inputs from the environment: `GENESIS_FILE` (the signed
genesis block) and `NA_SEED_FILE` (a file holding the NA key's base64 seed)
are required and become Container Apps secrets, handed to the image as
`GENESIS_JSON` and `NA_PRIVATE_KEY_SEED` (`start.sh` moves both out of the
server processes' environment). `NA_KEY_ID` (default `na-local`),
`OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON` configure the
Network Authority; every operator key needs a tier (`standard` or
`privileged`). Without `DATABASE_URL` (PostgreSQL, also passed as a secret)
the state is SQLite inside the container, which a new revision starts
without. With `INVITE_TOKEN`, the scripts also deploy a mesh node enrolled
with it. Run them from a release checkout, since the image tag comes from
`VERSION`.

## Terraform Verification

Run Terraform checks from a Linux filesystem, WSL, or a containerized Terraform
runner. Installing providers directly under a Windows-mounted path can fail on
provider executable permissions.

```bash
cd infrastructure
terraform fmt -check -diff
terraform init -backend=false -input=false
terraform validate
```

The generic SSH path can be planned without cloud credentials by targeting the
`null_resource`:

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

Before deploying to AWS, Azure, GCP, or Alibaba Cloud, run a real
`terraform plan` for that provider with the intended cloud credentials,
network IDs, image IDs, security groups, and secret-mounting strategy. Treat
that cloud-specific plan as a deployment gate; the repository cannot verify it
without access to the target account.
