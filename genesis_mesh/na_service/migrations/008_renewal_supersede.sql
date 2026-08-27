-- F-20: renewal supersedes the predecessor certificate after a grace window.
-- revoke_after is the instant the predecessor stops being accepted and enters
-- the CRL. NULL means "never superseded" (pre-existing behavior).
ALTER TABLE issued_certs ADD COLUMN revoke_after TEXT;
