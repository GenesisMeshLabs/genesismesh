### Security

- **Operator key holders change only with a second holder's approval, also
  after a restart or a retention run.**
  - `OPERATOR_KEY_HOLDERS_JSON` now names holders at the first start with
    `EVIDENCE_OUT_OF_BAND=on` only. A key added later, and a key whose public
    key changes under the same key ID, is recorded as its own holder until a
    holder change names one. 1.3.0 let the configuration name a new key's
    holder, and a re-keyed key kept its holder.
  - Retention carried old holder records forward after newer ones, and the
    last record in store order won: an approved holder change reverted, the
    configuration could then rename the key, and one person could approve
    their own change. Holders are now read in order of `effective_at`.
  - An approval is refused when the key that proposed the change was
    revoked, removed from the configuration or re-keyed since it proposed
    (`409 holder_change_proposer_revoked`, a new code).
  - A holder must be a string of 1 to 128 characters: `null`, numbers and an
    empty string in `OPERATOR_KEY_HOLDERS_JSON` are refused at start, where
    1.3.0 recorded `"None"` or `""`. The values of
    `OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON` must be strings
    too.

### Upgrading

- Set `OPERATOR_KEY_HOLDERS_JSON` before the first start with the records on.
  After that, name the holder of a new or re-keyed operator key with
  `POST /admin/operator-keys/<key_id>/holder`, approved by a second named
  holder; the NA logs a warning when the configuration names a holder it
  does not record.
