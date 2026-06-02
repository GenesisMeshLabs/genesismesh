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
#   - NA_VM_HOST
#   - NA_VM_SSH_PRIVATE_KEY or NA_VM_SSH_PRIVATE_KEY_FILE
#   - NA_VM_USER
#   - NA_VM_SSH_PORT

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

# Release CD defaults used by deploy-release-azure-vm.yml.
NA_VM_HOST="$(trim_crlf "${NA_VM_HOST:-}")"
NA_VM_USER="$(trim_crlf "${NA_VM_USER:-azureuser}")"
NA_VM_SSH_PORT="$(trim_crlf "${NA_VM_SSH_PORT:-22}")"

if ! [[ "$NA_VM_SSH_PORT" =~ ^[0-9]+$ ]]; then
  echo "ERROR: NA_VM_SSH_PORT must be numeric." >&2
  exit 1
fi

if [ -z "${NA_VM_SSH_PRIVATE_KEY:-}" ]; then
  if [ -n "${NA_VM_SSH_PRIVATE_KEY_FILE:-}" ]; then
    if [ -f "$NA_VM_SSH_PRIVATE_KEY_FILE" ]; then
      NA_VM_SSH_PRIVATE_KEY="$(cat "$NA_VM_SSH_PRIVATE_KEY_FILE")"
      echo "INFO: loaded NA_VM_SSH_PRIVATE_KEY from NA_VM_SSH_PRIVATE_KEY_FILE"
    else
      echo "ERROR: NA_VM_SSH_PRIVATE_KEY_FILE points to a missing file: $NA_VM_SSH_PRIVATE_KEY_FILE" >&2
      exit 1
    fi
  elif [ -f "$HOME/.ssh/id_rsa" ]; then
    NA_VM_SSH_PRIVATE_KEY="$(cat "$HOME/.ssh/id_rsa")"
    echo "INFO: loaded NA_VM_SSH_PRIVATE_KEY from ~/.ssh/id_rsa"
  elif [ -f "$HOME/.ssh/id_ed25519" ]; then
    NA_VM_SSH_PRIVATE_KEY="$(cat "$HOME/.ssh/id_ed25519")"
    echo "INFO: loaded NA_VM_SSH_PRIVATE_KEY from ~/.ssh/id_ed25519"
  fi
fi

CONFIGURE_RELEASE_VM=false
if [ -n "${NA_VM_HOST:-}" ] || [ -n "${NA_VM_SSH_PRIVATE_KEY:-}" ]; then
  if [ -z "${NA_VM_HOST:-}" ]; then
    echo "ERROR: NA_VM_HOST is required when configuring release VM deployment." >&2
    exit 1
  fi
  if [ -z "${NA_VM_SSH_PRIVATE_KEY:-}" ]; then
    echo "ERROR: NA_VM_SSH_PRIVATE_KEY or NA_VM_SSH_PRIVATE_KEY_FILE is required when configuring release VM deployment." >&2
    exit 1
  fi
  CONFIGURE_RELEASE_VM=true
else
  echo "INFO: release VM deployment values are not set; skipping release VM secrets."
fi

echo ""
echo "==> Setting GitHub Actions secrets"
"$GH_BIN" secret set AZURE_CLIENT_ID       --body "$AZURE_CLIENT_ID"
"$GH_BIN" secret set AZURE_SUBSCRIPTION_ID --body "$AZURE_SUBSCRIPTION_ID"
"$GH_BIN" secret set AZURE_TENANT_ID       --body "$AZURE_TENANT_ID"
"$GH_BIN" secret set NA_SSH_PUBLIC_KEY     --body "$NA_SSH_PUBLIC_KEY"
"$GH_BIN" secret set NA_ADMIN_CIDR         --body "$NA_ADMIN_CIDR"

if [ "$CONFIGURE_RELEASE_VM" = true ]; then
  "$GH_BIN" secret set NA_VM_HOST            --body "$NA_VM_HOST"
  "$GH_BIN" secret set NA_VM_SSH_PRIVATE_KEY --body "$NA_VM_SSH_PRIVATE_KEY"
fi

# Remove client secret - OIDC is used instead.
"$GH_BIN" secret delete AZURE_CLIENT_SECRET 2>/dev/null && echo "INFO: removed AZURE_CLIENT_SECRET" || true
echo "OK secrets set"

echo ""
echo "==> Setting GitHub Actions variables"
"$GH_BIN" variable set AZURE_LOCATION            --body "$AZURE_LOCATION"
"$GH_BIN" variable set TF_STATE_RESOURCE_GROUP   --body "$TF_STATE_RESOURCE_GROUP"
"$GH_BIN" variable set TF_STATE_STORAGE_ACCOUNT  --body "$TF_STATE_STORAGE_ACCOUNT"

if [ "$CONFIGURE_RELEASE_VM" = true ]; then
  "$GH_BIN" variable set NA_VM_USER     --body "$NA_VM_USER"
  "$GH_BIN" variable set NA_VM_SSH_PORT --body "$NA_VM_SSH_PORT"
fi
echo "OK variables set"

echo ""
echo "Done. Run the deploy workflow:"
echo "  gh workflow run deploy-azure.yml --field action=plan"
if [ "$CONFIGURE_RELEASE_VM" = true ]; then
  echo "  gh workflow run deploy-release-azure-vm.yml"
fi
