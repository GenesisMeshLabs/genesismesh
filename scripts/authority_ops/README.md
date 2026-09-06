# Reference authority maintenance

These adapters run beside the Python Network Authority, with its installed
dependencies. They are not part of the Rust gateway runtime.

`refresh_authority_crl.py --database DB --key-file KEY --issuer KEY_ID` renews
an expiring CRL using the existing authority identity and retains revocations.
Schedule hourly. It never renews signed genesis delegation.

`sync_authority_revocations.py --config CONFIG --watch` continuously imports
approved peers' signed feeds. Configuration contains `database`, `genesis_file`,
`interval_seconds` (15–3600), optional `status_file`, and 1–16 `peers` with
`network`, bare HTTPS `origin` and pinned `public_key`. Private HTTP requires
`allow_http: true`. An optional `feed_path` and `token_file` support authenticated
read-only relays; provision the least-privileged credential outside source control.

The consumer requires a valid, active locally signed recognition treaty binding
the peer key. It rejects stale/future feeds, bad signatures, unexpected issuers,
sequence rollback and conflicting revocations at the same sequence. Repeated
unchanged feeds do not write duplicate audit events. Existing imported revocations
remain retained by the authority store. Monitor `healthy` in the status file and
the process itself; sequence equality alone does not prove a running consumer.

Run isolated checks in the reference environment:

```text
python scripts/authority_ops/test_crl_refresh.py
python scripts/authority_ops/test_revocation_sync.py
```

Maintain database backups and retain sequence history through restarts. Test
membership acceptance followed by propagated revocation rejection at every peer.
Independent authority implementations need their own compatible consumers.
