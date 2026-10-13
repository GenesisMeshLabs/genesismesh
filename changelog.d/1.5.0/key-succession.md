### Added

- **NA key succession.** A `KeySuccessionRecord` names the Network Authority's next key, signed by the root
  key (kept offline), by the new key (proof that it is held) and by the outgoing NA key; the genesis key and the successions are the NA's key history
  (`GET /na/key-history`). The store, exports, anchors, retention checkpoints, audit packs, agreement trust
  (treaties and NA-issued attestations and agreements) and the verify routes accept an NA signature by the key
  valid at the record's own time, so records signed before and after a succession keep verifying. Record one
  with `genesis-mesh na succession history`, `sign` (offline, with the root key file), `prove` (where the new
  key lives) and `submit`
  (`POST /admin/na/succession`, privileged); the NA countersigns it and, with the evidence store on, records a
  `key_succession` entry. From the succession's `effective_at` the outgoing key signs nothing
  (`503 na_key_succeeded`); an instance may start with the new key before then, signs nothing and reports not
  ready until it takes effect.
- `genesis-mesh evidence verify-export --key-history <file> --root-key <key>` verifies an export across a
  succession; `na verify-db --genesis <file>` verifies the database's key history from the genesis block's
  root key and places each key in time.
- Mesh nodes follow the key history: they read `GET /na/key-history`, adopt it when it verifies from the root
  key their genesis block names, cache it, and check join certificates, policies and CRLs with the NA key
  valid at each one's `issued_at`.
- `/sovereign.json` adds `signing_key` and `network_authority.valid_to_enforced`, and links the key history.

### Security

- `valid_to` is enforced for every key a succession names: it signs nothing at or after its `new_valid_to`
  (`503 na_key_expired`), and verifiers refuse records it signed after it. The genesis key's `valid_to` is
  still shown and not enforced: deployments created before 1.5.0 carry a 90-day one.
- A record signed by a key of the NA's history outside that key's validity window is refused as
  `na_key_not_valid_at_time` (new reason code), in the store, exports, anchors, packs and decision
  verification.

### Upgrading

- Migration 017 rebuilds the evidence table on SQLite (new entry kinds `key_succession` and `archive`) and
  adds the key history and archive tables; at its first start the NA records its genesis key as the first
  entry of the key history. A 1.5 database cannot be opened by 1.4.
- Verifiers before 1.5 refuse the `key_succession` and `archive` entry kinds (`unknown_entry_kind`); the NA
  writes them only when an operator records a succession or an archive. Upgrade the SDKs and tools that read
  your exports first.
