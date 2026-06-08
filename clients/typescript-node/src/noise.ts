/**
 * Noise XX handshake + transport, implementing exactly the suite the Genesis
 * Mesh Python node uses:
 *
 *     Noise_XX_25519_AESGCM_SHA256   prologue = "GenesisMeshNoiseXX"
 *
 * Patterns (Noise spec §7.5, XX):
 *     -> e
 *     <- e, ee, s, es
 *     -> s, se
 *
 * The Python responder sends its certificate (base64) as the message-2 payload
 * and the initiator sends its certificate as the message-3 payload, both
 * encrypted by the running handshake (confirmed in
 * genesis_mesh/transport/noise_handshake.py).
 *
 * Crypto primitives:
 *   DH   = X25519                 (@noble/curves)
 *   HASH = SHA-256                (@noble/hashes)
 *   AEAD = AES-256-GCM            (node:crypto), 96-bit nonce =
 *          0x00000000 || big-endian uint64 counter   (Noise spec §12)
 *
 * No length framing is added: each Noise message is one transport frame
 * (one WebSocket binary message), matching the Python implementation.
 */
import { createCipheriv, createDecipheriv } from "node:crypto";
import { sha256 } from "@noble/hashes/sha2";
import { hmac } from "@noble/hashes/hmac";
import { x25519 } from "@noble/curves/ed25519";

const HASHLEN = 32;
const DHLEN = 32;
const TAGLEN = 16;
export const PROLOGUE = new TextEncoder().encode("GenesisMeshNoiseXX");
const PROTOCOL_NAME = new TextEncoder().encode("Noise_XX_25519_AESGCM_SHA256");

