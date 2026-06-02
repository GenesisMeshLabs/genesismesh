#!/usr/bin/env bash
# Push GitHub Actions secrets and variables from .env.
# Usage: bash infrastructure/scripts/setup-github-secrets.sh
#
# Prerequisites:
#   - gh CLI installed and authenticated (gh auth login)
#   - .env file filled in at the repo root
#   - NA_SSH_PUBLIC_KEY and NA_ADMIN_CIDR set in .env or auto-detectable
#
# Optional release VM deployment values:
#   - AZURE_RESOURCE_GROUP
#   - AZURE_VM_NAME
#
# Release deployment uses Azure Run Command through OIDC. It does not require
# an inbound SSH rule from GitHub Actions or a VM SSH private key in GitHub.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

# Git Bash non-login shells do not always include ~/.local/bin.
PATH="$HOME/.local/bin:$PATH"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

# Load .env (skip comments and blank lines).
set -o allexport
# shellcheck source=/dev/null
source <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | tr -d '\r')
set +o allexport

GH_BIN="$(command -v gh || command -v gh.exe || true)"
if [ -z "$GH_BIN" ]; then
  echo "ERROR: GitHub CLI is not on PATH. Install gh and run 'gh auth login'." >&2
  exit 1
fi

trim_crlf() {
  printf '%s' "$1" | tr -d '\r\n'
}

# Auto-populate SSH public key from ~/.ssh if not set in .env.
if [ -z "${NA_SSH_PUBLIC_KEY:-}" ]; then
  if [ -f "$HOME/.ssh/id_rsa.pub" ]; then
    NA_SSH_PUBLIC_KEY="$(cat "$HOME/.ssh/id_rsa.pub")"
    echo "INFO: loaded NA_SSH_PUBLIC_KEY from ~/.ssh/id_rsa.pub"
  elif [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
    NA_SSH_PUBLIC_KEY="$(cat "$HOME/.ssh/id_ed25519.pub")"
    echo "INFO: loaded NA_SSH_PUBLIC_KEY from ~/.ssh/id_ed25519.pub"
  else
    echo "ERROR: NA_SSH_PUBLIC_KEY is not set and no default SSH public key exists." >&2
    exit 1
  fi
fi

# Auto-populate admin CIDR from current public IP if not set in .env.
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

# Release CD values used by deploy-release-azure-vm.yml.
AZURE_RESOURCE_GROUP="$(trim_crlf "${AZURE_RESOURCE_GROUP:-}")"
AZURE_VM_NAME="$(trim_crlf "${AZURE_VM_NAME:-}")"
CONFIGURE_RELEASE_VM=false
if [ -n "$AZURE_RESOURCE_GROUP" ] || [ -n "$AZURE_VM_NAME" ]; then
  if [ -z "$AZURE_RESOURCE_GROUP" ]; then
    echo "ERROR: AZURE_RESOURCE_GROUP is required when configuring release VM deployment." >&2
    exit 1
  fi
  if [ -z "$AZURE_VM_NAME" ]; then
    echo "ERROR: AZURE_VM_NAME is required when configuring release VM deployment." >&2
    exit 1
  fi
  CONFIGURE_RELEASE_VM=true
else
  echo "INFO: AZURE_RESOURCE_GROUP/AZURE_VM_NAME not set; skipping release VM variables."
fi

echo ""
echo "==> Setting GitHub Actions secrets"
"$GH_BIN" secret set AZURE_CLIENT_ID       --body "$AZURE_CLIENT_ID"
"$GH_BIN" secret set AZURE_SUBSCRIPTION_ID --body "$AZURE_SUBSCRIPTION_ID"
"$GH_BIN" secret set AZURE_TENANT_ID       --body "$AZURE_TENANT_ID"
"$GH_BIN" secret set NA_SSH_PUBLIC_KEY     --body "$NA_SSH_PUBLIC_KEY"
"$GH_BIN" secret set NA_ADMIN_CIDR         --body "$NA_ADMIN_CIDR"

# Remove client secret - OIDC is used instead.
"$GH_BIN" secret delete AZURE_CLIENT_SECRET 2>/dev/null && echo "INFO: removed AZURE_CLIENT_SECRET" || true
echo "OK secrets set"

echo ""
echo "==> Setting GitHub Actions variables"
"$GH_BIN" variable set AZURE_LOCATION            --body "$AZURE_LOCATION"
"$GH_BIN" variable set TF_STATE_RESOURCE_GROUP   --body "$TF_STATE_RESOURCE_GROUP"
"$GH_BIN" variable set TF_STATE_STORAGE_ACCOUNT  --body "$TF_STATE_STORAGE_ACCOUNT"

if [ "$CONFIGURE_RELEASE_VM" = true ]; then
  "$GH_BIN" variable set AZURE_RESOURCE_GROUP --body "$AZURE_RESOURCE_GROUP"
  "$GH_BIN" variable set AZURE_VM_NAME         --body "$AZURE_VM_NAME"
fi
echo "OK variables set"

echo ""
echo "Done. Run the deploy workflow:"
echo "  gh workflow run deploy-azure.yml --field action=plan"
if [ "$CONFIGURE_RELEASE_VM" = true ]; then
  echo "  gh workflow run deploy-release-azure-vm.yml"
fi
