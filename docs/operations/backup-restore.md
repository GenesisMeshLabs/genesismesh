# Backup and Restore

The Network Authority stores invite tokens, issued certificates, nonces, CRLs,
policies, treaties, attestations, revocations, decisions, evidence and audit
events in SQLite or PostgreSQL. Treat that database as production state.

## What to Back Up

Back up the SQLite file configured by `DB_PATH`. For local CLI deployments this
is usually `.genesis-mesh/na.db`; in the container image it is
`/data/genesis_mesh_na.db` on the volume mounted at `/data`. With PostgreSQL,
see [PostgreSQL](#postgresql) below.

Also keep offline backups of:

- the signed genesis block
- every NA private key the key history names (the genesis key and each key a
  succession named), in a secret manager or offline key backup. The root
  private key is kept offline on its own ({doc}`key-succession`), never in
  the NA's backups
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

### In a container

The image includes the CLI. Back up inside the running container, then copy
the file out:

```bash
docker exec na genesis-mesh managed backup \
  --db-path /data/genesis_mesh_na.db --output /data/backup-YYYYMMDDHHMMSS.db
mkdir -p backups
docker cp na:/data/backup-YYYYMMDDHHMMSS.db ./backups/
docker exec na rm /data/backup-YYYYMMDDHHMMSS.db
```

To restore, stop the container and run the restore from a one-off container
on the same volume, from the image digest the NA runs (`$DIGEST`; the
backup directory must be readable by user 10001):

```bash
docker stop na
docker run --rm -v na-data:/data -v "$PWD/backups:/backups:ro" \
  --entrypoint genesis-mesh "ghcr.io/genesismeshlabs/genesis-mesh@$DIGEST" \
  managed restore --db-path /data/genesis_mesh_na.db \
  --backup /backups/backup-YYYYMMDDHHMMSS.db \
  --pre-restore-backup /data/before-restore.db --yes
docker start na
```

The restore replaces the database's contents and keeps its mode and owner,
whatever the backup file's mode is, so the volume stays as the image laid it
out: group-writable, for platforms that run the image under another user ID
in group 0.

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

   The restore copies the backup's contents into the database file, which
   keeps its own mode and owner whatever the backup file's mode is. It
   removes the replaced database's `-wal` and `-shm` files first, so SQLite
   cannot replay them onto the restored data. The pre-restore backup is
   taken with the SQLite backup API, so it includes writes still in the WAL.
   The backup is opened read-only and may sit on read-only media.

3. Verify the restored database before serving it:

   ```bash
   genesis-mesh na verify-db --db-path /var/lib/genesis-mesh/na.db \
     --genesis /config/genesis.signed.json
   ```

4. Check what the backup does not hold. Everything recorded after the
   backup is gone:
   - **Revocations.** Certificate, attestation and grant revocations made
     after the backup are gone, so that trust material is usable again.
     Re-issue each one.
   - **Revocation feed sequence.** The feed's sequence goes back with the
     restore. Partners that imported a later feed refuse the next one
     (`409 stale_sequence`) until the sequence passes theirs. Tell them.
   - **Key succession.** If a key succession was recorded after the backup,
     the restored key history does not hold it. An NA started with the new
     key refuses to start, and the old succession record cannot be submitted
     again, because its `effective_at` is in the past
     (`succession_times_invalid`). Do not restore a backup older than the
     latest succession without planning this ({doc}`key-succession`).
   - **Anchors.** If evidence store anchors were copied out of this NA
     (v1.2.0), restoring a backup older than the newest copy is an
     evidence-loss event for their holders: follow *After a restore* in
     {doc}`evidence-anchors`.
5. Start the Network Authority.
6. Check readiness:

   ```bash
   curl http://localhost:8443/readyz
   ```

7. Confirm persisted state:

   ```bash
   curl http://localhost:8443/nodes
   curl http://localhost:8443/crl
   curl http://localhost:8443/policy
   ```

8. Confirm Connectome state when the sovereign uses cross-sovereign trust:

   ```bash
   curl http://localhost:8443/connectome.json
   ```

## PostgreSQL

Back up with `pg_dump` in custom format and restore into a **new** database
(created with C collation, as the NA requires), then point a new instance at
it and verify:

```bash
pg_dump -Fc --no-owner --dbname "$DATABASE_URL" > na-YYYYMMDD.dump

createdb --template=template0 --encoding=UTF8 --lc-collate=C --lc-ctype=C na_restored
pg_restore --no-owner --exit-on-error --dbname postgresql://.../na_restored na-YYYYMMDD.dump

DATABASE_URL=postgresql://.../na_restored genesis-mesh na verify-db \
  --genesis /config/genesis.signed.json
```

Restore into a new database rather than over the old one, so the original is
still there if the restore turns out to be incomplete. `scripts/recovery_drill.py`
rehearses exactly this in CI: it dumps a populated database, drops the
original, restores into a new database and has a new instance verify every
treaty, revocation, policy, decision and evidence record.

## Restore Drill Checklist

![Restore drill: a backup, a revocation after it, restore and verify-db, the revocation gone, and revoked again](../examples/assets/images/genesis-mesh-restore-drill.gif)

The GIF is a real run of `docs/examples/assets/scripts/restore-drill-demo.py`
against a throwaway SQLite NA. The certificate revoked after the backup is
valid again after the restore: the CRL is back at sequence 0. Revoking it
again issues a CRL with sequence 1 once more, the same number as the CRL that
was lost. Nodes announce and compare CRLs by sequence, so a node that already
holds the lost CRL may not take a new one with the same number. Re-issue the
lost revocations, and check the CRL sequence your nodes report. The
transcript is
`docs/examples/assets/images/genesis-mesh-restore-drill.txt`.

- [ ] Create a backup from a non-production NA database.
- [ ] Mutate non-production state after the backup.
- [ ] Stop the test NA process.
- [ ] Restore the backup with `genesis-mesh managed restore --yes`.
- [ ] Run `genesis-mesh na verify-db --db-path <db> --genesis <genesis>`.
- [ ] Confirm the change made after the backup is gone (for example a
      revocation), and re-apply it.
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
- Start the restored database with the same signed genesis block and the NA
  key that was in effect at the backup's time. If a succession was recorded
  after the backup, see step 4 of [Restore](#restore).
