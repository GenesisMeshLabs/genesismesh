// Load and failover drill for a deployed Network Authority.
//
//   GM_URL=https://na.example.org GM_KEYS_FILE=keys.json node load-drill.mjs 120
//
// Runs governed actions (decide, record, submit evidence) on one resource
// chain for the given number of seconds, resubmitting a record until the NA
// answers. Kill and restart an NA instance meanwhile (docker compose kill na-a,
// docker compose start na-a). Afterwards every acknowledged record must be in
// the chain exactly once, the chain gap-free, its head as the NA reports it,
// and the store verifiable offline.
// GM_KEYS_FILE holds {"operator": {"seed"}, "na": {"public_key"}} (operator
// key id "ops"). Uses genesis-mesh-sdk from node_modules, or GM_SDK_ENTRY.
import { randomUUID, generateKeyPairSync } from 'node:crypto';
import { readFileSync } from 'node:fs';
const sdk = await import(process.env.GM_SDK_ENTRY ?? 'genesis-mesh-sdk');
const { GenesisMeshClient, ExecutionRecorder, seedSigner, verifyEvidenceEvents } = sdk;
const keys = JSON.parse(readFileSync(process.env.GM_KEYS_FILE, 'utf8'));
const url = process.env.GM_URL;
const gm = new GenesisMeshClient({ baseUrl: url, signingKeyBase64: keys.operator.seed, keyId: 'ops', timeout: 8000 });
const seconds = Number(process.argv[2] ?? 90);
const id = randomUUID();
const att = await gm.attestation.issue({ subject_id: `failover-${id}`, roles: ['role:client'], claims: { capabilities: ['secret.rotate'] } });
const { privateKey, publicKey } = generateKeyPairSync('ed25519');
const seed = privateKey.export({ type: 'pkcs8', format: 'der' }).subarray(-32).toString('base64');
const pub = publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('base64');
await gm.evidenceStore.registerExecutorKey({ key_id: `ctrl-${id}`, public_key: pub, executor_sovereign_id: `ctrl-${id}` });
const rec = new ExecutionRecorder({ executorSovereignId: `ctrl-${id}`, signer: seedSigner(seed, `ctrl-${id}`) });
const resource = `kv:failover-${id}/secret`;
const acked = { decisions: [], evidence: [] }; const errors = {}; let prior = null;
const note = e => { const k = `${e.status ?? e.code ?? e.name}`; errors[k] = (errors[k] ?? 0) + 1; };
const until = Date.now() + seconds * 1000;
while (Date.now() < until) {
  let decision;
  try { decision = (await gm.boundary.evaluate({ attestation_id: att.attestation_id, requested_capability: 'secret.rotate' })).decision; }
  catch (e) { note(e); await new Promise(r => setTimeout(r, 250)); continue; }
  acked.decisions.push(decision.decision_id);
  const record = await rec.record({ decision, executed_capability: 'secret.rotate', outcome: 'success', resource_id: resource,
    resource_action: prior ? 'rotate' : 'create', prior_resource: prior, execution_parameters: { secret_version: `v${acked.evidence.length + 1}` } });
  for (let attempt = 0; attempt < 40; attempt++) {           // resubmit the same record until the NA answers
    try { await gm.evidenceStore.submit(record); acked.evidence.push(record.evidence_id); prior = record; break; }
    catch (e) { note(e); await new Promise(r => setTimeout(r, 500)); }
  }
}
// Read the chain through the paged export (a long chain does not fit one history response).
const events = []; for await (const e of gm.evidenceStore.exportAll()) events.push(e);
const executions = events.filter(e => e.entry.entry_kind === 'execution' && e.payload.resource_id === resource);
const seqs = executions.map(e => e.entry.resource_sequence);
const ids = executions.map(e => e.payload.evidence_id);
const head = await gm.evidenceStore.resourceHead(resource);
const offline = verifyEvidenceEvents(events, { naPublicKeys: [keys.na.public_key], executorKeys: await gm.evidenceStore.listExecutorKeys() });
const result = {
  decisions: acked.decisions.length, evidence: acked.evidence.length, client_errors: errors,
  chain_gap_free: seqs.every((s, i) => s === i + 1), chain_matches_acked: JSON.stringify(ids) === JSON.stringify(acked.evidence),
  head_matches_chain: head?.resource_sequence === seqs.length, store_verified_offline: offline.verified, offline_failures: offline.failures.slice(0, 3),
};
console.log(JSON.stringify(result, null, 2));
process.exitCode = result.chain_gap_free && result.chain_matches_acked && result.head_matches_chain && result.store_verified_offline ? 0 : 1;
