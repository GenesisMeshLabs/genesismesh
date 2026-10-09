-- v1.2.0: signed store anchors.
--
-- An anchor is the NA's signature over the evidence store's head
-- (store_sequence and entry digest). Anchors form their own chain, outside
-- the store chain, so exports keep their format. They are append-only and
-- never removed, not even by retention: an auditor verifies history against
-- them years later.
--   * anchor_sequence is the primary key: no two anchors share a position
--   * one anchor per anchored store position
--   * anchors cannot be updated or deleted

CREATE TABLE IF NOT EXISTS evidence_anchors (
    anchor_sequence INTEGER PRIMARY KEY,
    store_sequence INTEGER NOT NULL UNIQUE,
    anchored_at TEXT NOT NULL,
    anchor_digest TEXT NOT NULL UNIQUE,
    anchor_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS evidence_anchors_no_update
BEFORE UPDATE ON evidence_anchors
BEGIN
    SELECT RAISE(ABORT, 'store anchors are append-only');
END;

CREATE TRIGGER IF NOT EXISTS evidence_anchors_no_delete
BEFORE DELETE ON evidence_anchors
BEGIN
    SELECT RAISE(ABORT, 'store anchors are append-only');
END;
