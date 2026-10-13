### Security

- **Read-tier evidence access.** Every evidence store read (`GET /admin/evidence`, `status`, `verify`, resource
  and vendor histories, resource heads, `export`, `GET executor-keys`), the audit pack route and the archive
  list accept a `read` key, so an auditor's key can produce a pack. Every route that changes the store or its
  keys still needs the standard or privileged tier and refuses a read key with `403
  insufficient_operator_tier` (tested route by route). To be recorded in `SECURITY.md` at release.

### Changed

- The Stage 2 and 3 routes (observations, break-glass, judgements, operator key holders, remediations and
  reviews) are stable in the public contract; the new routes and commands of 1.5.0 are beta, the records'
  signed forms and the pack format stable.
