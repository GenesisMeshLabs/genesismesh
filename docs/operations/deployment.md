# Deployment

Genesis Mesh supports local development startup and container-oriented Network
Authority startup.

```{mermaid}
flowchart TB
    subgraph host["Container Host"]
        secrets["Mounted secrets"]
        data["Durable DB volume"]
        container["Genesis Mesh container"]
    end

    ingress["Ingress on 8443"]
    gunicorn["Gunicorn"]
    flask["Network Authority app"]
    sqlite["SQLite DB"]

    secrets -->|GENESIS_FILE and NA_PRIVATE_KEY_FILE| container
    data -->|DB_PATH| sqlite
    ingress --> gunicorn
    gunicorn --> flask
    flask --> sqlite
    container --> gunicorn
```

## Local Development

Use the high-level CLI while developing or running smoke tests:

```bash
genesis-mesh init
genesis-mesh na start
genesis-mesh dev up
```

`genesis-mesh na start` uses the Flask local server and reads
`genesis-mesh.toml`. Production/container startup uses Gunicorn through
`start.sh`.

## Container Startup

The container entry point is `start.sh`. In Network Authority mode it runs
Gunicorn and requires mounted genesis and NA key files.

```bash
docker run --rm \
  -e SERVICE_ROLE=na \
  -e GENESIS_FILE=/run/secrets/genesis.signed.json \
  -e NA_PRIVATE_KEY_FILE=/run/secrets/na.key \
  -e OPERATOR_PUBLIC_KEYS_JSON='{"operator-local":"<base64-public-key>"}' \
  -e DB_PATH=/data/genesis_mesh_na.db \
  -p 8443:8443 \
  genesis-mesh:local
```

## Production Readiness Checks

Before production use, verify:

- the container starts as a non-root user
- required secret files are mounted
- startup fails when required secret files are missing
- `/healthz` and `/readyz` work behind the selected ingress
- SQLite data is persisted on durable storage
- backups are tested
- operator public keys are reviewed and rotated through policy
- logs do not expose private key material

## Container Smoke Checks

Build the image before release:

```bash
docker build -t genesis-mesh:local .
```

The container must fail closed when required Network Authority secrets are not
mounted:

```bash
docker run --rm genesis-mesh:local
```

Expected result: non-zero exit and a message containing `Refusing to start`.
With secrets mounted, the same image should serve `/healthz` and `/readyz`
through Gunicorn on port `8443`.

```bash
docker run --rm \
  -e SERVICE_ROLE=na \
  -e GENESIS_FILE=/run/secrets/genesis.signed.json \
  -e NA_PRIVATE_KEY_FILE=/run/secrets/na.key \
  -e DB_PATH=/data/genesis_mesh_na.db \
  -p 8443:8443 \
  genesis-mesh:local
```

Do not run two Network Authority processes against the same SQLite database
file. Genesis Mesh treats SQLite as a single-writer deployment store.

## Azure Helpers

Azure Container Apps helper scripts live under `infrastructure/azure/`. They are
deployment helpers, not a substitute for production secret mounting and policy
review.
