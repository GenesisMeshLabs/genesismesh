# Incident Response Runbooks

These runbooks are for managed sovereign operation. They are intentionally
plain: stop the bad trust path, preserve evidence, restore service, and document
what changed.

The `genesis-mesh managed` helpers used below (`audit-export`, `backup`,
`restore`) read a SQLite database file (`--db-path`). With PostgreSQL
(`DATABASE_URL`, for example in HA mode) they do not apply: query the audit
table with your database tools, and back up and restore with `pg_dump` and
`pg_restore` as in {doc}`backup-restore`.

## Operator Key Compromise

Use this when an operator signing key may have been exposed.

1. **Revoke the key on the running service — no restart required:**

   ```bash
   genesis-mesh admin revoke-operator-key <compromised-key-id> \
     --na https://na.example.org \
     --operator-key keys/other-operator.key \
     --operator-key-id <another-privileged-key-id> \
     --reason key_compromise
   ```

   The key stops authenticating on the very next request. Rejection happens
   before its signature is checked and before its nonce is consumed, so it
   cannot act at all — including revoking other operators.

   This requires a **privileged**-tier key, and the service refuses to revoke
   the last usable operator key (`409 last_active_operator_key`). Configure a
   second operator key *before* an incident so this path is available.

2. Confirm old-key admin requests now fail with `401 Unknown admin key`. The
   audit log records the true reason (`admin_auth_failed` with
   `reason: revoked_key`) plus an `operator_key_revoked` event naming who
   performed the revocation.
3. Rotate to a new operator key and record the new key ID. Adding a key still
   requires updating `OPERATOR_PUBLIC_KEYS_JSON` (and `OPERATOR_KEY_TIERS_JSON`)
   and restarting — only *removal* is live.
4. Revocation is **terminal**: a revoked key ID cannot be restored on the
   running service. Bringing it back means editing configuration and
   restarting, deliberately.
5. Export audit events around the compromise window:

   ```bash
   genesis-mesh managed audit-export \
     --db-path /var/lib/genesis-mesh/na.db \
     --output ./incident-audit.jsonl
   ```

6. Review admin actions signed by the compromised key.
7. Revoke or supersede any trust material created by the compromised key:
   certificates, attestations and treaties.
8. Check what the key did in the governed-changes path. These features are
   off by default; check the ones your NA has turned on:
   - grants it issued (`GET /admin/grants`, field `issued_by_operator`;
     with `EVIDENCE_GRANTS=on`). Revoke them with
     `POST /admin/grants/<grant_id>/revoke`;
   - executor and observer keys it registered. Retire them with
     `POST /admin/evidence/executor-keys/<key_id>/retire`;
   - reviews it decided and holder changes it approved (with
     `EVIDENCE_REMEDIATION=on`). Have another holder review them again;
   - archives it recorded and retention it applied. Compare them with your
     archive storage ({doc}`audit-and-retention`);
   - policies it activated;
   - key successions it submitted. Check that `GET /na/key-history` holds no
     succession you did not plan.

   A compromised read-tier key can read, force anchors and build audit
   packs; it can change nothing else.

## Network Authority Key Compromise

Use this when the NA signing key may have been exposed.

**Planned rotation and compromise are different cases.** A planned rotation
uses key succession ({doc}`key-succession`): the offline root key names the
next NA key and the sovereign keeps its identity. A compromised NA key still
means a new sovereign identity. A succession does not make the old key
harmless:

- Verifiers that follow the key history still accept the old key's signature
  on any record dated before the hand-over (`effective_at` plus 300 seconds).
  Whoever holds a copy of the key can sign new records and date them inside
  that window.
- Recognition treaties at other sovereigns name your NA public key
  (`subject_public_keys`). They keep accepting attestations signed by the old
  key until each counterpart revokes or replaces its treaty.

So:

1. Stop the Network Authority.
2. Preserve the current DB and key material for incident analysis.
3. Create a new sovereign identity: new root and NA keys and a new signed
   genesis. Counterparts must recognize the new identity explicitly, with new
   treaties.
4. Publish the replacement public trust material.
5. Re-issue affected certificates, attestations, treaties, and feeds as needed.
6. Notify recognizing sovereigns that old trust material must be rejected, and
   ask them to revoke every treaty that names the old key.
7. Record the migration in the incident log and release notes if public trust is
   affected.

If you still hold the exposed key and the root key is safe, you may instead
of step 1 succeed the key at once, with `effective_at` as early as the NA
allows (60 seconds), and keep the NA running on the new key while you build
the new identity. That stops your own NA from signing with the exposed key.
It does not replace steps 3 to 7.

A lost NA key, or a key past its `new_valid_to`, cannot sign its own
succession. A
compromised root key can sign successions to any key. Both also mean a new
identity.

An NA key compromise is a sovereign-level incident. Do not treat it as a normal
operator-key rotation.

## Governed-change incidents

These features are off by default. Each line applies only when the NA runs
with the setting named on the linked page.

