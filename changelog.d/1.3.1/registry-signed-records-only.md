### Security

- **Judgements and operator key holders rest only on registry records the NA
  signed.** The NA replayed its registry as stored, so a record a database
  writer added under another key (a holder change, a policy activation)
  changed the holders and the policies a change was judged under. Each
  registry record's NA signature is now verified before use, once per
  record, and each `registry_record_id` counts once (the first in the
  store). A record left out is named in `registry_problems` and turns
  `registry_healthy` false in `GET /admin/evidence/status`.
