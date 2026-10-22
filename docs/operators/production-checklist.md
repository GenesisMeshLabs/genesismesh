# Production Checklist

The {doc}`quickstart` keeps every key on one VM and leaves most settings at
their defaults. That is fine while you set up. Before other sovereigns rely on
yours, work through this page. Each step names the setting it changes and
what the default is, because most of what a production sovereign needs is off
by default.

The steps assume one Network Authority host and an offline machine for the
root key. {doc}`../operations/pilot-deployment-profile` describes a full
deployment shape, and {doc}`security-checklist` is the review to run
afterwards.

## 1. Generate the root key offline

The root key signs the genesis block and every NA key succession. Whoever
holds it and the NA key can replace the NA's key history, so it never touches
the NA host.

On a machine that has never been and will never be on a network:

```bash
genesis-mesh keygen root --output root --key-id rs-2026-q4
```

Keep `root.key` on removable media, encrypted, in two places under the control
of the people accountable for the sovereign. Record who holds each copy. The
full ceremony is in {doc}`../operations/key-succession`.

`genesis-mesh init` also writes a root key, next to the NA key. Do not use
`init` for a production sovereign, or move its root key offline at once and
accept that it was generated on a networked machine.

## 2. Create the NA key and sign the genesis block

Generate the NA key where it will be kept (step 4), and carry only its public
key to the offline machine:

```bash
genesis-mesh keygen network-authority --output na --key-id na-2026-q4
```

On the offline machine, write the genesis block and sign it with the root key:

```bash
genesis-mesh genesis create --network-name EXAMPLE-SOVEREIGN \
  --root-key root.pub --na-key na.pub --output genesis.json
genesis-mesh genesis sign --genesis genesis.json \
  --root-private-key root.key --key-id rs-2026-q4 --output genesis.signed.json
```

Carry `genesis.signed.json` back. It holds only public keys and signatures.

## 3. Write the settings file

Keep the NA's settings in one file with absolute paths. The same file then
serves `genesis-mesh na doctor --env-file`, and its lines are the variables
the container or systemd unit sets ({doc}`../reference/configuration`). A `#`
starts a comment line; there are no comments after a value.

```text
GENESIS_FILE=/etc/genesis-mesh/genesis.signed.json
NA_KEY_ID=na-2026-q4
NA_PUBLIC_URL=https://na.example.org
NA_PROXY_HOPS=1
NA_DEPLOYMENT=managed
BOUNDARY_POLICY_ENFORCEMENT=required
EVIDENCE_STORE=on
```

| Setting | Default | Why change it |
|---|---|---|
| `NA_KEY_ID` | `na-2025-q1` | Name the key you generated; trust bundles and gateway policies refer to it. |
| `NA_PUBLIC_URL` | unset | Unset, the URLs the NA advertises follow each request's `Host`. |
| `NA_PROXY_HOPS` | `0` | Set it to the number of reverse proxies in front of the NA, or rate limits and audit addresses see the proxy. |
| `NA_DEPLOYMENT` | `local` | `managed` refuses to start when the root key is near the NA's files. |
| `BOUNDARY_POLICY_ENFORCEMENT` | `optional` | `required` refuses the legacy `/admin/boundary/decide` route. |
| `EVIDENCE_STORE` | `off` | Off, the NA keeps no hash-chained, anchored evidence. Entries are not written retroactively. |

Add operator keys with the lowest tier their work needs. Generate each on its
holder's machine and register it:

```bash
genesis-mesh keygen operator --output alice --key-id alice \
  --tier privileged --env-file /etc/genesis-mesh/na.env
genesis-mesh keygen operator --output monitor --key-id monitor \
  --tier read --env-file /etc/genesis-mesh/na.env
```

Keep privileged keys few. Configure at least two, so that one can revoke the
other (`409 last_active_operator_key` otherwise).

## 4. Keep the NA key in a key store

With the default `file` provider the NA key is a file on the host. Prefer a
store the operator owns:

- `NA_KEY_PROVIDER=env` with `NA_PRIVATE_KEY_SEED_FILE` pointing at a
  platform secret (Docker or Kubernetes secret, tmpfs), or
- `NA_KEY_PROVIDER=azure-keyvault` with `AZURE_KEY_VAULT_URL` and
  `NA_KEY_SECRET_NAME`, read with a managed identity.

See {doc}`../operations/high-availability` for both. `NA_HA_MODE=on` refuses
the `file` provider.

## 5. Choose the database and rate-limit store

SQLite (`DB_PATH`) suits one instance. With it, the rate limiter counts in
memory, per Gunicorn worker: a client gets up to `WEB_CONCURRENCY` (default 4)
times each limit. PostgreSQL (`DATABASE_URL`) shares state across instances
and counts rate limits in the database (`RATE_LIMIT_STORE=database`, its
default there). `NA_HA_MODE=on` requires PostgreSQL, a non-file key provider
and the shared rate limiter.

## 6. Check the host

```bash
genesis-mesh na doctor --env-file /etc/genesis-mesh/na.env
```

`na doctor` fails when it finds the root private key where the NA's files
live (the directories of the genesis block, the NA key, the database and the
settings file, their parents and three levels below) or in a variable, and
when the NA key cannot sign now. It warns while `NA_DEPLOYMENT` is `local`,
and when `NA_RETENTION_REQUIRE_ARCHIVE=off`. The search is bounded (5,000
files, no symbolic links), so `OK` does not prove the root key is absent from
the host; the ceremony in step 1 does that.

Start the NA (container image, or Gunicorn under systemd), then check
`/readyz`. It names the database path or host to anyone who can reach it, so
filter it at the proxy if that matters.

## 7. Keep the anchors yourself

With the evidence store on, the NA signs a store anchor every
`NA_ANCHOR_INTERVAL_SECONDS` (default 3600). Fetch the anchors to a machine
the NA's host cannot write to, on a schedule, with a `read` key:

```bash
genesis-mesh evidence anchors fetch --na https://na.example.org \
  --na-public-key na.pub --out /audit/anchors \
  --operator-key monitor.key --operator-key-id monitor
```

A record removed or rewritten after its anchor was fetched then fails
verification. Write audit packs and archives as described in
{doc}`../operations/audit-packs` and {doc}`../operations/audit-and-retention`.
`NA_RETENTION_REQUIRE_ARCHIVE` is on by default: retention removes nothing an
archive does not cover.

## 8. Plan the key succession

The NA key can be replaced while the sovereign keeps its identity: the root
key signs a succession on the offline machine, the new key proves it is held,
and the NA countersigns and records it ({doc}`../operations/key-succession`).
Plan one before the key's end, and rehearse it.

A succession needs the outgoing NA key at the NA and the root key offline. A
lost NA key, an NA key past its `new_valid_to`, or an exposed root key cannot
be recovered this way: the sovereign then needs a new identity.

After a succession, counterparts' treaties still name your old key. Ask each
counterpart to issue a new treaty that names the new one
(see {doc}`treaty-lifecycle`).

## 9. Back up

Back up the database (`genesis-mesh managed backup` for SQLite, `pg_dump` for
PostgreSQL), the settings file and the genesis block, and keep a copy of every
NA key a succession names. See {doc}`../operations/backup-restore`.