function concat(...arrs: Uint8Array[]): Uint8Array {
  let len = 0;
  for (const a of arrs) len += a.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const a of arrs) {
    out.set(a, off);
    off += a.length;
  }
  return out;
}
function eq(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

// --- HKDF (Noise variant, HMAC-SHA256) ---------------------------------------
function hkdf(ck: Uint8Array, ikm: Uint8Array, numOutputs: 2 | 3): Uint8Array[] {
  const tempKey = hmac(sha256, ck, ikm);
  const o1 = hmac(sha256, tempKey, Uint8Array.of(0x01));
  const o2 = hmac(sha256, tempKey, concat(o1, Uint8Array.of(0x02)));
  if (numOutputs === 2) return [o1, o2];
  const o3 = hmac(sha256, tempKey, concat(o2, Uint8Array.of(0x03)));
  return [o1, o2, o3];
}

// --- AES-256-GCM AEAD --------------------------------------------------------
function gcmNonce(counter: bigint): Uint8Array {
  const nonce = new Uint8Array(12); // first 4 bytes zero
  const view = new DataView(nonce.buffer);
  view.setBigUint64(4, counter, false); // big-endian counter in last 8 bytes
  return nonce;
}
function aeadEncrypt(
  key: Uint8Array,
  counter: bigint,
  ad: Uint8Array,
  plaintext: Uint8Array,
): Uint8Array {
  const cipher = createCipheriv("aes-256-gcm", key, gcmNonce(counter));
  cipher.setAAD(ad);
  const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return concat(ct, cipher.getAuthTag());
}
function aeadDecrypt(
  key: Uint8Array,
  counter: bigint,
  ad: Uint8Array,
  ciphertext: Uint8Array,
): Uint8Array {
  if (ciphertext.length < TAGLEN) throw new Error("ciphertext too short");
  const ct = ciphertext.subarray(0, ciphertext.length - TAGLEN);
  const tag = ciphertext.subarray(ciphertext.length - TAGLEN);
  const decipher = createDecipheriv("aes-256-gcm", key, gcmNonce(counter));
  decipher.setAAD(ad);
  decipher.setAuthTag(tag);
  return new Uint8Array(Buffer.concat([decipher.update(ct), decipher.final()]));
}

// --- CipherState -------------------------------------------------------------
export class CipherState {
  private n = 0n;
  constructor(private k: Uint8Array | null) {}
  hasKey(): boolean {
    return this.k !== null;
  }
  encryptWithAd(ad: Uint8Array, plaintext: Uint8Array): Uint8Array {
    if (this.k === null) return plaintext;
    return aeadEncrypt(this.k, this.n++, ad, plaintext);
  }
  decryptWithAd(ad: Uint8Array, ciphertext: Uint8Array): Uint8Array {
    if (this.k === null) return ciphertext;
    return aeadDecrypt(this.k, this.n++, ad, ciphertext);
  }
}

// --- SymmetricState ----------------------------------------------------------
class SymmetricState {
  ck: Uint8Array;
  h: Uint8Array;
  cs: CipherState = new CipherState(null);

  constructor() {
    // InitializeSymmetric(protocol_name): name <= HASHLEN, so right-pad with 0.
    const h = new Uint8Array(HASHLEN);
    h.set(PROTOCOL_NAME);
    this.h = h;
    this.ck = h.slice();
  }
  mixKey(ikm: Uint8Array): void {
    const [ck, tempK] = hkdf(this.ck, ikm, 2);
    this.ck = ck;
    this.cs = new CipherState(tempK.subarray(0, 32));
  }
  mixHash(data: Uint8Array): void {
    this.h = sha256(concat(this.h, data));
  }
  encryptAndHash(plaintext: Uint8Array): Uint8Array {
    const ct = this.cs.encryptWithAd(this.h, plaintext);
    this.mixHash(ct);
    return ct;
  }
  decryptAndHash(ciphertext: Uint8Array): Uint8Array {
    const pt = this.cs.decryptWithAd(this.h, ciphertext);
    this.mixHash(ciphertext);
    return pt;
  }
  split(): [CipherState, CipherState] {
    const [tempK1, tempK2] = hkdf(this.ck, new Uint8Array(0), 2);
    return [new CipherState(tempK1.subarray(0, 32)), new CipherState(tempK2.subarray(0, 32))];
  }
}

interface KeyPair {
  priv: Uint8Array;
  pub: Uint8Array;
}
function genEphemeral(): KeyPair {
  const priv = x25519.utils.randomPrivateKey();
  return { priv, pub: x25519.getPublicKey(priv) };
}
function dh(keypair: KeyPair, pub: Uint8Array): Uint8Array {
  return x25519.getSharedSecret(keypair.priv, pub);
}

export interface HandshakeResult {
  send: CipherState;
  receive: CipherState;
  /** Remote static public key (X25519), bound to the peer certificate. */
  remoteStaticPub: Uint8Array;
  /** Decrypted payload carried in the final read message (peer certificate b64). */
  remotePayload: Uint8Array;
}

/**
 * Minimal XX HandshakeState supporting just the two roles this node needs.
 * Returns transport CipherStates plus the remote static key and remote payload.
 */
export class HandshakeState {
  private sym = new SymmetricState();
  private e: KeyPair | null = null;
  private re: Uint8Array | null = null;
  private rs: Uint8Array | null = null;

  private constructor(
    private readonly initiator: boolean,
    private readonly s: KeyPair,
  ) {
    this.sym.mixHash(PROLOGUE);
  }

  static create(initiator: boolean, staticPriv: Uint8Array): HandshakeState {
    return new HandshakeState(initiator, {
      priv: staticPriv,
      pub: x25519.getPublicKey(staticPriv),
    });
  }

  // --- token helpers ---
  private writeE(out: Uint8Array[]): void {
    this.e = genEphemeral();
    out.push(this.e.pub);
    this.sym.mixHash(this.e.pub);
  }
  private readE(buf: Uint8Array, off: { i: number }): void {
    this.re = buf.subarray(off.i, off.i + DHLEN);
    off.i += DHLEN;
    this.sym.mixHash(this.re);
  }
  private writeS(out: Uint8Array[]): void {
    out.push(this.sym.encryptAndHash(this.s.pub));
  }
  private readS(buf: Uint8Array, off: { i: number }): void {
    const hasKey = this.sym.cs.hasKey();
    const len = hasKey ? DHLEN + TAGLEN : DHLEN;
    const temp = buf.subarray(off.i, off.i + len);
    off.i += len;
    this.rs = this.sym.decryptAndHash(temp);
  }
  private mixDH(token: "ee" | "es" | "se"): void {
    let shared: Uint8Array;
    if (token === "ee") shared = dh(this.e!, this.re!);
    else if (token === "es")
      shared = this.initiator ? dh(this.e!, this.rs!) : dh(this.s, this.re!);
    else /* se */ shared = this.initiator ? dh(this.s, this.re!) : dh(this.e!, this.rs!);
    this.sym.mixKey(shared);
  }

  /** Initiator: write message 1 (-> e). */
  writeMessage1(): Uint8Array {
    const out: Uint8Array[] = [];
    this.writeE(out);
    out.push(this.sym.encryptAndHash(new Uint8Array(0)));
    return concat(...out);
  }
  /** Responder: read message 1 (-> e). */
  readMessage1(msg: Uint8Array): void {
    const off = { i: 0 };
    this.readE(msg, off);
    this.sym.decryptAndHash(msg.subarray(off.i));
  }
  /** Responder: write message 2 (<- e, ee, s, es) with `payload`. */
  writeMessage2(payload: Uint8Array): Uint8Array {
    const out: Uint8Array[] = [];
    this.writeE(out);
    this.mixDH("ee");
    this.writeS(out);
    this.mixDH("es");
    out.push(this.sym.encryptAndHash(payload));
    return concat(...out);
  }
  /** Initiator: read message 2 (<- e, ee, s, es); returns responder payload. */
  readMessage2(msg: Uint8Array): Uint8Array {
    const off = { i: 0 };
    this.readE(msg, off);
    this.mixDH("ee");
    this.readS(msg, off);
    this.mixDH("es");
    return this.sym.decryptAndHash(msg.subarray(off.i));
  }
  /** Initiator: write message 3 (-> s, se) with `payload`; returns transport ciphers. */
  writeMessage3(payload: Uint8Array): { msg: Uint8Array; result: HandshakeResult } {
    const out: Uint8Array[] = [];
    this.writeS(out);
    this.mixDH("se");
    out.push(this.sym.encryptAndHash(payload));
    const [c1, c2] = this.sym.split();
    return {
      msg: concat(...out),
      result: { send: c1, receive: c2, remoteStaticPub: this.rs!, remotePayload: new Uint8Array(0) },
    };
  }
  /** Responder: read message 3 (-> s, se); returns transport ciphers + initiator payload. */
  readMessage3(msg: Uint8Array): HandshakeResult {
    const off = { i: 0 };
    this.readS(msg, off);
    this.mixDH("se");
    const remotePayload = this.sym.decryptAndHash(msg.subarray(off.i));
    const [c1, c2] = this.sym.split();
    return { send: c2, receive: c1, remoteStaticPub: this.rs!, remotePayload };
  }
}

export { eq as constantTimeEqual };
