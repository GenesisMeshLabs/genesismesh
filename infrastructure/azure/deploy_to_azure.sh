#!/bin/bash
set -e

# ==================================================================================
# Genesis Mesh - Azure Deployment Script
# 
# This script uses the Azure CLI to provision resources and deploy the application.
# It assumes you are logged in (az login) and have a subscription selected.
# ==================================================================================

# Configuration Variables
APP_NAME="genesis-mesh"
LOCATION="swedencentral"  # Change this to your preferred region (e.g., eastus)
RESOURCE_GROUP="rg-${APP_NAME}"
ACR_NAME="acr${APP_NAME//-/}" # registry names must be alphanumeric
ENV_NAME="env-${APP_NAME}"
ALB_NAME="ca-${APP_NAME}-na"
WORKER_NAME="ca-${APP_NAME}-node"
IMAGE_TAG="latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GENESIS_FILE="${GENESIS_FILE:-genesis.signed.json}"
NA_PRIVATE_KEY_FILE="${NA_PRIVATE_KEY_FILE:-keys/na.key}"
DB_PATH="${DB_PATH:-genesis_mesh_na.db}"
PORT="${PORT:-8443}"
OPERATOR_PUBLIC_KEYS_JSON="${OPERATOR_PUBLIC_KEYS_JSON:-{}}"

echo "=== Starting Deployment for $APP_NAME ==="
echo "Location: $LOCATION"
echo "Resource Group: $RESOURCE_GROUP"

# 1. Create Resource Group
echo "Creating Resource Group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# 2. Create Azure Container Registry (ACR)
echo "Creating Azure Container Registry..."
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true

# 3. Build and Push Docker Image
echo "Building and Pushing Docker Image..."
# Using az acr build to build in the cloud (avoids local docker issues)
az acr build --registry "$ACR_NAME" --image "${APP_NAME}:${IMAGE_TAG}" "$REPO_ROOT"

# 4. Create Container Apps Environment
echo "Creating Container Apps Environment..."
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

# 5. Deploy Network Authority (NA) Service
echo "Deploying Network Authority (NA) Service..."
# We enable ingress for the NA service so nodes can connect to it.
az containerapp create \
  --name "$ALB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_NAME.azurecr.io/${APP_NAME}:${IMAGE_TAG}" \
  --target-port "$PORT" \
  --ingress external \
  --env-vars SERVICE_ROLE=na GENESIS_FILE="$GENESIS_FILE" NA_PRIVATE_KEY_FILE="$NA_PRIVATE_KEY_FILE" DB_PATH="$DB_PATH" PORT="$PORT" OPERATOR_PUBLIC_KEYS_JSON="$OPERATOR_PUBLIC_KEYS_JSON" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --min-replicas 1 \
  --max-replicas 1

# Get the FQDN of the NA service
NA_FQDN=$(az containerapp show --name "$ALB_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)
NA_URL="https://${NA_FQDN}"

echo "Network Authority URL: $NA_URL"

# 6. Deploy Mesh Node (Worker)
# The worker needs to know where the NA is to bootstrap.
# Node startup uses environment variables through start.sh.

echo "Deploying Mesh Node..."
az containerapp create \
  --name "$WORKER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$ACR_NAME.azurecr.io/${APP_NAME}:${IMAGE_TAG}" \
  --env-vars SERVICE_ROLE=node BOOTSTRAP_URL="$NA_URL" \
  --registry-server "$ACR_NAME.azurecr.io" \
  --min-replicas 1 \
  --max-replicas 1

echo "=== Deployment Complete ==="
echo "NA Service: $NA_URL"
echo "Mount production genesis and NA key files before using this in production."
