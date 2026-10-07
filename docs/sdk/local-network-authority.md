# Develop Against a Local Network Authority

A controller built on an SDK calls a Network Authority (NA) for decisions,
attestations and evidence. To develop and test one, run the NA locally from
the `genesis-mesh` package, configured as it will be in production: policies
required, the evidence store on, and separate keys for setup and for the
controller. This page sets that up with three commands (v1.1.0).

## Requirements

- Python 3.12 or later, for the NA
- The SDK for your language, from its registry (the Rust SDK is a Git
  dependency)

Keep everything local in one directory, here `local/`, and keep that
directory out of version control: it holds private keys.

## Set up

Install the NA in a virtual environment and activate it:

```bash
python -m venv local/venv
source local/venv/bin/activate          # Windows: local\venv\Scripts\Activate.ps1
pip install "genesis-mesh>=1.1"
```

Create the network, its settings and the controller's key:

```bash
genesis-mesh init \
    --config local/genesis-mesh.toml \
    --home local/.genesis-mesh \
    --network-name MY-PROJECT-DEV \
    --na-endpoint http://127.0.0.1:9443 \
    --na-port 9443 \
    --env-file local/na.env

genesis-mesh keygen operator \
    --output local/.genesis-mesh/keys/controller \
    --key-id controller \
    --tier standard \
    --env-file local/na.env
```

Start the NA and leave it running:

```bash
genesis-mesh na start --env-file local/na.env
```

It prints the settings it runs with and listens on `http://127.0.0.1:9443`
(`PORT` in the settings file, from `--na-port`);
`curl http://127.0.0.1:9443/healthz` returns `{"status":"ok"}`.

`na start --env-file` serves the same app as the production entry point and
the container image, with the settings in `local/na.env`. Without
`--env-file`, `na start` runs a demo NA with one operator key and default
settings, which cannot require policies.

## Keys and tiers

| Key | Tier | Used for |
|---|---|---|
| `operator-local` (`keys/operator.key`, from `init`) | privileged | Setup: publishing and activating policies, issuing and revoking attestations, registering executor keys |
| `controller` (`keys/controller.key`, from `keygen operator`) | standard | What the controller does at run time: `/admin/boundary/evaluate`, policy and evidence reads |
| The controller's executor key | (not an operator key) | Signing execution evidence; registered with the privileged key |

The controller key cannot publish policies, issue attestations or register
keys: the NA answers `403 insufficient_operator_tier`. Give your controller
the standard key and keep the privileged one for setup, in development as in
production.

In the SDK, each key is a key ID and the private key from its file, for
example in TypeScript:

```typescript
import { readFileSync } from 'node:fs';
import { GenesisMeshClient } from 'genesis-mesh-sdk';

// The key file holds comment lines and the base64 Ed25519 seed.
const seed = readFileSync('local/.genesis-mesh/keys/controller.key', 'utf8')
  .split('\n')
  .map((line) => line.trim())
  .find((line) => line && !line.startsWith('#'))!;

const client = new GenesisMeshClient({
  baseUrl: 'http://127.0.0.1:9443',
  signingKeyBase64: seed,
  keyId: 'controller',
});
```

## Settings

`init --env-file` writes `local/na.env`, which `keygen operator --env-file`
extends:

| Setting | Value | Why |
|---|---|---|
| `BOUNDARY_POLICY_ENFORCEMENT` | `required` | No governed action without a policy decision |
| `EVIDENCE_STORE` | `on` | Decision and execution history, export and offline verification |
| `NA_PROXY_HOPS` | `0` | Nothing sits in front of a local NA |
| `OPERATOR_PUBLIC_KEYS_JSON`, `OPERATOR_KEY_TIERS_JSON` | the keys above | Who may sign admin requests, and with which tier |
| `PORT` | from `--na-port` | Where `na start` listens; `--port` overrides it |
| `GENESIS_FILE`, `NA_PRIVATE_KEY_FILE`, `NA_KEY_ID`, `DB_PATH` | under `local/.genesis-mesh/` | Paths are relative to the settings file |

The file holds paths and public keys only. Add any variable from
{doc}`../reference/configuration` to it, one `KEY=VALUE` per line, and restart
the NA. The NA's settings come only from the file, not from your shell. A few
things are still read from the environment: logging (`GENESIS_LOG_LEVEL`,
`GENESIS_LOG_FORMAT`), the seed of the `env` key provider and Azure identity
variables.

## Rate limits

Every governed action is one admin call (`/admin/boundary/evaluate`). The NA
allows 300 admin requests a minute per client address
(`NA_RATE_LIMIT_ADMIN_PER_MINUTE`). It also allows 30 failed admin
authentications a minute per address
(`NA_RATE_LIMIT_ADMIN_AUTH_FAILURES_PER_MINUTE`): a bad or missing signature,
an unknown or revoked key, a stale timestamp, a replayed nonce, or a key below
the route's tier. After that, the address is refused for the rest of the
minute, valid requests included, with `429 admin_auth_throttled`. A `429`
carries `Retry-After`.

Locally, every client is `127.0.0.1` and shares that budget: a controller
retrying with a wrong key ID, or a key added without restarting the NA, also
blocks your setup scripts for a minute. Fix the failing client rather than
raising the limit.

In production, size the admin limit to the controllers that share one
address: a batch that rotates 1,000 secrets makes 1,000 admin calls.

## Reset

- Fresh data, same keys: stop the NA and delete `local/.genesis-mesh/na.db*`.
  Policies, attestations and executor key registrations go with the data: run
  your setup again.
- Everything: delete `local/` and set up again. This creates a new trust
  domain: earlier attestations and evidence no longer verify.

## Next

- {doc}`typescript/governance`: policies, attestations and governed actions
  with the TypeScript SDK.
- {doc}`../operations/container-images`: the same NA in production, from the
  signed container image.
