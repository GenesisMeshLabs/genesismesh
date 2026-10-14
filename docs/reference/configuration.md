# Configuration Reference

Genesis Mesh uses `genesis-mesh.toml` for local CLI workflows and environment
variables for container startup.

## CLI Config Discovery

The `genesis-mesh` command looks for config in this order:

1. `--config <path>`
2. `GENESIS_MESH_CONFIG`
3. `./genesis-mesh.toml`
4. `~/.genesis-mesh/config.toml`

`genesis-mesh init` writes a local config by default. Without an explicit
`--home`, the config is `./genesis-mesh.toml`. With an explicit `--home` and no
`--config`, the config is written to `<home>/genesis-mesh.toml` so generated
keys, genesis material, and the pointer file stay together. `genesis-mesh join`
updates that config with node certificate and policy paths.

Example:

```toml
[network]
name = "USG"
version = "v0.1"
na_endpoint = "http://127.0.0.1:8443"

[paths]
home = ".genesis-mesh"
genesis = ".genesis-mesh/genesis.signed.json"
na_private_key = ".genesis-mesh/keys/na.key"
operator_private_key = ".genesis-mesh/keys/operator.key"
operator_public_key = ".genesis-mesh/keys/operator.pub"
node_private_key = ".genesis-mesh/keys/node.key"
node_certificate = ".genesis-mesh/node.cert.json"
policy = ".genesis-mesh/policy.json"

[na]
key_id = "na-local"
host = "127.0.0.1"
port = 8443

[operator]
key_id = "operator-local"
```

Private-key paths in this file are local secrets and must not be committed.

## Network Authority Environment

