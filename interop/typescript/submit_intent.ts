/**
 * Leg 3 (TypeScript): create and sign data access intents with the TypeScript
 * SDK under the boundary decision from the Python leg, submit them to the NA's
 * /data-usage/verify, verify them offline, and write fixtures/ts_intent.json
 * (compliant), fixtures/ts_intent_denied.json and fixtures/ts_agent.json for
 * the C# leg. Also verifies the Python leg's artifacts offline, so three
 * implementations judge them.
 *
 *   node --experimental-strip-types submit_intent.ts ../fixtures
 */
import { generateKeyPairSync } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  GenesisMeshClient, createDataAccessIntent, parseJson, seedSigner, verifyAgreement, verifyBoundaryDecision,
  verifyDataAccessIntent, verifyDataLicensePolicySignature,
} from 'genesis-mesh-sdk';
import type {
  AgreementRecord, BoundaryDecision, BoundaryPolicy, DataAccessIntent, DataLicensePolicy, MembershipAttestation,
} from 'genesis-mesh-sdk';

const dir = process.argv[2] ?? '../fixtures';
// parseJson, not JSON.parse: it keeps integral floats such as the signed `1.0`
// in the agreement scope, without which the signature cannot be reproduced.
const read = <T>(name: string): T => parseJson(readFileSync(join(dir, name), 'utf8')) as T;
const write = (name: string, data: unknown) => writeFileSync(join(dir, name), JSON.stringify(data, null, 2) + '\n');

const na = read<{ base_url: string }>('na.json');
const keys = read<Record<string, string>>('public_keys.json');
const decision = read<BoundaryDecision>('boundary_decision.json');
const policy = read<DataLicensePolicy>('data_policy.json');

// The agent (bank-a, the licensee) holds its own Ed25519 key.
const { privateKey, publicKey } = generateKeyPairSync('ed25519');
const seed = (privateKey.export({ type: 'pkcs8', format: 'der' }) as Buffer).subarray(-32).toString('base64');
const agentPublicKey = (publicKey.export({ type: 'spki', format: 'der' }) as Buffer).subarray(-32).toString('base64');
const signer = seedSigner(seed, 'bank-a');

const compliant = await createDataAccessIntent({
  agent_sovereign_id: 'bank-a', decision_id: decision.decision_id,
  sources: [{ source_id: 'db-prod', source_type: 'proprietary', owner_sovereign_id: 'org-a', classification_tags: ['transactions'] }],
  access_types: ['read'], estimated_volume_bytes: 1_048_576, valid_for_seconds: 3600,
}, signer);
const denied = await createDataAccessIntent({
  agent_sovereign_id: 'bank-a', decision_id: decision.decision_id,
  sources: [{ source_id: 'db-hr', source_type: 'personal', owner_sovereign_id: 'org-a', classification_tags: ['pii-raw'] }],
  access_types: ['read', 'export'], estimated_volume_bytes: 50_000_000, valid_for_seconds: 3600,
}, signer);

// The NA verifies them (public route), and so does the SDK offline.
const client = new GenesisMeshClient({ baseUrl: na.base_url });
const verdicts: Record<string, Record<string, unknown>> = {};
for (const [name, intent] of [['ts_intent', compliant], ['ts_intent_denied', denied]] as [string, DataAccessIntent][]) {
  const online = await client.dataUsage.verify({ intent, policy, agent_public_keys: [agentPublicKey] });
  const offline = verifyDataAccessIntent(intent, policy, [agentPublicKey]);
  if (online.valid !== offline.valid || online.violation_reason !== offline.violation_reason) {
    throw new Error(`${name}: NA said ${JSON.stringify(online)}, SDK said ${JSON.stringify(offline)}`);
  }
  verdicts[name] = {
    valid: offline.valid, violation_reason: offline.violation_reason,
    violations: offline.violations.map(v => v.violation_type),
  };
  verdicts[`${name}_na`] = {
    valid: online.valid, violation_reason: online.violation_reason,
    violations: online.violations.map(v => v.violation_type),
  };
}

// The Python leg's artifacts, verified by a third implementation.
const now = new Date();
const policies = [read<BoundaryPolicy>('boundary_policy.json')];
for (const name of ['agreement', 'agreement_tampered']) {
  const r = verifyAgreement(read<AgreementRecord>(`${name}.json`), [keys['org-a']!], [keys['bank-a']!]);
  verdicts[name] = { accepted: r.accepted, reason: r.reason };
}
const decisionCases: [string, typeof policies | undefined, MembershipAttestation | undefined][] = [
  ['boundary_decision', policies, undefined],
  ['boundary_decision_denied', policies, undefined],
  ['boundary_decision_attestation', policies, read<MembershipAttestation>('attestation.json')],
  ['boundary_decision_tampered', undefined, undefined],
];
for (const [name, expectedPolicies, expectedAttestation] of decisionCases) {
  const r = verifyBoundaryDecision(read<BoundaryDecision>(`${name}.json`), {
    operatorPublicKeys: [keys.na!], now, expectedPolicies, expectedAttestation,
  });
  verdicts[name] = { accepted: r.accepted, reason: r.reason, authorized: r.authorized };
}
verdicts.data_policy = { valid: verifyDataLicensePolicySignature(policy, [keys.na!]) };

write('ts_intent.json', compliant);
write('ts_intent_denied.json', denied);
write('ts_agent.json', { agent_sovereign_id: 'bank-a', public_key: agentPublicKey });
mkdirSync(join(dir, 'results'), { recursive: true });
write(join('results', 'typescript.json'), { leg: 'typescript', verdicts });
for (const [name, v] of Object.entries(verdicts)) console.log(`[TS SDK] ${name}: ${JSON.stringify(v)}`);

if (verdicts.ts_intent!.valid !== true || verdicts.ts_intent_denied!.valid !== false) {
  console.error('[TS SDK] intent verification did not match the scenario');
  process.exit(1);
}
console.log('[TS SDK] intent: submitted  compliant: true');
