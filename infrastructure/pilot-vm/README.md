# Pilot-profile test VM

A single-VM deployment of the pilot deployment profile
(`docs/operations/pilot-deployment-profile.md`) for testing a release before
a pilot: PostgreSQL 17, two Network Authority instances in HA mode built from
the released PyPI package (or a release-candidate wheel), and Caddy with an
automatic TLS certificate.

## Prepare (on the operator's machine)

Generate the sovereign's keys and signed genesis on the operator's machine.
The root and operator private keys never go to the VM; it receives the signed
genesis, the NA seed (as a platform secret store would provide it) and the
operators' public keys. Write `.env` next to `docker-compose.yml`:

```bash
GENESIS_MESH_VERSION=0.63.1            # PyPI release to install
SITE_ADDRESS=na.example.org            # DNS name for the TLS certificate
NA_KEY_ID=pilot-na
NA_PRIVATE_KEY_SEED=<base64 seed>
POSTGRES_PASSWORD=<random>
OPERATOR_PUBLIC_KEYS_JSON='{"alice":"<base64>","ci":"<base64>"}'
OPERATOR_KEY_TIERS_JSON='{"alice":"privileged","ci":"standard"}'
NA_RATE_LIMIT_ADMIN_PER_MINUTE=600     # size to the pilot's controllers
```

To test a release candidate instead of a published release, put its wheel in
`dist/` and set `IMAGE_TAG` (for example `0.64.0-rc1`).

## Run (on the VM)

```bash
docker compose build na-a      # one build; na-b reuses the image
docker compose up -d
curl https://$SITE_ADDRESS/readyz
```

## Drills

- **Backup and restore:** `./restore-drill.sh` dumps the live database,
  restores it into a new database and runs `na verify-db` on both.
- **Load and failover:** `GM_URL=https://$SITE_ADDRESS GM_KEYS_FILE=keys.json
  node load-drill.mjs 120` runs governed actions on one resource chain; kill an
  instance meanwhile (`docker compose kill na-a`, later `docker compose start
  na-a`). It checks that every acknowledged record is in the chain exactly
  once, gap-free, and that the store verifies offline. On a network that
  re-signs TLS, set `NODE_EXTRA_CA_CERTS` to the proxy's CA.
- **Upgrade:** change `GENESIS_MESH_VERSION` (or the wheel), back up, then
  `docker compose build na-a && docker compose up -d`; roll back by restoring
  the backup (`docs/operations/upgrade.md`).