| Variable | Required | Description |
|---|---:|---|
| `SERVICE_ROLE` | no | Set to `na` for Network Authority startup. Defaults to `na`. |
| `GENESIS_FILE` | yes | Path to the signed genesis block. `start.sh` defaults it to `genesis.signed.json` in the working directory (`/data` in the container image). |
| `GENESIS_JSON` | no | `start.sh`: the signed genesis block itself, used when `GENESIS_FILE` does not exist. It is written to a private in-memory directory (`/dev/shm` when available) and removed from the environment. |
| `NA_PRIVATE_KEY_FILE` | with the `file` key provider | Path to the Network Authority private key. `start.sh` defaults it to `keys/na.key` in the working directory. |
| `NA_PRIVATE_KEY` | no | `start.sh`: the private key file's contents, used when `NA_PRIVATE_KEY_FILE` does not exist. Handled like `GENESIS_JSON`. Prefer a mounted file or the `env` provider with `NA_PRIVATE_KEY_SEED_FILE`. |
| `NA_KEY_PROVIDER` | no | `file` (default), `env` or `azure-keyvault`: where the signing key comes from (v0.60, see [High Availability](../operations/high-availability.md)). |
| `NA_PRIVATE_KEY_SEED` | with the `env` provider | Base64 Ed25519 seed injected by the platform's secret store. `start.sh` moves it to a private in-memory file at start, so the server processes do not carry it in their environment. |
| `NA_PRIVATE_KEY_SEED_FILE` | with the `env` provider | Path to a file holding the base64 seed, for Docker and Kubernetes secrets. Set this or `NA_PRIVATE_KEY_SEED`, not both (v1.0.2). |
| `NA_KEY_SEED_ENV` | no | Name of the variable that holds the seed for the `env` provider (default `NA_PRIVATE_KEY_SEED`); the file variant is that name with `_FILE` appended. |
| `AZURE_KEY_VAULT_URL` / `NA_KEY_SECRET_NAME` | with the `azure-keyvault` provider | Vault URL and the secret holding the seed; read with the managed identity (`AZURE_CLIENT_ID` selects a user-assigned one). |
| `DATABASE_URL` | no | `postgresql://...` stores all state in shared PostgreSQL (v0.60); `sqlite:///path` names a SQLite file. Unset: SQLite at `DB_PATH`. |
| `NA_HA_MODE` | no | `off` (default) or `on`; `on` refuses to start without PostgreSQL, a non-file key provider and shared rate limits. |
| `RATE_LIMIT_STORE` | no | `memory` or `database`; defaults to `database` on PostgreSQL. |
| `NA_KEY_ID` | no | Key ID named in the NA's signatures. Defaults to `na-2025-q1`; set it to the ID recorded in the NA key file (`na-local` for keys from `genesis-mesh init`) and keep it stable, since trust bundles and gateway policies refer to it. |
| `DB_PATH` | no | SQLite database path. Defaults to `genesis_mesh_na.db`; the container image sets `/data/genesis_mesh_na.db`. |
| `PORT` | no | HTTP bind port. Defaults to `8443`. |
| `WEB_CONCURRENCY` | no | Gunicorn worker count. Defaults to `4`. |
| `OPERATOR_PUBLIC_KEYS_JSON` | yes for admin APIs | JSON object mapping operator key IDs to base64 public keys. |
| `BOUNDARY_POLICY_ENFORCEMENT` | no | `optional` (default) or `required`; `required` refuses the legacy `/admin/boundary/decide` route. |
| `NA_ANCHOR_INTERVAL_SECONDS` | no | After an append to the evidence store, sign a new store anchor once this many seconds have passed since the last one (default 3600); `0` anchors only on `POST /admin/evidence/anchors`. See {doc}`../operations/evidence-anchors` (v1.2.0). |
| `EVIDENCE_STORE` | no | `off` (default) or `on`; `on` keeps an append-only record of decisions and execution evidence (v0.59). |
| `EVIDENCE_OUT_OF_BAND` | no | `off` (default) or `on`; `on` records observations, break-glass records, judgements, quarantine and registry entries in the evidence store, and opens their routes. Needs `EVIDENCE_STORE=on`. Turn it on once every verifier that reads exports runs 1.3: a 1.2 verifier refuses the new entry kinds. See {doc}`../operations/out-of-band-changes` (v1.3.0). |
| `NA_OBSERVATION_MAX_BACKLOG_SECONDS` | no | How long after a change an observation or break-glass record is still admitted (default 604800, 7 days); an older one is quarantined. See {doc}`../operations/out-of-band-changes` (v1.3.0). |
| `NA_OBSERVATION_CLOCK_SKEW_SECONDS` | no | Clock skew tolerated between observers, controllers and the NA (default 300) (v1.3.0). |
| `NA_JUDGE_ON_ADMISSION` | no | `on` (default) judges each observation and break-glass record when it is admitted; `off` leaves judging to the judge routes (v1.3.0). |
| `EVIDENCE_REMEDIATION` | no | `off` (default) or `on`; `on` records remediation and review entries in the evidence store, opens their routes and accepts boundary policies with `remediation`, `review_required` or `emergency` sections. Needs `EVIDENCE_OUT_OF_BAND=on`. Turn it on once every verifier that reads exports and every SDK that reads policies runs 1.4: a 1.3 verifier refuses the new entry kinds and a 1.3 SDK the new policy sections. See {doc}`../operations/remediation-and-reviews` (v1.4.0). |
| `EVIDENCE_GRANTS` | no | `off` (default) or `on`; `on` issues pre-issued grants, records grants, their uses and revocations in the evidence store, opens their routes, and lists revoked grants in the revocation feed. Needs `EVIDENCE_OUT_OF_BAND=on`. Turn it on once every verifier that reads exports, packs and the revocation feed runs 1.6: a 1.5 verifier refuses the new entry kinds and the feed's `revoked_grant_ids`. See {doc}`../operations/grants` (v1.6.0). |
| `NA_GRANT_MAX_VALIDITY_SECONDS` | no | The longest validity of a grant this NA issues: 60 to 86400 seconds (default 86400, 24 hours, the most any grant may have). A use is uploaded no later than its grant's validity after it was made (v1.6.0). |
| `NA_GRANT_MAX_USES` | no | The largest budget of a grant: 1 to 10000 (default 100) (v1.6.0). |
| `NA_GRANT_MAX_USES_PER_TIME_TOKEN` | no | The most uses that may follow the use a time token names: 1 to 1000 (default 10), and the default of a grant that names none (v1.6.0). |
| `NA_RETENTION_REQUIRE_ARCHIVE` | no | `on` (default) or `off`. With `on`, retention removes nothing past the last entry an unbroken run of archive records covers (`genesis-mesh audit archive`); `off` is for local development only. See {doc}`../operations/audit-and-retention` (v1.5.0). |
| `NA_DEPLOYMENT` | no | `local` (default) or `managed`. `managed` refuses to start when the root private key is found where the NA's files live (the directories of the genesis block, the NA key file and the database, their parent directory and three levels below it) or in an environment variable, when the NA key is the root key, or when `NA_RETENTION_REQUIRE_ARCHIVE` is `off`. See {doc}`../operations/key-succession` (v1.5.0). |
| `NA_DECISION_LIFETIME_SECONDS` | no | How long a boundary decision the NA issues stays valid: 1 to 300 seconds (default 300). Verifiers refuse a decision that outlives the key that signed it by more than 300 seconds past its hand-over (`decision_outlives_key`), so 300 is also the most this may be (v1.5.0). |
| `NA_REMEDIATION_GRACE_SECONDS` | no | Grace before a remediation is due when no policy gives one (default 86400, one day; 0 to 2592000): `remediation_due_at = judged_at + grace` (v1.4.0). |
| `NA_REMEDIATION_DEFAULT_MODE` | no | `alert_only` (default) or `cancel`: what a judged DENY leads to when no policy gives guidance (v1.4.0). |
| `NA_REVIEW_MAX_WAIVER_SECONDS` | no | Longest waiver a review may grant (default 2592000, 30 days; at most 90 days) (v1.4.0). |
| `NA_REVIEW_ACTOR_HOLDERS_JSON` | no | JSON object mapping observed actors (as sources report them) to operator key holders: a review decided by the holder an observed actor maps to is refused. An actor equal to a holder's name is that holder without an entry. The actor is not authenticated; see *Who may decide* in {doc}`../operations/remediation-and-reviews` (v1.4.0). |
| `OPERATOR_KEY_HOLDERS_JSON` | no | JSON object mapping operator key IDs to the person or team holding them, recorded in the evidence store at the first start with `EVIDENCE_OUT_OF_BAND=on`; each holder is a string of 1 to 128 characters. A key without an entry is its own holder (unnamed); an entry naming a key as its own holder is refused at start (v1.5.0), since reviews need a named holder. After that first start the configuration names no holder (v1.3.1): a key added later, or given a new public key, is its own holder until a holder change, which a second named holder approves, names one (v1.3.0). |
| `NA_MAX_REQUEST_BYTES` | no | Largest accepted request body in bytes (default 2097152, 2 MiB); larger requests get `413 request_entity_too_large` before they are parsed (v0.62). |
| `NA_RATE_LIMIT_ADMIN_PER_MINUTE` | no | Admin requests per minute per client address (default 300; 30 before v1.1.0). Every governed action calls `/admin/boundary/evaluate`, so size this to the controllers behind one address (v0.63.1). |
| `NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE` | no | Failed admin authentications per minute (default 30): a bad or missing signature, an unknown or revoked key, a stale timestamp, a replayed nonce, or a key below the route's tier. Failures that name an active operator key count against that key at the client address; failures that name no active key (none, an unknown or a revoked one) count against the address (v1.2.0). All failures from one address are also capped at four times the limit. Once a request's scope or its address is over the limit, a request that fails gets `429 admin_auth_throttled` instead of `401`, at its first failed check (headers, key, timestamp and nonce before the signature), and is neither counted nor audited again; a request correctly signed by an active operator key is still served (v1.3.1), so requests forged from a shared address cannot lock its operators out. One `admin_auth_throttled` audit event is written per scope and minute instead of one per request (v1.1.0). |
| `NA_RATE_LIMIT_VERIFY_PER_MINUTE` | no | Public verification and proof requests per minute per client address (default 60). |
| `NA_RATE_LIMIT_EVIDENCE_PER_MINUTE` | no | Execution evidence submissions per minute per client address (default 120). |
| `NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE` | no | Observation and break-glass submissions per minute per client address (default 120), a bucket of their own (v1.3.0). |
| `NA_RATE_LIMIT_AUDIT_PACKS_PER_HOUR` | no | Audit packs (`POST /admin/evidence/audit-pack`) per hour per client address (default 12), a bucket of their own: a pack reads and verifies up to 50,000 entries (v1.5.0). |
| `NA_RATE_LIMIT_NODE_PER_MINUTE` | no | Requests to the `/node/*` routes an edge agent calls, per minute per node key, counted after the request authenticates (default 120). Beta (v1.7.0). |
| `NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE` | no | Requests to the `/node/*` routes per minute per client address, counted before authentication (default 600); raise it when many edge nodes share one address. Beta (v1.7.0). |
| `NA_RATE_LIMIT_READ_PER_MINUTE` | no | Public policy reads per minute per client address (default 120). Enrollment (`/join`) limits are fixed anti-abuse controls. |
| `NA_PROXY_HOPS` | no | Number of reverse proxies in front of the NA whose `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` are trusted (default `0`, the NA reached directly; `1` before v1.3.1). Set it to the number of proxies in front, `1` behind one nginx or load balancer: with too many, clients can choose the address rate limits apply to (v0.62); with too few, every client shares the proxy's address. The proxy must set or overwrite each of these headers with values it chooses: nginx passes on a client's `X-Forwarded-Host` unless told otherwise, and `$host` and `$http_host` carry the `Host` the client sent, so use `proxy_set_header X-Forwarded-Host $server_name;` in a server block that names the NA, and set `NA_PUBLIC_URL`. |
| `NA_PUBLIC_URL` | no | The NA's public origin, e.g. `https://na.example.org` (v1.2.0). When set, `/sovereign.json` and `/swagger.json` advertise it whatever the request says; otherwise they take the scheme and host from the request as the trusted proxies leave it, which a client can influence through `Host` (a host that is not a valid origin gets `400`, v1.3.1). Set it in production. Since v1.3.1 the NA refuses to start unless it is exactly `http` or `https`, a DNS name or IP address (IPv6 in brackets), and an optional port of 1 to 65535, with nothing after it but a `/`. |
| `OPERATOR_KEY_TIERS_JSON` | yes for admin APIs | JSON object mapping each operator key ID to `read`, `standard` or `privileged`. **Required for every configured key — the service refuses to start otherwise.** |

