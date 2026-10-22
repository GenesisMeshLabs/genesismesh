# TypeScript SDK

> **Added in v0.53.0** · Package: `genesis-mesh-sdk` · Source: `sdk-typescript/`

TypeScript client for the Genesis Mesh Network Authority HTTP API.
Ships ESM, CJS, and type declarations. Node.js ≥ 22 required.

---

## Install

```sh
npm install genesis-mesh-sdk
```

---

## `GenesisMeshClient`

```typescript
import { GenesisMeshClient } from 'genesis-mesh-sdk';

const client = new GenesisMeshClient({
  baseUrl: 'http://127.0.0.1:9443',   // the local NA from the local NA guide
  signingKeyBase64: '<base64-seed>',   // 32-byte Ed25519 seed, base64-encoded
  keyId: 'controller',                 // a standard-tier key registered with the NA
  timeout: 10_000,                     // optional milliseconds (default 10 s)
});
```

The examples use the local NA set up in {doc}`../local-network-authority`,
which listens on port 9443. `genesis-mesh init` without `--na-port` uses
8443. Use the privileged key (`operator-local` there) only for setup:
policies, attestations and executor keys. The tier each method needs is in
{doc}`sub-clients`.

`signingKeyBase64` and `keyId` are only required for admin routes. You can
omit them when calling public verification endpoints only.

The client exposes 12 sub-clients:

```
client.agreement   client.boundary    client.policy
client.evidence    client.evidenceStore
client.attestation client.disclosure  client.consensus
client.dataUsage   client.health      client.na
client.grants
```

`client.evidence` is trust evidence (v0.53); `client.evidenceStore` is the
v0.59 execution evidence store. `client.na` reads and verifies the NA's key
history (1.5.0). `client.grants` issues and reads pre-issued grants (1.6.0,
beta routes). Pass `signer` instead of `signingKeyBase64` to sign admin
requests with a key held elsewhere (for example an HSM).

## Guides

The guides cover the controller side of governed changes. The evidence
store (`EVIDENCE_STORE`), out-of-band records (`EVIDENCE_OUT_OF_BAND`),
remediation (`EVIDENCE_REMEDIATION`) and grants (`EVIDENCE_GRANTS`) are off
by default on an NA; each guide names the settings it needs.

{doc}`client`:

- {doc}`sub-clients`: every sub-client's methods and the key tier each needs
- {doc}`auth`: admin signatures, raw admin calls, errors and types
- {doc}`high-availability` (v0.60): failover across NA instances, readiness,
  and retryable conflicts

{doc}`governed-actions`:

- {doc}`governance`: `governedAction` (decide, verify, act, record) and
  reconciliation against the NA history
- {doc}`evidence-store`: evidence store, attestation and policy clients,
  signers, retries and errors
- {doc}`out-of-band-changes` (1.3.0): observations, break-glass records,
  judgements and the record outbox
- {doc}`remediation-and-reviews` (1.4.0): remediation records, the due queue,
  reviews and waivers, and urgent changes
- {doc}`grants` (1.6.0): pre-issued grants: issuing them, acting within one
  while the NA is unreachable, and verifying the records

{doc}`verification`:

- {doc}`offline-verification`: verifying decisions and evidence exports
  without the NA, and the canonical JSON rules
- {doc}`audit-packs` (1.5.0): the NA key history and key succession, and
  audit packs verified offline

Walkthroughs in the SDK repository, each a script with a recording of a real
run against a local NA:

- [A governed rotation](https://github.com/GenesisMeshLabs/sdk-typescript/blob/main/docs/walkthroughs/governed-rotation.md):
  set up a policy, an attestation and an executor key, run one allowed and one
  denied `governedAction`, then export the evidence and verify it offline.
- [Acting while the NA is down](https://github.com/GenesisMeshLabs/sdk-typescript/blob/main/docs/walkthroughs/acting-while-the-na-is-down.md):
  act under a pre-issued grant and fall back to break-glass while the NA is
  stopped, then sync the records when it is back.

---

## Build and test

```sh
cd sdk-typescript
npm run build   # ESM → dist/esm/ · CJS → dist/cjs/ · types → dist/types/
npm run typecheck
npm run test:package  # ESM and CommonJS entry points
npm test              # unit tests and core-generated vectors
npm run test:e2e      # live tests against a disposable local NA
```

```{toctree}
:maxdepth: 2
:hidden:

client
governed-actions
verification
```
