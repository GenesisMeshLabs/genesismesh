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

- `Dockerfile`: kept at the repository root so Docker and Azure Container
  Registry builds can use the whole repository as the build context.
- `start.sh`: kept at the repository root because the Docker image entry point
  invokes it directly.
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

## Azure Scripts

The Azure helper scripts live in `infrastructure/azure/` and build from the
repository root automatically:

```powershell
.\infrastructure\azure\deploy_to_azure.ps1
```

```bash
bash infrastructure/azure/deploy_to_azure.sh
```

Both scripts target port `8443`, matching the Docker image and `start.sh`. The
scripts set the expected environment variable names; production environments
still need to mount the genesis and NA key files at those configured paths.
