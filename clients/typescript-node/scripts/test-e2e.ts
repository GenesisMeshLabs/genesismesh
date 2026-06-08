/**
 * End-to-end peer test (no live NA needed): two MeshNodes, one listening and one
 * dialing, complete a Noise XX session, validate each other's certificates
 * (including the Ed25519->X25519 static-key binding), and exchange a DATA
 * message both directions.
 *
 * Certificates are minted locally by a throwaway "test NA" key, signed over the
 * same canonical JSON the real NA uses — so this exercises the full peer stack.
 *
 * Run: npx tsx scripts/test-e2e.ts
 */
import { Identity } from "../src/identity.js";
import { MeshNode } from "../src/node.js";
import { canonicalizeExcluding, type JsonValue } from "../src/canonical.js";
import type { GenesisBlock, JoinCertificate } from "../src/models.js";

const NETWORK = "TESTNET";
const testNa = Identity.generate();

function mintCert(nodeId: string, roles: string[]): JoinCertificate {
  const now = new Date();
  const cert: Record<string, JsonValue> = {
    cert_id: crypto.randomUUID(),
    node_public_key: nodeId,
    network_name: NETWORK,
    roles,
    issued_at: now.toISOString(),
    expires_at: new Date(now.getTime() + 3600_000).toISOString(),
    issued_by: "test-na",
    signatures: [],
  };
  const sig = testNa.sign(new TextEncoder().encode(canonicalizeExcluding(cert, ["signatures"])));
  cert.signatures = [{ key_id: "test-na", sig }];
  return cert as unknown as JoinCertificate;
}

function fakeGenesis(): GenesisBlock {
  return {
    network_name: NETWORK,
    network_version: "v0.1",
    root_public_key: testNa.publicKeyB64,
    network_authority: { public_key: testNa.publicKeyB64, valid_from: "", valid_to: "" },
    allowed_crypto_suites: ["ed25519", "x25519"],
    allowed_transports: ["quic"],
    policy_manifest: { hash: "sha256:test", url: null },
    bootstrap_anchors: [],
    signatures: [],
  };
}

function assert(cond: boolean, msg: string) {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
  console.log("ok -", msg);
}

async function main() {
  const idA = Identity.generate();
  const idB = Identity.generate();

  const nodeA = new MeshNode({ identity: idA, naEndpoint: "http://127.0.0.1:1" });
  const nodeB = new MeshNode({ identity: idB, naEndpoint: "http://127.0.0.1:1" });
  // Inject genesis + certs directly (skip live NA).
  (nodeA as any).genesis = fakeGenesis();
  (nodeB as any).genesis = fakeGenesis();
  nodeA.adoptCertificate(mintCert(idA.nodeId, ["role:anchor"]));
  nodeB.adoptCertificate(mintCert(idB.nodeId, ["role:client"]));
  // Silence heartbeat noise to the bogus NA.
  nodeA.on("warn", () => {});
  nodeB.on("warn", () => {});

  const gotOnA = new Promise<string>((resolve) =>
    nodeA.on("data", (d: { from: string; text: string | null }) => resolve(d.text ?? "")),
  );
  const gotOnB = new Promise<string>((resolve) =>
    nodeB.on("data", (d: { from: string; text: string | null }) => resolve(d.text ?? "")),
  );

  const aRegisteredB = new Promise<string>((resolve) =>
    nodeA.on("peer:connected", (p: { peerId: string }) => resolve(p.peerId)),
  );

  const port = await nodeA.listen(0, "127.0.0.1");
  assert(port > 0, `node A listening on :${port}`);

  const conn = await nodeB.connect(`127.0.0.1:${port}`);
  assert(conn.peerId === idA.nodeId, "node B connected and validated node A's certificate");
  assert((await aRegisteredB) === idB.nodeId, "node A accepted + validated node B and registered it");

  nodeB.sendData(idA.nodeId, "hello from B");
  assert((await gotOnA) === "hello from B", "node A received DATA from node B (B->A)");

  nodeA.sendData(idB.nodeId, "hello from A");
  assert((await gotOnB) === "hello from A", "node B received DATA from node A (A->B)");

  await nodeA.stop();
  await nodeB.stop();
  console.log("PASS: full peer stack e2e (Noise XX + cert binding + DATA both directions)");
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
