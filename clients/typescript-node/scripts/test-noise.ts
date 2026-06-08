/**
 * Noise XX self-test: initiator <-> responder loopback in-process.
 * Proves the handshake completes, transport frames round-trip, and the
 * Ed25519->X25519 static-key derivation matches what a peer derives from our
 * certificate (the binding genesis_mesh/node/peer_identity.py enforces).
 *
 * Run: npx tsx scripts/test-noise.ts
 */
import { x25519, edwardsToMontgomeryPriv, edwardsToMontgomeryPub } from "@noble/curves/ed25519";
import { Identity } from "../src/identity.js";
import { HandshakeState, constantTimeEqual as eq } from "../src/noise.js";

function assert(cond: boolean, msg: string) {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
  console.log("ok -", msg);
}

const enc = new TextEncoder();

// 1) derivation consistency: pub(derivedPriv) == derivedPub
const id = Identity.generate();
assert(
  eq(x25519.getPublicKey(edwardsToMontgomeryPriv(id.seed)), edwardsToMontgomeryPub(id.publicKey)),
  "X25519 getPublicKey(edwardsToMontgomeryPriv) == edwardsToMontgomeryPub",
);

// 2) handshake loopback
const alice = Identity.generate(); // initiator
const bob = Identity.generate(); // responder
const aliceCert = enc.encode("ALICE_CERT_B64");
const bobCert = enc.encode("BOB_CERT_B64");

const hi = HandshakeState.create(true, alice.noiseStaticPrivate());
const hr = HandshakeState.create(false, bob.noiseStaticPrivate());

const m1 = hi.writeMessage1();
hr.readMessage1(m1);
const m2 = hr.writeMessage2(bobCert);
const bobCertSeen = hi.readMessage2(m2);
const { msg: m3, result: aliceTx } = hi.writeMessage3(aliceCert);
const bobTx = hr.readMessage3(m3);

assert(eq(bobCertSeen, bobCert), "initiator received responder cert payload in msg2");
assert(eq(bobTx.remotePayload, aliceCert), "responder received initiator cert payload in msg3");

// 3) static-key binding: each side's observed remote static == peer's derived static pub
assert(eq(aliceTx.remoteStaticPub, bob.noiseStaticPublic()), "initiator sees bob's derived static key");
assert(eq(bobTx.remoteStaticPub, alice.noiseStaticPublic()), "responder sees alice's derived static key");

// 4) transport round-trip both directions (multiple frames -> nonce increments)
const ad = new Uint8Array(0);
for (let i = 0; i < 3; i++) {
  const p = enc.encode(`a->b #${i}`);
  assert(eq(bobTx.receive.decryptWithAd(ad, aliceTx.send.encryptWithAd(ad, p)), p), `a->b frame ${i}`);
}
for (let i = 0; i < 3; i++) {
  const p = enc.encode(`b->a #${i}`);
  assert(eq(aliceTx.receive.decryptWithAd(ad, bobTx.send.encryptWithAd(ad, p)), p), `b->a frame ${i}`);
}

console.log("PASS: Noise XX self-test");
