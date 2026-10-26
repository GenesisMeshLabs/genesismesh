#!/usr/bin/env bash
# Upgrade the mesh.genesismesh.org stack to a released Genesis Mesh version.
#
#   /opt/genesis-mesh-mesh/upgrade.sh X.Y.Z
#
# Run on the droplet, in /opt/genesis-mesh-mesh, after the release is published
# (PyPI and the gateway image). It verifies the gateway image's signature
# (cosign 3), backs up the configuration and the volumes, sets the versions in
# .env, builds the NA from PyPI, restarts and checks the database and readiness.
# Read the release's upgrade notes first (docs/operations/upgrade.md): a release
# that needs an operator step is not upgraded by this script alone.
#
# Rollback: restore backups/env-before-X.Y.Z to .env, then `docker compose up -d`
# (the previous images stay on the host); restore the volume tarballs only when
# the release migrated the database.
set -euo pipefail

VERSION=${1:?usage: upgrade.sh X.Y.Z}
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a release version: $VERSION" >&2; exit 2; }
cd /opt/genesis-mesh-mesh
STAMP="before-$VERSION"
OUT="/root/upgrade-$VERSION"
IMAGE=ghcr.io/genesismeshlabs/genesis-mesh-gateway
mkdir -p "$OUT" backups
exec > >(tee -a "$OUT/upgrade.log") 2>&1

current=$(grep -E '^GENESIS_MESH_VERSION=' .env | cut -d= -f2)
echo "== upgrade $current -> $VERSION"
# FORCE=1 re-runs an upgrade that stopped half way (.env may already name the version).
if [ "${FORCE:-}" != 1 ] && { [ "$current" = "$VERSION" ] || [ "$(printf '%s\n%s\n' "$current" "$VERSION" | sort -V | tail -n 1)" != "$VERSION" ]; }; then
  echo "refusing: $VERSION is not newer than $current (FORCE=1 to re-run)" >&2; exit 2
fi

echo "== gateway image, by digest, signature verified"
DIGEST=$(docker buildx imagetools inspect "$IMAGE:$VERSION" --format '{{json .Manifest.Digest}}' | tr -d '"')
cosign verify "$IMAGE@$DIGEST" \
  --certificate-identity "https://github.com/GenesisMeshLabs/gateway/.github/workflows/distribution.yml@refs/tags/v$VERSION" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com > "$OUT/cosign-gateway.json"
docker pull "$IMAGE@$DIGEST"
docker tag "$IMAGE@$DIGEST" "genesis-mesh-gateway:$VERSION"

echo "== config backups"
install -m 600 .env "backups/env-$STAMP"
for f in policy.json docker-compose.yml Caddyfile; do install -m 600 "$f" "backups/$f-$STAMP"; done

echo "== versions"
sed -i -e "s/^GENESIS_MESH_VERSION=.*/GENESIS_MESH_VERSION=$VERSION/" -e "s/^GATEWAY_VERSION=.*/GATEWAY_VERSION=$VERSION/" .env
grep -E '^(GENESIS_MESH_VERSION|GATEWAY_VERSION)=' .env

echo "== build the NA from PyPI $VERSION"
docker compose build na
docker compose run --rm --no-deps --entrypoint genesis-mesh na --version

echo "== stop and back up the volumes"
docker compose stop
for v in na-data demo-state gateway-state; do
  docker run --rm -v "genesis-mesh-mesh_${v}:/v:ro" -v /opt/genesis-mesh-mesh/backups:/b alpine \
    tar czf "/b/${v}-${STAMP}.tgz" -C /v .
  chmod 600 "backups/${v}-${STAMP}.tgz"
done

echo "== start $VERSION"
docker compose up -d
for _ in $(seq 1 60); do
  [ "$(docker compose ps --format '{{.Service}} {{.Status}}' | grep -E '^(na|gateway) ' | grep -c healthy)" = 2 ] && break
  sleep 5
done
docker compose ps --format '{{.Service}} {{.Status}} {{.Image}}'
docker compose logs --since 5m na | grep -iE "migrat|error|warning|re-issu" | tail -10 || true

echo "== verify-db"
docker compose exec -T na genesis-mesh na verify-db --db-path /data/na.db --genesis /config/genesis.signed.json \
  > "$OUT/verify-db.json" || true
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); c=r["checks"]; print("ok", r["ok"], "schema", c.get("schema_version"), "entries", c.get("evidence", {}).get("entries"))' "$OUT/verify-db.json"

echo "== readiness"
docker compose exec -T na python -c 'import json,urllib.request; r=json.load(urllib.request.urlopen("http://127.0.0.1:8000/readyz")); print("ready", r.get("status"), "schema", r.get("database",{}).get("schema_version"), "reissue", json.dumps(r.get("reissue")))'
curl -fsS https://mesh.genesismesh.org/ready > /dev/null && echo "public mesh ready"
echo "UPGRADE DONE: $VERSION (log $OUT/upgrade.log)"
