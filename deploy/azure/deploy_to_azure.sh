#!/bin/bash
set -euo pipefail

# ==================================================================================
# Genesis Mesh - Azure Deployment Script
#
# This script uses the Azure CLI to provision resources and deploy the application.
# It assumes you are logged in (az login) and have a subscription selected.
#
# It deploys the published, signed image (ghcr.io/genesismeshlabs/genesis-mesh)
# at this checkout's VERSION, so run it from a release checkout; verify the image
# first (docs/operations/container-images.md). IMAGE overrides it (prefer a
# digest). BUILD_FROM_SOURCE=true builds this checkout in an Azure Container
# Registry instead.
#
# Inputs (the private ones become Container Apps secrets, never plain settings):
#   GENESIS_FILE         the sovereign's signed genesis block (required)
#   NA_SEED_FILE         a file holding the NA key's base64 seed (required)
#   NA_KEY_ID            the key ID in the NA key file (default na-local)
#   OPERATOR_PUBLIC_KEYS_JSON, OPERATOR_KEY_TIERS_JSON   (required for admin APIs)
#   DATABASE_URL         PostgreSQL URL; without it the NA keeps SQLite state in
#                        the container, which a new revision starts without
#   INVITE_TOKEN         when set, also deploys a mesh node enrolled with it
# ==================================================================================

# Configuration Variables
APP_NAME="genesis-mesh"
LOCATION="swedencentral"  # Change this to your preferred region (e.g., eastus)
RESOURCE_GROUP="rg-${APP_NAME}"
ACR_NAME="acr${APP_NAME//-/}" # registry names must be alphanumeric
ENV_NAME="env-${APP_NAME}"
ALB_NAME="ca-${APP_NAME}-na"
WORKER_NAME="ca-${APP_NAME}-node"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
IMAGE_TAG="$(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")"
IMAGE="${IMAGE:-ghcr.io/genesismeshlabs/genesis-mesh:${IMAGE_TAG}}"
BUILD_FROM_SOURCE="${BUILD_FROM_SOURCE:-false}"
REGISTRY_ARGS=()
PORT="8443"
NA_KEY_ID="${NA_KEY_ID:-na-local}"
OPERATOR_PUBLIC_KEYS_JSON="${OPERATOR_PUBLIC_KEYS_JSON:-"{}"}"
# F-21: each operator key needs a tier (read|standard|privileged); the NA refuses
# to start if a configured key has none.
OPERATOR_KEY_TIERS_JSON="${OPERATOR_KEY_TIERS_JSON:-"{}"}"

for required in GENESIS_FILE NA_SEED_FILE; do
  if [ -z "${!required:-}" ] || [ ! -f "${!required}" ]; then
    echo "ERROR: set $required to an existing file (see the header of this script)." >&2
    exit 1
  fi
done
GENESIS_JSON="$(cat "$GENESIS_FILE")"
NA_SEED="$(grep -v '^#' "$NA_SEED_FILE" | tr -d '[:space:]')"

echo "=== Starting Deployment for $APP_NAME ==="
echo "Location: $LOCATION"
echo "Resource Group: $RESOURCE_GROUP"

# 1. Create Resource Group
echo "Creating Resource Group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# 2-3. Optionally build this checkout in an Azure Container Registry (ACR)
if [ "$BUILD_FROM_SOURCE" = "true" ]; then
  echo "Creating Azure Container Registry..."
  az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku Basic \
    --admin-enabled true

  echo "Building and Pushing Docker Image..."
  # Using az acr build to build in the cloud (avoids local docker issues)
  az acr build --registry "$ACR_NAME" --image "${APP_NAME}:${IMAGE_TAG}" "$REPO_ROOT"
  IMAGE="$ACR_NAME.azurecr.io/${APP_NAME}:${IMAGE_TAG}"
  REGISTRY_ARGS=(--registry-server "$ACR_NAME.azurecr.io")
fi
echo "Image: $IMAGE"

# 4. Create Container Apps Environment
echo "Creating Container Apps Environment..."
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

# 5. Deploy Network Authority (NA) Service
# The genesis block and the seed are Container Apps secrets; start.sh moves
# them out of the server processes' environment. Ingress terminates TLS.
echo "Deploying Network Authority (NA) Service..."
SECRETS=("genesis-json=$GENESIS_JSON" "na-seed=$NA_SEED")
DATABASE_ARGS=()
if [ -n "${DATABASE_URL:-}" ]; then
  SECRETS+=("database-url=$DATABASE_URL")
  DATABASE_ARGS=("DATABASE_URL=secretref:database-url")
fi
az containerapp create \
  --name "$ALB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$IMAGE" \
  --target-port "$PORT" \
  --ingress external \
  --secrets "${SECRETS[@]}" \
  --env-vars SERVICE_ROLE=na PORT="$PORT" NA_PROXY_HOPS=1 \
    GENESIS_JSON=secretref:genesis-json \
    NA_KEY_PROVIDER=env NA_PRIVATE_KEY_SEED=secretref:na-seed NA_KEY_ID="$NA_KEY_ID" \
    OPERATOR_PUBLIC_KEYS_JSON="$OPERATOR_PUBLIC_KEYS_JSON" OPERATOR_KEY_TIERS_JSON="$OPERATOR_KEY_TIERS_JSON" \
    ${DATABASE_ARGS[@]+"${DATABASE_ARGS[@]}"} \
  ${REGISTRY_ARGS[@]+"${REGISTRY_ARGS[@]}"} \
  --min-replicas 1 \
  --max-replicas 1

# Get the FQDN of the NA service
NA_FQDN=$(az containerapp show --name "$ALB_NAME" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)
NA_URL="https://${NA_FQDN}"

echo "Network Authority URL: $NA_URL"

# 6. Deploy a Mesh Node (Worker), when an invite token is given.
if [ -n "${INVITE_TOKEN:-}" ]; then
  echo "Deploying Mesh Node..."
  az containerapp create \
    --name "$WORKER_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENV_NAME" \
    --image "$IMAGE" \
    --secrets "genesis-json=$GENESIS_JSON" "invite-token=$INVITE_TOKEN" \
    --env-vars SERVICE_ROLE=node BOOTSTRAP_URL="$NA_URL" \
      GENESIS_JSON=secretref:genesis-json INVITE_TOKEN=secretref:invite-token \
    ${REGISTRY_ARGS[@]+"${REGISTRY_ARGS[@]}"} \
    --min-replicas 1 \
    --max-replicas 1
else
  echo "No INVITE_TOKEN: skipping the mesh node (create an invite on the NA, then rerun with it)."
fi

echo "=== Deployment Complete ==="
echo "NA Service: $NA_URL"
if [ -z "${DATABASE_URL:-}" ]; then
  echo "State is SQLite inside the container: set DATABASE_URL (PostgreSQL) to keep it across revisions."
fi
