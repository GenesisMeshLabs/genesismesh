# Incident Response Runbooks

These runbooks are for managed sovereign operation. They are intentionally
plain: stop the bad trust path, preserve evidence, restore service, and document
what changed.

## Operator Key Compromise

Use this when an operator signing key may have been exposed.

1. Remove the compromised key from `OPERATOR_PUBLIC_KEYS_JSON` or the operator
   key environment file.
2. Restart the Network Authority.
3. Confirm old-key admin requests fail.
4. Rotate to a new operator key and record the new key ID.
5. Export audit events around the compromise window:

   ```bash
   genesis-mesh managed audit-export \
     --db-path /var/lib/genesis-mesh/na.db \
     --output ./incident-audit.jsonl
   ```

6. Review admin actions signed by the compromised key.
7. Revoke or supersede any trust material created by the compromised key.

## Network Authority Key Compromise

Use this when the NA signing key may have been exposed.

1. Stop the Network Authority.
2. Preserve the current DB and key material for incident analysis.
3. Generate a new sovereign or new NA key depending on policy.
4. Publish the replacement public trust material.
5. Re-issue affected certificates, attestations, treaties, and feeds as needed.
6. Notify recognizing sovereigns that old trust material must be rejected.
7. Record the migration in the incident log and release notes if public trust is
   affected.

An NA key compromise is a sovereign-level incident. Do not treat it as a normal
operator-key rotation.

## Bad Treaty Issued

Use this when a recognition treaty was issued with the wrong subject sovereign,
public key, role, validity window, or metadata.

1. Revoke the treaty:

   ```bash
   curl -X POST https://<na>/admin/recognition-treaties/<treaty-id>/revoke
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
   independently checked.
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
   be removed from state.
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

4. Start the Network Authority.
5. Check:

   ```bash
   curl -fsS http://127.0.0.1:8443/healthz
   curl -fsS http://127.0.0.1:8443/readyz
   curl -fsS http://127.0.0.1:8443/connectome.json
   ```

6. Export audit events after restore and attach them to the incident record.

## Revocation Blast-Radius Review

Use this after any membership attestation or treaty revocation that may affect
another sovereign.

1. Fetch `/connectome.json`.
2. Review `revocation_blast_radius`.
3. Identify accepting sovereigns affected by the revoked trust material.
4. Confirm each affected sovereign has imported the latest feed.
5. Record expected accept/reject behavior for the affected attestations.