`start.sh` refuses to start the Network Authority when `GENESIS_FILE` is
missing, when `NA_PRIVATE_KEY_FILE` is missing with the `file` key provider,
when the SQLite database's directory does not exist or is not writable by the
user it runs as, or when `NA_KEY_SEED_ENV` is not a variable name. The
Network Authority then refuses to start when the signing key does not match
the genesis block.

Every `429` response carries `Retry-After: 60`: each limit counts per minute,
so a minute is the longest a client waits (v1.1.0).

These variables configure the production entry point (`start.sh`, or Gunicorn
with `genesis_mesh.na_service.wsgi:app`). The local development server reads
them from a file: `genesis-mesh na start --env-file local/na.env` builds the
same app as the production entry point, with the settings in that file
(v1.1.0). The NA's settings come only from the file, not from the process
environment. Still read from the environment: logging (`GENESIS_LOG_LEVEL`,
`GENESIS_LOG_FORMAT`), the seed of the `env` key provider
(`NA_PRIVATE_KEY_SEED` or `NA_PRIVATE_KEY_SEED_FILE`, so the secret stays out
of the file) and Azure identity variables. Variables only `start.sh` reads
(`GENESIS_JSON`, `NA_PRIVATE_KEY`) have no effect in the file. `PORT` in the
file sets the port; `--port` overrides it.

