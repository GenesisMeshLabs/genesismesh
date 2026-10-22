### Security

- **`/heartbeat` and `/renew` are rate limited.** Edge agents call them,
  and neither had a limit. Both now count against the per-address node
  budget (`node_address`, 600 a minute by default) that the `/node/*` routes
  already use.

### Fixed

- **A succession record names the NA's real key ID.** The genesis block
  names no key ID, so `na succession sign` wrote a made-up `na-key-1` as
  `previous_key_id`. `GET /na/key-history` now lists the running key's own
  ID for it, and the command uses that.
- **`/api-reference` shows the privileged tier of
  `/admin/agreements/counter`**, as enforced since 1.1.1.
- **Provider-neutral model examples.** The CLI help, a model field
  description and the agent-network example now use neutral example model
  IDs.
