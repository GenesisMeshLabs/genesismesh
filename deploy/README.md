# Deploying the Network Authority

Ready-to-adapt deployment files for operators. They track the release they
ship with; start from the files of the release you deploy.

| Folder | What |
| --- | --- |
| `compose/` | Docker Compose: `docker-compose.images.yml` (the signed images: Network Authority and gateway), `docker-compose.na.yml` (a Network Authority built from this checkout) and `ha/` (two instances on PostgreSQL behind nginx; see *High Availability* in the docs) |
| `kubernetes/` | Kubernetes manifests for the published image; see `kubernetes/README.md` |
| `azure/` | Azure: Container Apps helper scripts (below) and a Terraform module for a VM (see *Terraform Deployment* in the docs) |

The image itself (`Dockerfile`, `start.sh`, `docker/healthcheck.sh`) stays at
the repository root, because each release builds it from its own tag. The
gateway's deployment files are in the gateway repository's `deploy/` folder.

## Azure Container Apps


The helper scripts in `azure/` deploy the Network Authority to Azure Container Apps:

```powershell
.\deploy\azure\deploy_to_azure.ps1
```

```bash
bash deploy/azure/deploy_to_azure.sh
```

The scripts deploy the published image at this checkout's `VERSION` (`IMAGE`
overrides it; `BUILD_FROM_SOURCE=true` builds the checkout in an Azure
Container Registry) and target port `8443`. They take their inputs from the environment: `GENESIS_FILE` (the signed
genesis block) and `NA_SEED_FILE` (a file holding the NA key's base64 seed)
are required and become Container Apps secrets, handed to the image as
`GENESIS_JSON` and `NA_PRIVATE_KEY_SEED` (`start.sh` moves both out of the
server processes' environment). `NA_KEY_ID` (default `na-local`),
`OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON` configure the
Network Authority; every operator key needs a tier (`read`, `standard`
or `privileged`). Without `DATABASE_URL` (PostgreSQL, also passed as a secret)
the state is SQLite inside the container, which a new revision starts
without. With `INVITE_TOKEN`, the scripts also deploy a mesh node enrolled
with it. Run them from a release checkout, since the image tag comes from
`VERSION`.
