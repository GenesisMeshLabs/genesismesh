# Offline verification

Use `verifyBoundaryDecision` for signature, expiry and expected policy and
attestation bindings. Supply `now` only for historical audits. An accepted DENY
has `accepted: true` and `authorized: false`; acceptance means the artifact
verified, not that execution is allowed.

Signature helpers are available for decisions, attestations, policies,
justifications, revocation feeds, execution records and retention checkpoints.
`attestationDigest`, `policyDigest`, `policySetDigest` and `executionDigest`
reproduce the Python reference digests.

```typescript
import { parseExportLines, verifyEvidenceEvents } from 'genesis-mesh-sdk';

const result = verifyEvidenceEvents(parseExportLines(ndjson), {
  naPublicKeys: [trustedNaPublicKey],
  executorKeys,
});
if (!result.verified) {
  throw new Error(JSON.stringify(result.failures));
}
```

Supply trusted public keys independently of the export. Executor keys include
`key_id`, `public_key` and `executor_sovereign_id`. Retired keys remain useful for
historical verification. Unknown keys and missing signatures fail verification.

`parseExportLines` rejects malformed event envelopes and unsupported schema
versions. `verifyEvidenceEvents` checks envelopes, payload digests, signatures,
execution windows, capabilities, store ordering and both execution chains. Invalid
payloads are reported as failures. For a filtered history use `contiguous: false`;
this permits gaps in the store sequence but still checks adjacent store links and
resource chains. A partial resource chain needs a signed `checkpoint` with its
prior resource heads. A valid export proves the supplied records; it does not
prove that an external source supplied every record in the original store.

## Agreements, license policies and data access intents

From 0.61.0 the SDK verifies agreements and data usage records offline, with the
reason codes of the Python reference, and signs data access intents as an agent.

```typescript
import {
  createDataAccessIntent, parseJson, seedSigner, verifyAgreement,
  verifyDataAccessIntent, verifyDataLicensePolicySignature,
} from 'genesis-mesh-sdk';

const agreement = parseJson(agreementText) as AgreementRecord;
const a = verifyAgreement(agreement, [offererPublicKey], [responderPublicKey]);
// a.accepted, a.reason: 'accepted' | 'invalid_offerer_signature' | ...

verifyDataLicensePolicySignature(policy, [licensorPublicKey]); // boolean

const intent = await createDataAccessIntent({
  agent_sovereign_id: 'bank-a', decision_id: decision.decision_id,
  sources: [{ source_id: 'db-prod', source_type: 'proprietary', owner_sovereign_id: 'org-a', classification_tags: [] }],
  access_types: ['read'], estimated_volume_bytes: 1_048_576,
}, seedSigner(agentSeed, 'bank-a'));
const v = verifyDataAccessIntent(intent, policy, [agentPublicKey]);
// v.valid, v.violation_reason, v.violations
```

`verifyAgreement` checks both signatures over the agreed body and, when given,
the expected graph digest. `verifyDataAccessIntent` checks the agent signature,
then expiry, licensed sources, prohibited classifications, permitted access
types and the volume cap, and reports every violation. Read agreements with
`parseJson`: a signed float such as `1.0` must survive parsing.

These verifiers pass the shared `interop` conformance vectors
(`tests/fixtures/conformance/interop.json`), and the core's cross-language
scenario runs them against a live Network Authority.

## Canonical JSON and numeric limits

The SDK escapes non-ASCII text and DEL, orders object keys by Unicode code point,
and uses Python-compatible float notation. SDK-generated evidence timestamps use
Pydantic's microsecond form. No runtime dependencies are required.

Use the SDK's `parseJson` for received JSON that will be verified. The transport
and export parser already do this. On Node.js 22+, it remembers integral float
lexemes such as `90.0`, including nested values in justification proofs. Ordinary
`JSON.parse`, `JSON.stringify`, object copying and `structuredClone` can discard
that information. Preserve received artifacts and use the supplied canonical
functions for signing or digests. Keep metadata integers within JavaScript's safe
integer range and prefer strings for identifiers and precise quantities. Integer
literals beyond that range are parsed as `bigint` and canonicalized exactly.

## Validation commands

Run these in the `sdk-typescript` repository.

```sh
npm run typecheck
npm run build
npm run test:package
npm test
npm run test:e2e
```

The unit suite consumes `tests/fixtures/python-vectors.json`, verifying Python
signatures and digests and rejecting tampered copies. Regenerate the fixture with
`scripts/generate_vectors.py` using a Python interpreter with the core installed.

`test:e2e` uses `GM_E2E_PYTHON`, or the adjacent core's `.venv` interpreter, to start
a disposable NA on a loopback ephemeral port. It enables the evidence store and
required policy enforcement, generates temporary keys and database state, and
stops the NA afterwards. Only the test fixture's rate limiter is bypassed so
paging tests do not wait between requests. Real authentication, signatures,
policy evaluation, storage and rejection handling remain active. The callback
uses synthetic metadata; no cloud services are involved. This also checks that
Python accepts TypeScript-signed evidence.

Alternatively, set `GM_E2E_BASE_URL`, `GM_E2E_OPERATOR_SEED`,
`GM_E2E_NA_PUBLIC_KEY` and optionally `GM_E2E_OPERATOR_KEY_ID` to use an isolated
NA prepared for these tests. It must allow privileged setup and sufficient
requests. Tests create attestations, policies and evidence and update the active
recognition policy, so use a disposable instance. The ordinary unit-test command
skips live tests unless one of the E2E environment variables enables them.
