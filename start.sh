#!/bin/bash
set -euo pipefail

ROLE=${SERVICE_ROLE:-na}

if [ "$ROLE" = "na" ]; then
    echo "Starting Network Authority..."

    GENESIS_FILE=${GENESIS_FILE:-genesis.signed.json}
    NA_PRIVATE_KEY_FILE=${NA_PRIVATE_KEY_FILE:-keys/na.key}
    DB_PATH=${DB_PATH:-genesis_mesh_na.db}
    PORT=${PORT:-8443}

    if [ ! -f "$GENESIS_FILE" ] || [ ! -f "$NA_PRIVATE_KEY_FILE" ]; then
        echo "ERROR: genesis block or NA key not mounted. Refusing to start." >&2
        exit 1
    fi

    export GENESIS_FILE
    export NA_PRIVATE_KEY_FILE
    export DB_PATH

    exec gunicorn \
        --bind "0.0.0.0:${PORT}" \
        --workers "${WEB_CONCURRENCY:-4}" \
        --worker-class sync \
        --timeout 30 \
        --max-requests 1000 \
        --limit-request-line 4096 \
        --access-logfile - \
        --error-logfile - \
        "genesis_mesh.na_service.wsgi:app"
fi

if [ "$ROLE" = "node" ]; then
    echo "Starting Mesh Node..."

    if [ "$#" -gt 0 ]; then
        exec python -m genesis_mesh.node "$@"
    fi

    GENESIS_FILE=${GENESIS_FILE:-}
    BOOTSTRAP=${BOOTSTRAP_URL:-http://localhost:8443}
    NODE_ROLE=${NODE_ROLE:-anchor}
    INVITE_TOKEN=${INVITE_TOKEN:-}

    if [ -z "$GENESIS_FILE" ] || [ ! -f "$GENESIS_FILE" ]; then
        echo "ERROR: genesis block not mounted. Refusing to start node." >&2
        exit 1
    fi

    if [ -z "$INVITE_TOKEN" ]; then
        echo "ERROR: INVITE_TOKEN is required for node enrollment. Refusing to start node." >&2
        exit 1
    fi

    cmd=(
        python -m genesis_mesh.node
        --genesis "$GENESIS_FILE"
        --bootstrap "$BOOTSTRAP"
        --role "$NODE_ROLE"
        --invite-token "$INVITE_TOKEN"
        --listen-host "${LISTEN_HOST:-0.0.0.0}"
        --listen-port "${LISTEN_PORT:-0}"
    )

    if [ -n "${NODE_KEY_FILE:-}" ]; then
        cmd+=(--node-key "$NODE_KEY_FILE")
    fi

    if [ "${PERSISTENT:-true}" = "true" ]; then
        cmd+=(--persistent)
    fi

    echo "Executing mesh node startup"
    exec "${cmd[@]}"
fi

echo "ERROR: unknown SERVICE_ROLE '$ROLE'. Expected 'na' or 'node'." >&2
exit 1
