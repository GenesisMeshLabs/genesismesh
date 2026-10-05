# Deploys the published, signed image (ghcr.io/genesismeshlabs/genesis-mesh) at
# this checkout's VERSION, so run it from a release checkout; verify the image
# first (docs/operations/container-images.md). $env:IMAGE overrides it (prefer a
# digest). $env:BUILD_FROM_SOURCE = "true" builds this checkout in an Azure
# Container Registry instead.
#
# Inputs, as environment variables (the private ones become Container Apps
# secrets, never plain settings):
#   GENESIS_FILE         the sovereign's signed genesis block (required)
#   NA_SEED_FILE         a file holding the NA key's base64 seed (required)
#   NA_KEY_ID            the key ID in the NA key file (default na-local)
#   OPERATOR_PUBLIC_KEYS_JSON, OPERATOR_KEY_TIERS_JSON   (required for admin APIs)
#   DATABASE_URL         PostgreSQL URL; without it the NA keeps SQLite state in
#                        the container, which a new revision starts without
#   INVITE_TOKEN         when set, also deploys a mesh node enrolled with it
$ErrorActionPreference = "Stop"

$APP_NAME = "genesis-mesh"
$LOCATION = "swedencentral"
$RESOURCE_GROUP = "rg-$APP_NAME"
$ACR_NAME = "acr" + $APP_NAME.Replace("-", "")
$ENV_NAME = "env-$APP_NAME"
$ALB_NAME = "ca-$APP_NAME-na"
$WORKER_NAME = "ca-$APP_NAME-node"
$REPO_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$IMAGE_TAG = (Get-Content (Join-Path $REPO_ROOT "VERSION") -Raw).Trim()
$IMAGE = if ($env:IMAGE) { $env:IMAGE } else { "ghcr.io/genesismeshlabs/genesis-mesh:$IMAGE_TAG" }
$BUILD_FROM_SOURCE = $env:BUILD_FROM_SOURCE -eq "true"
$REGISTRY_ARGS = @()
$PORT = "8443"
$NA_KEY_ID = if ($env:NA_KEY_ID) { $env:NA_KEY_ID } else { "na-local" }
$OPERATOR_PUBLIC_KEYS_JSON = if ($env:OPERATOR_PUBLIC_KEYS_JSON) { $env:OPERATOR_PUBLIC_KEYS_JSON } else { "{}" }
# Each operator key needs a tier (read|standard|privileged); the NA refuses to start
# if a configured key has none.
$OPERATOR_KEY_TIERS_JSON = if ($env:OPERATOR_KEY_TIERS_JSON) { $env:OPERATOR_KEY_TIERS_JSON } else { "{}" }

foreach ($required in @("GENESIS_FILE", "NA_SEED_FILE")) {
  $path = [Environment]::GetEnvironmentVariable($required)
  if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Set $required to an existing file (see the header of this script)."
  }
}
$GENESIS_JSON = (Get-Content -LiteralPath $env:GENESIS_FILE -Raw).Trim()
$NA_SEED = ((Get-Content -LiteralPath $env:NA_SEED_FILE) | Where-Object { $_ -notmatch '^#' } | ForEach-Object { $_.Trim() }) -join ""

# az is az.cmd on Windows, where PowerShell passes embedded double quotes
# without escaping them; escape them so JSON values arrive intact.
function NativeArg([string]$value) {
  if ($PSVersionTable.PSVersion.Major -lt 6 -or $IsWindows) { return $value -replace '"', '\"' }
  return $value
}

Write-Host "=== Starting Deployment for $APP_NAME ==="
Write-Host "Location: $LOCATION"
Write-Host "Resource Group: $RESOURCE_GROUP"

# 1. Create Resource Group
Write-Host "Creating Resource Group..."
az group create --name $RESOURCE_GROUP --location $LOCATION

# 2-3. Optionally build this checkout in ACR
if ($BUILD_FROM_SOURCE) {
  Write-Host "Creating Azure Container Registry..."
  az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true

  Write-Host "Building and Pushing Docker Image..."
  az acr build --registry $ACR_NAME --image "$APP_NAME`:$IMAGE_TAG" "$REPO_ROOT"
  $IMAGE = "$ACR_NAME.azurecr.io/$APP_NAME`:$IMAGE_TAG"
  $REGISTRY_ARGS = @("--registry-server", "$ACR_NAME.azurecr.io")
}
Write-Host "Image: $IMAGE"

# 4. Create CA Env
Write-Host "Creating Container Apps Environment..."
az containerapp env create --name $ENV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION

# 5. Deploy NA
# The genesis block and the seed are Container Apps secrets; start.sh moves
# them out of the server processes' environment. Ingress terminates TLS.
Write-Host "Deploying Network Authority (NA) Service..."
$SECRETS = @((NativeArg "genesis-json=$GENESIS_JSON"), "na-seed=$NA_SEED")
$DATABASE_ARGS = @()
if ($env:DATABASE_URL) {
  $SECRETS += "database-url=$($env:DATABASE_URL)"
  $DATABASE_ARGS = @("DATABASE_URL=secretref:database-url")
}
az containerapp create `
  --name $ALB_NAME `
  --resource-group $RESOURCE_GROUP `
  --environment $ENV_NAME `
  --image $IMAGE `
  --target-port $PORT `
  --ingress external `
  --secrets @SECRETS `
  --env-vars SERVICE_ROLE=na PORT=$PORT NA_PROXY_HOPS=1 `
    GENESIS_JSON=secretref:genesis-json `
    NA_KEY_PROVIDER=env NA_PRIVATE_KEY_SEED=secretref:na-seed NA_KEY_ID=$NA_KEY_ID `
    (NativeArg "OPERATOR_PUBLIC_KEYS_JSON=$OPERATOR_PUBLIC_KEYS_JSON") `
    (NativeArg "OPERATOR_KEY_TIERS_JSON=$OPERATOR_KEY_TIERS_JSON") `
    @DATABASE_ARGS `
  @REGISTRY_ARGS `
  --min-replicas 1 `
  --max-replicas 1

# Get FQDN
$NA_FQDN = az containerapp show --name $ALB_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv
$NA_URL = "https://$NA_FQDN"
Write-Host "Network Authority URL: $NA_URL"

# 6. Deploy a Mesh Node, when an invite token is given
if ($env:INVITE_TOKEN) {
  Write-Host "Deploying Mesh Node..."
  az containerapp create `
    --name $WORKER_NAME `
    --resource-group $RESOURCE_GROUP `
    --environment $ENV_NAME `
    --image $IMAGE `
    --secrets (NativeArg "genesis-json=$GENESIS_JSON") "invite-token=$($env:INVITE_TOKEN)" `
    --env-vars SERVICE_ROLE=node BOOTSTRAP_URL=$NA_URL NODE_ROLE=anchor `
      GENESIS_JSON=secretref:genesis-json INVITE_TOKEN=secretref:invite-token `
    @REGISTRY_ARGS `
    --min-replicas 1 `
    --max-replicas 1
} else {
  Write-Host "No INVITE_TOKEN: skipping the mesh node (create an invite on the NA, then rerun with it)."
}

Write-Host "=== Deployment Complete ==="
Write-Host "NA Service: $NA_URL"
if (-not $env:DATABASE_URL) {
  Write-Host "State is SQLite inside the container: set DATABASE_URL (PostgreSQL) to keep it across revisions."
}