- **Edge device compromised.** Revoke any certificate it holds:
  `genesis-mesh admin revoke <cert-id> --reason key_compromise`. The NA revokes
  every certificate of the device in one CRL, retires its executor key and
  revokes the grants that key bears ({doc}`edge-agent`, *Revoking a device*).
- **Grant bearer compromised.** Retire its executor key. That ends every grant
  it bears ({doc}`grants`, *Revocation*).
- **Executor or observer key compromised.** Retire it with
  `POST /admin/evidence/executor-keys/<key_id>/retire`. Records it signs
  afterwards are refused (`*_key_retired`) ({doc}`out-of-band-changes`).
- **Root key compromised.** No succession can be trusted from now on. Create a
  new identity, as above ({doc}`key-succession`).
- **The store no longer matches its anchors** (`409 evidence_anchor_refused`,
  or a failure of `GET /admin/evidence/verify` or `genesis-mesh na verify-db`).
  Stop writes if you can, preserve the database, keep every anchor that was
  copied out, and follow *After a restore* in {doc}`evidence-anchors`.
- **Anchoring blocked** (`GET /admin/evidence/status` reports
  `anchoring_blocked`). An instance's clock ran ahead. Fix the time source
  (NTP) of every instance ({doc}`evidence-anchors`).

## Bad Treaty Issued

Use this when a recognition treaty was issued with the wrong subject sovereign,
public key, role, validity window, or metadata.

1. Revoke the treaty. The request must be signed by a privileged operator key,
   as every `/admin` request is:

   ```bash
   genesis-mesh treaty revoke <treaty-id> \
     --na https://na.example.org \
     --reason <reason> \
     --operator-key keys/ops.key \
     --operator-key-id <privileged-key-id> \
     --yes
   ```

2. Confirm `/connectome.json` shows the revoked edge.
3. Export audit events for the treaty:

   ```bash
   genesis-mesh managed audit-export \
     --db-path /var/lib/genesis-mesh/na.db \
     --output ./bad-treaty-audit.jsonl \
     --event-type recognition_treaty_issued
   ```

4. Issue a corrected treaty only after the subject public keys and scope are
   checked against a source other than the subject's own endpoint.
5. Notify affected operators if any attestation was accepted under the bad
   treaty.

## Bad Revocation Feed Imported

Use this when a signed feed was imported from the wrong issuer, stale sequence,
wrong public key, or wrong incident scope.

1. Stop importing new feeds from the affected issuer until the source is
   understood.
2. Export `sovereign_revocation_feed_imported` and
   `sovereign_revocation_feed_rejected` audit events.
3. Review `/connectome.json` revocation blast radius.
4. Restore from the most recent known-good DB backup if the imported feed must
   be removed from state. A restore has side effects: read the checks in
   *Database Restore* below first.
5. Re-import the corrected feed.
6. Confirm the expected attestations are accepted or rejected after import.

## Database Restore

Use this when DB state is corrupt, accidental trust data was deleted, or a bad
import must be rolled back.

1. Stop the Network Authority.
2. Create a pre-restore copy of the current DB.
3. Restore the selected backup:

   ```bash
   genesis-mesh managed restore \
     --db-path /var/lib/genesis-mesh/na.db \
     --backup /backups/genesis-mesh-na-known-good.db \
     --pre-restore-backup /backups/na-before-restore.db \
     --yes
   ```

4. Verify the restored database before you start the NA:

   ```bash
   genesis-mesh na verify-db \
     --db-path /var/lib/genesis-mesh/na.db \
     --genesis /etc/genesis-mesh/genesis.signed.json
   ```

5. Check what the backup does not hold:
   - **Key succession.** Do not restore a backup older than the latest key
     succession. The NA refuses to start with the new key, and the succession
     cannot be submitted again: its `effective_at` is now in the past
     (`succession_times_invalid`).
   - **Anchors.** If anchors were copied out of this NA, a restore to a point
     before the newest held anchor is an evidence-loss event. Follow
     *After a restore* in {doc}`evidence-anchors`.
   - **Revocations.** Attestation, certificate and grant revocations made
     after the backup are gone, so that trust material is usable again.
     Re-apply each one.
   - **Revocation feed sequence.** The feed's sequence goes back with the
     restore. Partners that imported a later feed refuse the next one
     (`409 stale_sequence`) until the sequence passes theirs again. Tell
     them.
6. Start the Network Authority.
7. Check:

   ```bash
   curl -fsS http://127.0.0.1:8443/healthz
   curl -fsS http://127.0.0.1:8443/readyz
   curl -fsS http://127.0.0.1:8443/connectome.json
   ```

8. Export audit events after restore and attach them to the incident record.

See {doc}`backup-restore` for the full procedure.

## Revocation Blast-Radius Review

Use this after any membership attestation or treaty revocation that may affect
another sovereign.

1. Fetch `/connectome.json`.
2. Review `revocation_blast_radius`.
3. Identify accepting sovereigns affected by the revoked trust material.
4. Confirm each affected sovereign has imported the latest feed.
5. Record expected accept/reject behavior for the affected attestations.
