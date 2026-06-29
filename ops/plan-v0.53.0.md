# v0.53.0 Plan -- TypeScript SDK

## Positioning

The Genesis Mesh Python implementation is the protocol reference.  It is not
the right entry point for the majority of developers who will build on top of
the protocol.

Web application developers, MCP server authors, dashboard builders, and
operator tooling authors all work in TypeScript.  They should not need to run
a Python subprocess or call a CLI to perform a signature verification or check
a boundary decision.

The TypeScript SDK is not a reimplementation of the protocol.  It is a typed
client that wraps the stable Python API (defined in v0.51) via the Genesis
Mesh Network Authority HTTP interface.  The SDK handles:
- Authentication and key management
- Request serialization / response deserialization
- Typed error handling
- Node.js and browser compatibility (ESM, no native dependencies)

The SDK covers the stable surface only.  It does not expose internal or
experimental APIs.

v0.52 should prove:

> A TypeScript developer can verify a trust agreement, check boundary
> authorization, and submit a data access intent against a Genesis Mesh
> Network Authority using strongly-typed async functions, with no Python
> knowledge required.

## Design

### Package: `sdk/typescript/`

Published to npm as `genesis-mesh` (scoped: `@genesismeshlabs/sdk` if preferred).

```
sdk/typescript/
  package.json
  tsconfig.json
  src/
    client.ts          -- GenesisMeshClient: base HTTP client, auth
    agreement.ts       -- offer, counter, accept, cosign, verify
    boundary.ts        -- decide, verify
    evidence.ts        -- build, verify
    attestation.ts     -- model attestation: create, verify
    disclosure.ts      -- commit, prove, verify, nullifier
    consensus.ts       -- vote, build proof, verify
    data_usage.ts      -- intent, record, verify
    types.ts           -- all TypeScript interfaces matching protocol models
    errors.ts          -- typed error classes
    index.ts           -- public re-exports
  tests/
    agreement.test.ts
    boundary.test.ts
    ...
  README.md
```

### `GenesisMeshClient`

```typescript
export class GenesisMeshClient {
  constructor(options: {
    baseUrl: string;          // Network Authority URL
    signingKey?: string;      // base64url Ed25519 private key (for signing)
    apiKey?: string;          // Optional bearer token for NA auth
    timeout?: number;         // ms, default 10000
  });

  // Sub-clients
  readonly agreement: AgreementClient;
  readonly boundary: BoundaryClient;
  readonly evidence: EvidenceClient;
  readonly attestation: AttestationClient;
  readonly disclosure: DisclosureClient;
  readonly consensus: ConsensusClient;
  readonly dataUsage: DataUsageClient;
}
```

### Example: boundary check

```typescript
import { GenesisMeshClient } from 'genesis-mesh';

const client = new GenesisMeshClient({
  baseUrl: 'https://na.example.com',
  signingKey: process.env.OPERATOR_KEY,
});

const result = await client.boundary.decide({
  requestingAgent: 'agent-a',
  targetAgent:     'agent-b',
  capability:      'transactions.read',
  agreementId:     agreement.agreementId,
});

if (!result.allowed) {
  throw new Error(`Boundary denied: ${result.reason}`);
}
```

### Example: MCP server integration

```typescript
// In an MCP tool handler:
const intent = await client.dataUsage.createIntent({
  agentSovereignId: agentId,
  decisionId:       decisionId,
  sources:          [{ sourceId: 'db-prod', sourceType: 'proprietary', ownerSovereignId: 'org-a' }],
  accessTypes:      ['read'],
});

const { compliant, violations } = await client.dataUsage.verifyIntent({
  intent,
  policyId: activePolicyId,
});
```

### Types

All protocol model types are exported as TypeScript interfaces:

```typescript
export interface AgreementRecord { ... }
export interface BoundaryDecision { ... }
export interface TrustEvidence { ... }
export interface DataAccessIntent { ... }
// etc -- one interface per stable Python model
```

### Test strategy

Tests run against a local Network Authority started in a subprocess.
A mock server option is provided for CI environments without a full NA.

`npm test` runs Jest with the mock server.
`npm run test:integration` runs against a real NA (requires env vars).

### Build targets

- **ESM** (`dist/esm/`) -- for bundlers, Next.js, Deno
- **CJS** (`dist/cjs/`) -- for Node.js require()
- **Types** (`dist/types/`) -- `.d.ts` declarations

Minimum supported: Node.js 20 LTS, TypeScript 5.0.

## Success Criteria

- [x] `sdk-typescript/` at `C:\Source\GenesisMeshLabs\sdk-typescript\` (decoupled from main repo)
- [x] `GenesisMeshClient` with all 7 sub-clients
- [x] TypeScript interfaces for all stable protocol models (`src/types.ts`)
- [x] Typed error classes covering all API error codes (`src/errors.ts`)
- [x] Admin auth in dedicated `src/auth.ts` — canonicalJson, Ed25519 signing, header building
- [x] Jest test suite: 74 tests; all pass (`npm test`)
- [x] `npm run build` produces ESM + CJS + types
- [x] README with install + quick-start + all 7 sub-client examples
- [x] Sphinx build (Python side) clean with `-W`

## Release Gate

- [x] `sdk-typescript/package.json` version `0.53.0`
- [x] CHANGELOG entry (TypeScript SDK)
- [x] history.md updated with v0.53.0 entry
- [x] All prior Python tests continue to pass
