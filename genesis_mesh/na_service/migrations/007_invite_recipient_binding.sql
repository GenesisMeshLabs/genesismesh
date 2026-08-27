-- F-08: allow an invite token to be bound to a specific recipient public key.
-- NULL means unbound (pre-existing behavior).
ALTER TABLE invite_tokens ADD COLUMN recipient_public_key TEXT;
