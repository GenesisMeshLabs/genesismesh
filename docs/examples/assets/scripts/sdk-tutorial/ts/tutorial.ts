// Step 2: create an admin client
import { BadRequestError, GenesisMeshClient } from "genesis-mesh-sdk";
import type { TrustDecision } from "genesis-mesh-sdk";

const baseUrl = process.env.GM_NA_URL ?? "http://127.0.0.1:9443";

const client = new GenesisMeshClient({
  baseUrl,
  signingKeyBase64: process.env.GM_ADMIN_KEY_B64,
  keyId: process.env.GM_ADMIN_KEY_ID,
});

// Step 3: build trust evidence for a decision
const decision: TrustDecision = {
  source_sovereign_id: "ALPHA-NA",
  target_sovereign_id: "BETA-NA",
  verdict: "allow",
  reason: "Recognition treaty active, attestation valid",
};

const evidence = await client.evidence.build({ decision });

console.log(evidence.evidence_id); // a UUID
console.log(evidence.verdict);     // "allow"
console.log(evidence.issued_at);   // ISO 8601 timestamp

// Step 4: verify the evidence
const publicClient = new GenesisMeshClient({ baseUrl });

const result = await publicClient.evidence.verify({ evidence });

console.log(result.accepted); // true
console.log(result.reason);   // "accepted"

// Step 5: handle errors
try {
  await client.evidence.build({
    decision: {
      source_sovereign_id: "ALPHA-NA",
      target_sovereign_id: "BETA-NA",
      verdict: "trusted", // not in the allowed set
      reason: "testing",
    },
  });
} catch (err) {
  if (err instanceof BadRequestError) {
    console.error(err.status, err.code, err.message);
    // 400 invalid_verdict verdict must be one of: allow, block, escalate, warn
  } else {
    throw err;
  }
}
