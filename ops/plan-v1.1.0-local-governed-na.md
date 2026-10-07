# Plan v1.1.0 (part 2) — Local Governed Network Authority for SDK Developers

Drafted as 1.2.0. It merged (genesismesh #55) before 1.1.0 was tagged, and
the Maintainer folded it into 1.1.0 on 2026-10-07 (Decisions, 10): one
release with the signed images of `plan-v1.1.0.md`. Its release gate is
the one in `plan-v1.1.0.md`.

## Context

A pilot controller built only on `genesis-mesh-sdk` (TypeScript) against a
Network Authority installed from PyPI ran its whole governed lifecycle (45
checks: policies, attestations, `governedAction`, executor evidence, history,
export, reconciliation, least privilege). It also showed what every SDK
developer hits before writing a line of controller code:

1. **`genesis-mesh na start` cannot run a governed NA.** It reads only the
   config file and `--evidence-store`: no `BOUNDARY_POLICY_ENFORCEMENT`, no
   second operator key, no tiers, no rate limits
   (`docs/reference/configuration.md`). The pilot had to ship its own
   `run-na.py` that imports `genesis_mesh.na_service.wsgi`.
2. **No command creates an operator key.** `keygen` offers `root`,
   `network-authority` and `node`; the pilot used `keygen node` for its
   standard-tier controller key, then a script to put the public key and tier
   into `OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON`.
3. **No page explains how to develop an SDK controller against a local NA:**
   which keys, which tiers, which settings, how to reset.
4. **The admin rate limit stops governed workloads.** Every governed action is
   one admin call (`/admin/boundary/evaluate`). At the default of 30 a minute
   per address the pilot failed within seconds; it needed
   `NA_RATE_LIMIT_ADMIN_PER_MINUTE=600`. A production controller in one
   container has the same problem.
5. A `429` carries no `Retry-After`, so a client cannot tell when to retry.

This release fixes those in the core, so the pilot's helper scripts reduce to
two CLI commands and a docs link.

## Scope

### In scope

- `genesis-mesh na start --env-file PATH`: the production settings
  (`load_settings`) from a file, served by the development server.
- `genesis-mesh init --env-file PATH`: writes a starter settings file for that
  NA.
- `genesis-mesh keygen operator`: an operator key pair, optionally registered
  with its tier in a settings file.
- Admin rate limit default raised from 30 to 300 a minute per address, with a
  new limit on failed admin authentications (30 a minute per address) so
  unauthenticated floods stay as limited as today.
- `Retry-After` on every `429`.
- Docs: a new page *Develop against a local Network Authority*, updates to the
  configuration reference, the CLI reference and the SDK index.
- SDK READMEs (TypeScript, Go, .NET, Rust) link the new page; they are bumped
  with the release train anyway.

### Out of scope

- A public TypeScript governed-lifecycle example in `sdk-typescript`
  (follow-up: port the pilot's flow once this release ships).
- SDK retry on `429` using `Retry-After` (SDK releases, after this one).
- Any change to admin signatures, tiers or which routes use which tier.
- `na start` under Gunicorn: it stays the development server; production keeps
  the container image or `start.sh`.
- Console sign-in (Entra ID): its own plan.
- The PHP SDK.

## Implementation

### 1. One app factory for production and `na start`

Move the body of `genesis_mesh/na_service/wsgi.py` (genesis load, signer,
`create_app`, `ProxyFix`) into `build_app(settings: NASettings)` in a new
`genesis_mesh/na_service/app_factory.py`. `wsgi.py` becomes
`app = build_app(load_settings())`, unchanged in behavior. One code path means
`na start --env-file` cannot drift from what Gunicorn serves.

### 2. `na start --env-file PATH`

- Parses `KEY=VALUE` lines (comments and blank lines skipped, no shell
  expansion, no new dependency) into a mapping, then `load_settings(mapping)`
  and `build_app`. The process environment is not read, so a stray variable in
  the developer's shell cannot change the NA.
- With `--env-file`, `--config`, `--db-path` and `--evidence-store` are
  refused (one source of configuration); `--host` and `--port` still choose
  the bind address.
- Without `--env-file`, `na start` behaves exactly as in 1.0.2.
- Relative paths in the file resolve against the file's directory.
- The startup log names the file and the settings that matter for development
  (enforcement, evidence store, operator key IDs with tiers, rate limits); no
  key material.

### 3. `init --env-file PATH`

Writes the settings for the network `init` just created: `GENESIS_FILE`,
`NA_PRIVATE_KEY_FILE`, `NA_KEY_ID`, `DB_PATH`, `OPERATOR_PUBLIC_KEYS_JSON` and
`OPERATOR_KEY_TIERS_JSON` (the init operator key, `privileged`),
`EVIDENCE_STORE=on`, `BOUNDARY_POLICY_ENFORCEMENT=required`,
`NA_PROXY_HOPS=0`. Refuses to overwrite an existing file. The file holds paths
and public keys only, never private key material.

### 4. `keygen operator`

```
genesis-mesh keygen operator --output PATH --key-id ID [--tier read|standard|privileged] [--env-file PATH]
```

- Writes the key pair like the other `keygen` commands and prints the public
  key.
- `--tier` defaults to `standard`: least privilege for a controller.
- With `--env-file`, adds or replaces the key's entry in
  `OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON` in that file,
  keeping every other line as it was. Refuses if the key ID already exists
  with a different public key, unless `--replace` is given.

The pilot's setup then becomes:

```
genesis-mesh init --config local/genesis-mesh.toml --home local/.genesis-mesh --env-file local/na.env
genesis-mesh keygen operator --output local/.genesis-mesh/keys/controller --key-id controller --env-file local/na.env
genesis-mesh na start --env-file local/na.env --port 9443
```

### 5. Admin rate limit

- `RateLimits.admin` default 30 → 300 (`NA_RATE_LIMIT_ADMIN_PER_MINUTE`
  unchanged; a deployment that set it keeps its value).
- New `RateLimits.admin_auth_failures`, default 30, from
  `NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE`. Each failed admin
  authentication (bad signature, unknown key, stale timestamp, replayed nonce,
  insufficient tier) counts in `admin_auth_failed:{address}`. While that
  bucket is full, admin requests from the address get `429` before signature
  verification and without an audit event each; one `admin_auth_throttled`
  audit event per address per window records the throttling.
- Both limiter stores gain a read-only `exceeded(key, limit, window)` so the
  pre-check does not consume a slot; the database store reads the same
  window row it counts in, so the limit holds across workers and HA
  instances.
- Tests: 300 valid calls in a minute pass; the 301st gets `429`; 30 failed
  calls from an address throttle the 31st, valid or not, without verification
  or audit; another address is unaffected; both stores; `HA` mode with the
  database store.

### 6. `Retry-After`

`RateLimitError` responses carry `Retry-After: 60` (the window length, an
upper bound). The response body is unchanged.

### 7. Docs

- New `docs/sdk/local-network-authority.md`, in the SDK index toctree:
  install from PyPI in a venv, the three commands above, the key and tier
  table (privileged for setup, standard for the controller, the executor key
  for evidence), the settings and why, resetting data versus resetting the
  trust domain, sizing the admin rate limit for a controller in production.
  Language-neutral, with one TypeScript snippet; each SDK README links it.
- `docs/reference/configuration.md`: replace "`na start` reads none of these"
  with the `--env-file` behavior; document the new default and the new
  variable.
- CLI reference: `na start --env-file`, `init --env-file`, `keygen operator`.
- `docs/operations/upgrade.md`: the admin default change and what to do if a
  deployment relied on 30.

## Security notes

- **Rate limit raised for authenticated callers only.** Unauthenticated or
  failing admin traffic is held to 30 a minute per address, the same as
  today, and no longer writes an audit row per request once throttled, so the
  audit-flood protection is stronger than in 1.0.2. Valid signed traffic gets
  300; a compromised key is bounded by its tier, as before.
- **No new trust path.** Signatures, tiers, nonces and the audience binding are
  unchanged. `na start --env-file` serves the same app as production, so a
  developer tests the real enforcement rather than the 1.0 single-key
  shortcut.
- **Settings files hold no secrets.** `init` and `keygen operator` write paths
  and public keys only; private keys stay in their files with the existing
  permissions. The docs page says to keep the whole `local/` directory out of
  version control.
- **`keygen operator` defaults to `standard`**, never `privileged`.
- `na start` still binds `127.0.0.1` by default and still warns it is the
  development server.

## Success Criteria

- [x] `wsgi.py` and `na start --env-file` build the app through one function;
      existing wsgi and container tests pass unchanged
- [x] The three-command setup above runs a NA with enforcement required, two
      operator keys with their tiers and the evidence store (Windows by hand;
      Linux through the CLI tests in CI)
- [x] The TypeScript pilot passes against it without its own `run-na.py` or
      `write-env.py` (45 of 45 checks, default limits, 2026-10-07)
- [x] Admin limit and failed-auth limit tests pass for both limiter stores
      (the database store on SQLite here, on PostgreSQL in CI's PostgreSQL job)
- [x] Every `429` has `Retry-After`
- [x] `na start` without `--env-file` keeps its 1.0 configuration (existing
      tests); it gets the new rate-limit defaults like every NA
- [x] Docs build under `sphinx -W`; the new page is in the SDK section

## Release Gate

See `plan-v1.1.0.md`.

## Decisions

1. **Version 1.2.0, superseded by 10** (Maintainer, 2026-10-07): new CLI options, a new command,
   a new setting and a changed default are new surfaces, a minor under
   `docs/development/versioning.md`.
2. **Admin default 300** (Maintainer, 2026-10-07): five a second per address.
   600 worked for the pilot's burst; 300 covers a steady controller and keeps
   the step from 30 moderate. Deployments set their own value either way.
3. **Failed-auth limit 30** (Maintainer, 2026-10-07): equal to the old admin
   limit, so nothing an attacker can do gets cheaper.

Made during implementation and review (2026-10-07):

4. **`PORT` in the settings file.** `init --env-file` writes `PORT` from
   `--na-port` and `na start --env-file` listens on it (`--port` overrides),
   so the endpoint and the port cannot drift apart.
5. **Overwrites only with `--force`.** `init --env-file` refuses an existing
   file unless `--force` is given, and refuses a path that is another output
   of `init`. `keygen operator` refuses existing key files, unlike the other
   `keygen` commands: its key is registered in a settings file, and a silent
   overwrite would leave the registration out of sync. It checks the settings
   file first, writes the key files, then registers, removing the new files
   if registration fails.
6. **Every failed admin authentication counts**, including missing or
   oversized headers and invalid timestamps, and a key below the route's tier
   (403). The bucket is per address, so a standard key probing privileged
   routes also throttles a privileged key at the same address; the docs say
   so.
7. **Environment exceptions.** `na start --env-file` takes the NA's settings
   only from the file. Logging, the `env` key provider's seed and Azure
   identity variables are still read from the environment, as documented.
   Empty values count as unset.
8. **Startup summary on stderr** (`click.echo`), not the log: it is for the
   developer at the terminal.
9. **Ship skill 6A/6B do not apply**: no new trust primitive or signed model;
   `docs/sdk/local-network-authority.md` is the walkthrough.
10. **Released as 1.1.0** (Maintainer, 2026-10-07): #55 merged before
    `v1.1.0` was tagged and 1.1.0 was never released, so this work ships in
    1.1.0 rather than a 1.2.0 that would follow it within days. Both are new
    surfaces in a minor version; the `v1.2.0` annotations became `v1.1.0`.
