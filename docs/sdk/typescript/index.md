# TypeScript SDK

> **Added in v0.53.0** · Package: `genesis-mesh-sdk` · Source: `sdk-typescript/`

TypeScript client for the Genesis Mesh Network Authority HTTP API.
Ships ESM, CJS, and type declarations. Node.js ≥ 20 required.

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

The client exposes 7 sub-clients:

```
client.agreement   client.boundary    client.evidence
client.attestation client.disclosure  client.consensus
client.dataUsage
```

---

## Build and test

```sh
cd sdk-typescript
npm run build   # ESM → dist/esm/ · CJS → dist/cjs/ · types → dist/types/
npm test        # 74 Jest tests
```

Smoke test against a live NA:

```sh
cd sandbox/sdk-smoke
npm install
npm run smoke   # requires NA on http://127.0.0.1:9443
```

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
```
