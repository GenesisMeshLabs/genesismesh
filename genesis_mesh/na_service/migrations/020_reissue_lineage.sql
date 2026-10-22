-- v1.8.0: re-issue lineage for attestations and treaties.
--
-- At a key succession the NA re-issues, under the new key, the attestations
-- and treaties the old key signed that are still valid past the old key's
-- vouching horizon. A re-issued record gets a new ID; lineage_id links every
-- copy (the first copy's ID), reissued_from names the copy it replaces and
-- superseded_by the copy that replaced it. The old copy stays active, so the
-- grants and decisions resting on its ID keep verifying; superseded_by is
-- advisory and lists show only the newest copy. Revoking any copy revokes the
-- whole lineage. The statements are the same for SQLite and PostgreSQL.

ALTER TABLE membership_attestations ADD COLUMN lineage_id TEXT;
ALTER TABLE membership_attestations ADD COLUMN reissued_from TEXT;
ALTER TABLE membership_attestations ADD COLUMN superseded_by TEXT;
UPDATE membership_attestations SET lineage_id = attestation_id WHERE lineage_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_membership_attestations_lineage
    ON membership_attestations(lineage_id);

ALTER TABLE recognition_treaties ADD COLUMN lineage_id TEXT;
ALTER TABLE recognition_treaties ADD COLUMN reissued_from TEXT;
ALTER TABLE recognition_treaties ADD COLUMN superseded_by TEXT;
UPDATE recognition_treaties SET lineage_id = treaty_id WHERE lineage_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_recognition_treaties_lineage
    ON recognition_treaties(lineage_id);
