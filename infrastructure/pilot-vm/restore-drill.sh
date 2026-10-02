#!/usr/bin/env bash
# Backup and restore drill on the pilot VM: dump the live database, restore it
# into a new database, verify the restored copy and the live one.
set -euo pipefail
cd "${PILOT_DIR:-/opt/genesis-mesh-pilot}"
PW=$(sed -n "s/^POSTGRES_PASSWORD='\(.*\)'$/\1/p" .env)
docker compose exec -T postgres pg_dump -U genesis -Fc genesis_mesh > /root/na-backup.dump
echo "dump bytes: $(stat -c %s /root/na-backup.dump)"
docker compose exec -T postgres psql -U genesis -d postgres -q -c "DROP DATABASE IF EXISTS restored WITH (FORCE)"
docker compose exec -T postgres psql -U genesis -d postgres -q -c "CREATE DATABASE restored TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
docker compose exec -T postgres pg_restore -U genesis --no-owner --exit-on-error -d restored < /root/na-backup.dump
echo "restored into a new database"
for db in restored genesis_mesh; do
  echo "== na verify-db on ${db}"
  docker compose run --rm -T --no-deps -e "DATABASE_URL=postgresql://genesis:${PW}@postgres:5432/${db}" \
    na-a genesis-mesh na verify-db --genesis /config/genesis.signed.json 2>&1 | tail -6
done
docker compose exec -T postgres psql -U genesis -d postgres -q -c "DROP DATABASE restored WITH (FORCE)"
