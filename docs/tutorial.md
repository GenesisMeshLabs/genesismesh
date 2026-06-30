# Tutorial: Build and Verify Trust Evidence with the TypeScript SDK

This tutorial walks you through using the Genesis Mesh TypeScript SDK to build a
signed trust evidence record and then verify it using the public verify endpoint.
You will need a running Network Authority and Node.js 22 or later.

## Prerequisites

- A running Network Authority — see [](operators/quickstart.md) for setup steps
- Node.js >= 22
- An admin key pair registered with your NA (the `keyId` and base64-encoded
  private key produced during operator setup)

## Step 1: Install the SDK

```bash
npm install genesis-mesh-sdk
```

## Step 2: Create an admin client

Admin operations — issuing attestations, building evidence, recording boundary
decisions — require a signing key. Pass the base64-encoded Ed25519 private key
and the key ID registered with your NA:

```typescript
import { GenesisMeshClient } from "genesis-mesh-sdk";

const client = new GenesisMeshClient({
  baseUrl: "http://localhost:8000",
  signingKeyBase64: process.env.GM_ADMIN_KEY_B64,
  keyId: process.env.GM_ADMIN_KEY_ID,
});
```

Keep `GM_ADMIN_KEY_B64` in an environment variable or secrets manager — never
hard-code it in source.

## Step 3: Build trust evidence for a trust decision

A `TrustDecision` describes an authorization outcome between two sovereigns.
Pass one to `client.evidence.build()` to produce a signed `TrustEvidence` record:

```typescript
import { TrustDecision } from "genesis-mesh-sdk";

const decision: TrustDecision = {
  source_sovereign_id: "ALPHA-NA",
  target_sovereign_id: "BETA-NA",
  verdict: "allow",
  reason: "Recognition treaty active, attestation valid",
};

const evidence = await client.evidence.build(decision);

console.log(evidence.evidence_id); // e.g. "ev-3f8a21c0"
console.log(evidence.verdict);     // "allow"
console.log(evidence.signature);   // base64-encoded Ed25519 signature
```

The returned `TrustEvidence` object is self-contained: it includes the full
decision body, the issuer key ID, a timestamp, and the signature. You can
serialize it and hand it to any party that needs to verify the decision.

## Step 4: Verify the evidence

Verification uses the public `/verify/evidence` endpoint and requires no signing
key. Create a second client — or reuse the same one without credentials — and
call `client.evidence.verify()`:

```typescript
const publicClient = new GenesisMeshClient({
  baseUrl: "http://localhost:8000",
});

const result = await publicClient.evidence.verify({ evidence });

console.log(result.valid);  // true
console.log(result.reason); // "Signature valid"
```

`VerifyResult` always returns both fields. If `valid` is `false`, `reason`
explains why — for example, `"Unknown key ID"` or `"Signature mismatch"`.

## Step 5: Handle errors

The SDK throws `ValidationException` for requests that fail input validation
before reaching the NA, and `NetworkAuthorityException` for error responses from
the server. Wrap calls in a try/catch for production code:

```typescript
import { ValidationException, NetworkAuthorityException } from "genesis-mesh-sdk";

try {
  const evidence = await client.evidence.build({
    source_sovereign_id: "ALPHA-NA",
    target_sovereign_id: "BETA-NA",
    verdict: "invalid-verdict", // not in the allowed set
    reason: "testing",
  });
} catch (err) {
  if (err instanceof ValidationException) {
    console.error("Input rejected:", err.message);
    // "verdict must be one of: allow, block, escalate, warn"
  } else if (err instanceof NetworkAuthorityException) {
    console.error("NA returned error:", err.status, err.message);
  } else {
    throw err;
  }
}
```

## What's next

- [](sdk/typescript/sub-clients) — reference for all seven SDK sub-clients
  (Agreement, Attestation, Boundary, Consensus, DataUsage, Disclosure, Evidence)
- [](operators/quickstart.md) — set up a sovereign from scratch
- [](concepts/glossary.md) — definitions for every protocol term used above
