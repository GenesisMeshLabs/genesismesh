#!/usr/bin/env bash
# Build the package and publish to TestPyPI or PyPI.
#
# Usage:
#   bash infrastructure/scripts/publish-package.sh test     # → TestPyPI
#   bash infrastructure/scripts/publish-package.sh prod     # → real PyPI
#
# Tokens are read from .env at the repo root:
#   PYPI_API_TOKEN=pypi-...
#   TESTPYPI_API_TOKEN=pypi-...

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

TARGET="${1:-test}"

case "$TARGET" in
    test)
        if [ -z "${TESTPYPI_API_TOKEN:-}" ]; then
            echo "ERROR: TESTPYPI_API_TOKEN is empty in .env" >&2
            exit 1
        fi
        REPO_FLAG="--repository testpypi"
        TOKEN="$TESTPYPI_API_TOKEN"
        INDEX_NOTE="https://test.pypi.org/project/genesis-mesh/"
        ;;
    prod)
        if [ -z "${PYPI_API_TOKEN:-}" ]; then
            echo "ERROR: PYPI_API_TOKEN is empty in .env" >&2
            exit 1
        fi
        REPO_FLAG=""
        TOKEN="$PYPI_API_TOKEN"
        INDEX_NOTE="https://pypi.org/project/genesis-mesh/"
        ;;
    *)
        echo "Usage: $0 [test|prod]" >&2
        exit 1
        ;;
esac

cd "$REPO_ROOT"

echo "==> Cleaning previous build artifacts"
rm -rf dist/ build/ genesis_mesh.egg-info/

echo "==> Building wheel + sdist"
python -m build

echo "==> Verifying package metadata"
python -m twine check dist/*

echo "==> Uploading to $TARGET"
TWINE_USERNAME=__token__ \
TWINE_PASSWORD="$TOKEN" \
    python -m twine upload $REPO_FLAG dist/*

echo ""
echo "==> Done. Project page: $INDEX_NOTE"
