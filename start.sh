#!/bin/bash
set -euo pipefail

ROLE=${SERVICE_ROLE:-na}

# Files created in /data are group-writable: the directory is setgid group 0,
# so a platform that runs the image under another user ID in group 0 can take
# over a volume this one wrote (v1.1). Secrets are still created 0600 below.
umask 0002

# A private directory for secrets handed over in the environment: on /dev/shm
# (memory only, recreated on every start) when it is available, never in the
# container's writable layer if it can be avoided. Unpredictable name, mode
# 0700; files are created 0600 via umask, never world-readable, not even briefly.
SECRETS_DIR=""
secrets_dir() {
    if [ -z "$SECRETS_DIR" ]; then
        if [ -d /dev/shm ] && [ -w /dev/shm ]; then
            SECRETS_DIR="$(mktemp -d -p /dev/shm gm-secrets.XXXXXXXX)"
        else
            SECRETS_DIR="$(mktemp -d)"
        fi
    fi
}

if [ "$ROLE" = "na" ]; then
    echo "Starting Network Authority..."

    GENESIS_FILE=${GENESIS_FILE:-genesis.signed.json}
    NA_PRIVATE_KEY_FILE=${NA_PRIVATE_KEY_FILE:-keys/na.key}
    DB_PATH=${DB_PATH:-genesis_mesh_na.db}
    PORT=${PORT:-8443}

    if [ ! -f "$GENESIS_FILE" ] && [ -n "${GENESIS_JSON:-}" ]; then
        secrets_dir
        GENESIS_FILE="$SECRETS_DIR/genesis.signed.json"
        (umask 077; printf '%s' "$GENESIS_JSON" > "$GENESIS_FILE")
    fi

    if [ ! -f "$NA_PRIVATE_KEY_FILE" ] && [ -n "${NA_PRIVATE_KEY:-}" ]; then
        secrets_dir
        NA_PRIVATE_KEY_FILE="$SECRETS_DIR/na.key"
        (umask 077; printf '%s' "$NA_PRIVATE_KEY" > "$NA_PRIVATE_KEY_FILE")
    fi

    # v0.60: with NA_KEY_PROVIDER=env or azure-keyvault the key is never a
    # file; the NA itself refuses to start if the provider cannot load it.
    NA_KEY_PROVIDER=${NA_KEY_PROVIDER:-file}

    # v1.1: a seed given as an environment value is moved to a secret file
    # (NA_PRIVATE_KEY_SEED_FILE), so the server and its workers do not carry it
    # in their environment. Prefer mounting the file in the first place: the
    # container configuration still shows an environment value.
    SEED_VAR=${NA_KEY_SEED_ENV:-NA_PRIVATE_KEY_SEED}
    if ! [[ "$SEED_VAR" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        echo "ERROR: NA_KEY_SEED_ENV must name an environment variable. Refusing to start." >&2
        exit 1
    fi
    SEED_FILE_VAR="${SEED_VAR}_FILE"
    if [ "$NA_KEY_PROVIDER" = "env" ] && [ -n "${!SEED_VAR:-}" ] && [ -z "${!SEED_FILE_VAR:-}" ]; then
        secrets_dir
        (umask 077; printf '%s' "${!SEED_VAR}" > "$SECRETS_DIR/na.seed")
        export "$SEED_FILE_VAR=$SECRETS_DIR/na.seed"
        unset "$SEED_VAR"
    fi
    unset GENESIS_JSON NA_PRIVATE_KEY

    if [ ! -f "$GENESIS_FILE" ] || { [ "$NA_KEY_PROVIDER" = "file" ] && [ ! -f "$NA_PRIVATE_KEY_FILE" ]; }; then
        echo "ERROR: genesis block or NA key not mounted. Refusing to start." >&2
        exit 1
    fi

    # SQLite needs to write the database and its journal next to it. A volume
    # left by another user (for example an image that ran as a different uid)
    # or a read-only mount would otherwise fail on the first write.
    case "${DATABASE_URL:-}" in
        "") CHECK_DB="$DB_PATH" ;;
        sqlite:*) CHECK_DB="${DATABASE_URL#sqlite://}" ;;
        *) CHECK_DB="" ;;  # PostgreSQL: the server owns its storage
    esac
    case "$CHECK_DB" in //*) CHECK_DB="${CHECK_DB#/}" ;; esac  # sqlite:////abs/path
    case "$CHECK_DB" in
        ""|":memory:"|"/:memory:") ;;
        *)
            DB_DIR="$(dirname "$CHECK_DB")"
            if [ ! -d "$DB_DIR" ]; then
                echo "ERROR: database directory $DB_DIR does not exist. Mount a data volume there or set DB_PATH. Refusing to start." >&2
                exit 1
            fi
            if [ ! -w "$DB_DIR" ] || { [ -e "$CHECK_DB" ] && [ ! -w "$CHECK_DB" ]; }; then
                echo "ERROR: database $CHECK_DB is not writable by uid $(id -u). Give the data volume to this user (for example chown -R $(id -u):0 and chmod -R g+rwX on the volume). Refusing to start." >&2
                exit 1
            fi
            # SQLite creates its files 0644 whatever the umask, and gives its
            # -wal and -shm files the database's mode: create the database here,
            # group-writable, so another user ID in group 0 can take it over.
            [ -e "$CHECK_DB" ] || : > "$CHECK_DB"
            ;;
    esac

    export GENESIS_FILE
    export NA_PRIVATE_KEY_FILE
    export NA_KEY_PROVIDER
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

    # As for the NA: platforms without file mounts pass the genesis block itself.
    if { [ -z "$GENESIS_FILE" ] || [ ! -f "$GENESIS_FILE" ]; } && [ -n "${GENESIS_JSON:-}" ]; then
        secrets_dir
        GENESIS_FILE="$SECRETS_DIR/genesis.signed.json"
        (umask 077; printf '%s' "$GENESIS_JSON" > "$GENESIS_FILE")
    fi
    unset GENESIS_JSON

    if [ -z "$GENESIS_FILE" ] || [ ! -f "$GENESIS_FILE" ]; then
        echo "ERROR: genesis block not mounted. Refusing to start node." >&2
        exit 1
    fi

    if [ -z "$INVITE_TOKEN" ]; then
        echo "ERROR: INVITE_TOKEN is required for node enrollment. Refusing to start node." >&2
        exit 1
    fi

    # The token goes to the node in a private file, not on its command line,
    # where any user on the host could read it with ps (v1.1).
    secrets_dir
    (umask 077; printf '%s' "$INVITE_TOKEN" > "$SECRETS_DIR/invite.token")
    unset INVITE_TOKEN

    cmd=(
        python -m genesis_mesh.node
        --genesis "$GENESIS_FILE"
        --bootstrap "$BOOTSTRAP"
        --role "$NODE_ROLE"
        --invite-token-file "$SECRETS_DIR/invite.token"
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