The file has one `KEY=VALUE` per line, close to `docker run --env-file`: `#`
starts a comment line, values are taken literally (no quotes, no `export`, no
`${VAR}`), an empty value counts as unset, and a name set twice is refused.
`GENESIS_FILE`,
`NA_PRIVATE_KEY_FILE` and `DB_PATH` may be relative to the file's directory;
`genesis-mesh` resolves them, so the file is not meant for
`docker run --env-file`. `genesis-mesh init --env-file` writes one and
`genesis-mesh keygen operator --env-file` adds operator keys to it; see
{doc}`../sdk/local-network-authority`.

Without `--env-file`, `genesis-mesh na start` reads none of these variables:
it takes the genesis block, the keys, the database path and its one operator
key (privileged tier) from the config file, the evidence store setting from
`--evidence-store` or the config, and uses the defaults for everything else.

## Node Environment

| Variable | Required | Description |
|---|---:|---|
| `SERVICE_ROLE` | yes | Set to `node` for node startup. |
| `GENESIS_FILE` | yes | Path to the signed genesis block. |
| `GENESIS_JSON` | no | `start.sh`: the signed genesis block itself, used when `GENESIS_FILE` is unset or missing. |
| `INVITE_TOKEN` | yes | Single-use enrollment token from the network's operator. `start.sh` hands it to the node in a private file, not on its command line. |
| `BOOTSTRAP_URL` | no | Network Authority endpoint. Defaults to `http://localhost:8443`. |
| `NODE_ROLE` | no | Requested node role. Defaults to `anchor`. |
| `NODE_KEY_FILE` | no | Path to an existing node private key. Unset: the node generates a new key at every start. |
| `LISTEN_HOST` / `LISTEN_PORT` | no | Peer listener address. Default `0.0.0.0` and `0` (any free port). |
| `PERSISTENT` | no | Defaults to `true`: after enrolling, the node keeps running its peer runtime with heartbeats until stopped. `false` enrolls, prints its status and exits. |

For production node deployments, prefer explicit command arguments so the
genesis path, node key path, invite token, listen host, and listen port are clear
in deployment manifests.

## Files and Secrets

Private keys and databases should not be committed. The repository ignores:

- `genesis-mesh.toml`
- `.genesis-mesh/`
- `*.key`
- `*.pem`
- `keys/`
- `*.db`
- `*.db-shm`
- `*.db-wal`
- `*.sqlite`

Operator public keys are not private, but they are authorization data and should
be reviewed like any other security-sensitive configuration.
