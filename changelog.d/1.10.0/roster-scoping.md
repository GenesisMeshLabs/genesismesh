### Security

- **A standard-tier operator key sees only its own attestations.**
  `GET /attestations` gave every operator key the full list, with each
  subject's public key, roles, claims and attestation ID. From 1.10.0, a
  `standard` key lists only the attestations whose subject it is, by the rule
  that binds decisions to their subject since 1.9.2: its key bound as
  `subject_public_key`, or with none bound its key ID as `subject_id`. A
  signed `GET /attestations/<id>` from a `standard` key answers another
  subject's attestation as `404 attestation_not_found`, exactly as for an ID
  that does not exist. `read` and `privileged` keys see every attestation, as
  before. (ops/plan-v1.9.2.md R10, acceptance tests 15 to 17.)
- **Unchanged:** an unsigned `GET /attestations` still returns only the count,
  and an unsigned `GET /attestations/<id>` stays public: the ID is known only
  to the holder and the parties it was shown to.
- A signed read by ID is now authenticated like the list (read tier or
  above, the admin rate limit); a request whose signature does not verify gets
  `401 admin_auth_failed`. Before 1.10.0 the signature headers were ignored.

### Upgrading

- **Tooling that lists attestations with a `standard` key** sees only that
  key's own attestations. Give a `read` key to anything that must see the
  whole roster, such as dashboards and audits.
