# Backup and Restore

The Network Authority stores invite tokens, issued certificates, nonces, CRLs,
policies, and audit events in SQLite. Treat that database as production state.

## What to Back Up

Back up the SQLite file configured by `DB_PATH`. For local CLI deployments this
is usually `.genesis-mesh/na.db`; for containers it should be a mounted durable
volume such as `/data/genesis_mesh_na.db`.

Also keep offline backups of:

- the signed genesis block
- the Network Authority private key, in a secret manager or offline key backup
- operator public key configuration
- deployment configuration that sets `DB_PATH`, `GENESIS_FILE`, and
  `NA_PRIVATE_KEY_FILE`

## Online Backup

Use the managed backup command:

```bash
genesis-mesh managed backup \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /backups/genesis-mesh-na-YYYYMMDDHHMMSS.db
```

The command uses SQLite's online backup API, so it can copy a consistent
snapshot while the service is running.

The same API is available from a maintenance shell:

```python
from genesis_mesh.na_service.db import NADatabase

db = NADatabase("/data/genesis_mesh_na.db")
db.backup("/backups/genesis_mesh_na-YYYYMMDD.db")
```

## Restore

1. Stop the Network Authority process.
2. Restore the backup database to the configured `DB_PATH`:

   ```bash
   genesis-mesh managed restore \
     --db-path /var/lib/genesis-mesh/na.db \
     --backup /backups/genesis-mesh-na-YYYYMMDDHHMMSS.db \
     --pre-restore-backup /backups/na-before-restore.db \
     --yes
   ```

3. Start the Network Authority.
4. Check readiness:

   ```bash
   curl http://localhost:8443/readyz
   ```

5. Confirm persisted state:

   ```bash
   curl http://localhost:8443/nodes
   curl http://localhost:8443/crl
   curl http://localhost:8443/policy
   ```

6. Confirm Connectome state when the sovereign uses cross-sovereign trust:

   ```bash
   curl http://localhost:8443/connectome.json
   ```

## Restore Drill Checklist

- [ ] Create a backup from a non-production NA database.
- [ ] Mutate non-production state after the backup.
- [ ] Stop the test NA process.
- [ ] Restore the backup with `genesis-mesh managed restore --yes`.
- [ ] Start the test NA process.
- [ ] Confirm `/healthz` returns `{"status":"ok"}`.
- [ ] Confirm `/readyz` returns `{"status":"ready"}`.
- [ ] Confirm `/connectome.json` matches the expected restored trust state.
- [ ] Export audit events after the drill and store the drill result.

## Operational Notes

- Do not run two Network Authority processes against the same SQLite file. This
  deployment shape is unsupported; use one writer per database file.
- Test restore regularly, not only backup creation.
- Keep backups encrypted and access controlled. The database contains node
  public keys, certificate state, audit events, and nonce history.
- A restored database should use the same signed genesis block and NA private
  key that signed the existing certificates and CRLs.
