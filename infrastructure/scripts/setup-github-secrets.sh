#!/usr/bin/env bash
# Push GitHub Actions secrets and variables from .env
# Usage: bash infrastructure/scripts/setup-github-secrets.sh
#
# Prerequisites:
#   - gh CLI installed and authenticated (gh auth login)
#   - .env file filled in at the repo root
#   - NA_SSH_PUBLIC_KEY and NA_ADMIN_CIDR set in .env

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

# Load .env (skip comments and blank lines)
set -o allexport
# shellcheck source=/dev/null
source <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$')
set +o allexport

# Auto-populate SSH public key from ~/.ssh/id_rsa.pub if not set in .env
if [ -z "${NA_SSH_PUBLIC_KEY:-}" ]; then
  if [ -f "$HOME/.ssh/id_rsa.pub" ]; then
    NA_SSH_PUBLIC_KEY="$(cat "$HOME/.ssh/id_rsa.pub")"
    echo "INFO: loaded NA_SSH_PUBLIC_KEY from ~/.ssh/id_rsa.pub"
  else
    echo "ERROR: NA_SSH_PUBLIC_KEY is not set and ~/.ssh/id_rsa.pub does not exist." >&2
    exit 1
  fi
fi

# Auto-populate admin CIDR from current public IP if not set in .env
if [ -z "${NA_ADMIN_CIDR:-}" ]; then
  MY_IP="$(curl -sf https://api.ipify.org)"
  if [ -n "$MY_IP" ]; then
    NA_ADMIN_CIDR="${MY_IP}/32"
    echo "INFO: detected NA_ADMIN_CIDR as $NA_ADMIN_CIDR"
  else
    echo "ERROR: NA_ADMIN_CIDR is not set and could not detect public IP." >&2
    exit 1
  fi
fi

echo ""
echo "==> Setting GitHub Actions secrets"
gh secret set AZURE_CLIENT_ID       --body "$AZURE_CLIENT_ID"
gh secret set AZURE_SUBSCRIPTION_ID --body "$AZURE_SUBSCRIPTION_ID"
gh secret set AZURE_TENANT_ID       --body "$AZURE_TENANT_ID"
gh secret set NA_SSH_PUBLIC_KEY     --body "$NA_SSH_PUBLIC_KEY"
gh secret set NA_ADMIN_CIDR         --body "$NA_ADMIN_CIDR"

# Remove client secret — OIDC is used instead
gh secret delete AZURE_CLIENT_SECRET 2>/dev/null && echo "INFO: removed AZURE_CLIENT_SECRET" || true
echo "OK secrets set"

echo ""
echo "==> Setting GitHub Actions variables"
gh variable set AZURE_LOCATION            --body "$AZURE_LOCATION"
gh variable set TF_STATE_RESOURCE_GROUP   --body "$TF_STATE_RESOURCE_GROUP"
gh variable set TF_STATE_STORAGE_ACCOUNT  --body "$TF_STATE_STORAGE_ACCOUNT"
echo "OK variables set"

echo ""
echo "Done. Run the deploy workflow:"
echo "  gh workflow run deploy-azure.yml --field action=plan"
