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
  before. (ops/plan-v1.9.2.md R10, acceptance tests 15 to 17a, decisions 3 and 4.)
- **An unsigned read by ID gives the status only.** An unsigned
  `GET /attestations/<id>` returned the whole attestation, with its subject,
  public key, roles and claims, on the view that only the holder knows the
  ID. The public revocation feed lists every revoked ID, so anyone could read
  every revoked member's attestation. From 1.10.0 an unsigned read returns
  `attestation_id`, `status`, `revoked_at`, `revocation_reason`,
  `reissued_from` and `superseded_by`, without `attestation`, as an unsigned
  `GET /attestations` returns only the count (v1.0.2). An unknown ID is still
  `404 attestation_not_found`.
- A signed read by ID is now authenticated like the list (read tier or
  above, the admin rate limit); a request whose signature does not verify gets
  `401 admin_auth_failed`. Before 1.10.0 the signature headers were ignored.

### Upgrading

- **Tooling that lists attestations with a `standard` key** sees only that
  key's own attestations. Give a `read` key to anything that must see the
  whole roster, such as dashboards and audits.
- **Clients that read an attestation by ID without signing** get its status
  and lineage, not the attestation. Sign the read with an operator key (the
  TypeScript and .NET SDKs 1.10.0 sign `attestation.get` whenever the client
  has a key), or keep the attestation from when it was issued. A holder gets a
  re-issued copy from its operator.
