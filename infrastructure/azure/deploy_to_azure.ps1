$ErrorActionPreference = "Stop"

$APP_NAME = "genesis-mesh"
$LOCATION = "swedencentral"
$RESOURCE_GROUP = "rg-$APP_NAME"
$ACR_NAME = "acr" + $APP_NAME.Replace("-", "")
$ENV_NAME = "env-$APP_NAME"
$ALB_NAME = "ca-$APP_NAME-na"
$WORKER_NAME = "ca-$APP_NAME-node"
$IMAGE_TAG = "latest"
$REPO_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$GENESIS_FILE = "genesis.signed.json"
$NA_PRIVATE_KEY_FILE = "keys/na.key"
$DB_PATH = "genesis_mesh_na.db"
$PORT = "8443"
$OPERATOR_PUBLIC_KEYS_JSON = if ($env:OPERATOR_PUBLIC_KEYS_JSON) { $env:OPERATOR_PUBLIC_KEYS_JSON } else { "{}" }

Write-Host "=== Starting Deployment for $APP_NAME ==="
Write-Host "Location: $LOCATION"
Write-Host "Resource Group: $RESOURCE_GROUP"

# 1. Create Resource Group
Write-Host "Creating Resource Group..."
az group create --name $RESOURCE_GROUP --location $LOCATION

# 2. Create ACR
Write-Host "Creating Azure Container Registry..."
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true

# 3. Build Image
Write-Host "Building and Pushing Docker Image..."
az acr build --registry $ACR_NAME --image "$APP_NAME`:$IMAGE_TAG" "$REPO_ROOT"

# 4. Create CA Env
Write-Host "Creating Container Apps Environment..."
az containerapp env create --name $ENV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION

# 5. Deploy NA
Write-Host "Deploying Network Authority (NA) Service..."
az containerapp create `
  --name $ALB_NAME `
  --resource-group $RESOURCE_GROUP `
  --environment $ENV_NAME `
  --image "$ACR_NAME.azurecr.io/$APP_NAME`:$IMAGE_TAG" `
  --target-port $PORT `
  --ingress external `
  --env-vars SERVICE_ROLE=na GENESIS_FILE=$GENESIS_FILE NA_PRIVATE_KEY_FILE=$NA_PRIVATE_KEY_FILE DB_PATH=$DB_PATH PORT=$PORT OPERATOR_PUBLIC_KEYS_JSON=$OPERATOR_PUBLIC_KEYS_JSON `
  --registry-server "$ACR_NAME.azurecr.io" `
  --min-replicas 1 `
  --max-replicas 1

# Get FQDN
$NA_FQDN = az containerapp show --name $ALB_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv
$NA_URL = "https://$NA_FQDN"
Write-Host "Network Authority URL: $NA_URL"

# 6. Deploy Node
Write-Host "Deploying Mesh Node..."
az containerapp create `
  --name $WORKER_NAME `
  --resource-group $RESOURCE_GROUP `
  --environment $ENV_NAME `
  --image "$ACR_NAME.azurecr.io/$APP_NAME`:$IMAGE_TAG" `
  --env-vars SERVICE_ROLE=node BOOTSTRAP_URL=$NA_URL NODE_ROLE=anchor `
  --registry-server "$ACR_NAME.azurecr.io" `
  --min-replicas 1 `
  --max-replicas 1

Write-Host "=== Deployment Complete ==="
Write-Host "NA Service: $NA_URL"
