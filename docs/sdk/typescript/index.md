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
  baseUrl: 'http://127.0.0.1:9443',   // NA address
  signingKeyBase64: '<base64-seed>',   // 32-byte Ed25519 seed, base64-encoded
  keyId: 'operator-local',            // identifies the key in signatures
  timeout: 10_000,                    // optional milliseconds (default 10 s)
});
```

`signingKeyBase64` and `keyId` are only required for admin routes. You can
omit them when calling public verification endpoints only.

The client exposes 10 sub-clients:

```
client.agreement   client.boundary    client.policy
client.evidence    client.evidenceStore
client.attestation client.disclosure  client.consensus
client.dataUsage   client.health
```

`client.evidence` is trust evidence (v0.53); `client.evidenceStore` is the
v0.59 execution evidence store. Pass `signer` instead of `signingKeyBase64`
to sign admin requests with a key held elsewhere (for example an HSM).

## Governed secret lifecycles (v0.59.1)

The SDK covers the controller side of the secret governance pilots:

- {doc}`governance`: `governedAction` (decide, verify, act, record) and
  reconciliation against the NA history
- {doc}`evidence-store`: evidence store, attestation and policy clients,
  signers, retries and errors
- {doc}`offline-verification`: verifying decisions and evidence exports
  without the NA, and the canonical JSON rules
- {doc}`high-availability` (v0.60): failover across NA instances, readiness,
  and retryable conflicts
- {doc}`out-of-band-changes` (1.3.0): observations, break-glass records,
  judgements and the record outbox

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
:maxdepth: 1
:hidden:

sub-clients
auth
governance
evidence-store
offline-verification
high-availability
out-of-band-changes
```
