/**
 * Proves the TypeScript canonical encoder is byte-compatible with the Python
 * NA, and that @noble/curves verifies the live genesis root signature.
 *
 * Run: npm run test:canonical
 */
import { ed25519 } from "@noble/curves/ed25519";
import { canonicalizeExcluding } from "../src/canonical.js";
import type { JsonValue } from "../src/canonical.js";

const NA = process.env.GM_NA ?? "https://na.genesismesh.connectorzzz.com";

function b64ToBytes(b64: string): Uint8Array {
  return Uint8Array.from(Buffer.from(b64, "base64"));
}

async function main() {
  const res = await fetch(`${NA}/genesis`);
  if (!res.ok) throw new Error(`GET /genesis -> ${res.status}`);
  const genesis = (await res.json()) as Record<string, JsonValue>;

  const canonical = canonicalizeExcluding(genesis, ["signatures"]);
  console.log("canonical length:", canonical.length, "(Python oracle: 447)");

  const rootPub = b64ToBytes(genesis.root_public_key as string);
  const sigs = genesis.signatures as Array<{ key_id: string; sig: string }>;
  const msg = new TextEncoder().encode(canonical);

  let verified = false;
  for (const s of sigs) {
    if (ed25519.verify(b64ToBytes(s.sig), msg, rootPub)) verified = true;
  }

  console.log("root signature verifies:", verified);
  if (canonical.length !== 447 || !verified) {
    console.error("FAIL: canonical bytes or signature mismatch");
    process.exit(1);
  }
  console.log("PASS: TS canonical JSON is byte-compatible with the Python NA.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
