/**
 * Node identity: an Ed25519 keypair plus the X25519 static key derived from it
 * for the Noise XX transport.
 *
 * This mirrors the Python node exactly:
 *  - the Ed25519 *private key* is the 32-byte seed (PyNaCl `bytes(SigningKey)`),
 *    base64-encoded as `private_key_b64`
 *  - the public key is the 32-byte Ed25519 verify key, base64 as `public_key_b64`
 *    (this is the node's identity / `node_public_key` everywhere in the mesh)
 *  - the Noise static key is X25519 derived from Ed25519 via the same mapping
 *    libsodium uses (crypto_sign_ed25519_sk_to_curve25519). `@noble/curves`
 *    `edwardsToMontgomery*` reproduces that mapping, so a peer that derives the
 *    expected static key from our certificate's Ed25519 key gets the same bytes.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import {
  ed25519,
  x25519,
  edwardsToMontgomeryPriv,
  edwardsToMontgomeryPub,
} from "@noble/curves/ed25519";

export function b64encode(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64");
}
export function b64decode(b64: string): Uint8Array {
  return Uint8Array.from(Buffer.from(b64, "base64"));
}

export class Identity {
  /** 32-byte Ed25519 seed (the private key). */
  readonly seed: Uint8Array;
  /** 32-byte Ed25519 public key. */
  readonly publicKey: Uint8Array;

  private constructor(seed: Uint8Array, publicKey: Uint8Array) {
    this.seed = seed;
    this.publicKey = publicKey;
  }

  static generate(): Identity {
    const seed = ed25519.utils.randomPrivateKey();
    return new Identity(seed, ed25519.getPublicKey(seed));
  }

  static fromSeedB64(seedB64: string): Identity {
    const seed = b64decode(seedB64);
    if (seed.length !== 32) {
      throw new Error(`Ed25519 seed must be 32 bytes, got ${seed.length}`);
    }
    return new Identity(seed, ed25519.getPublicKey(seed));
  }

  get publicKeyB64(): string {
    return b64encode(this.publicKey);
  }
  get seedB64(): string {
    return b64encode(this.seed);
  }
  /** The node's identity string used throughout the mesh (== node_public_key). */
  get nodeId(): string {
    return this.publicKeyB64;
  }

  /** Ed25519 detached signature (64 bytes), base64-encoded. */
  sign(message: Uint8Array): string {
    return b64encode(ed25519.sign(message, this.seed));
  }

  /** X25519 static private key for Noise (clamped scalar), 32 bytes. */
  noiseStaticPrivate(): Uint8Array {
    return edwardsToMontgomeryPriv(this.seed);
  }
  /** X25519 static public key for Noise, 32 bytes. */
  noiseStaticPublic(): Uint8Array {
    return edwardsToMontgomeryPub(this.publicKey);
  }

  /** Persist identity to a small JSON file (private — keep it secret). */
  save(path: string): void {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(
      path,
      JSON.stringify(
        { algorithm: "ed25519", seed_b64: this.seedB64, public_key_b64: this.publicKeyB64 },
        null,
        2,
      ),
      { mode: 0o600 },
    );
  }

  static load(path: string): Identity {
    const data = JSON.parse(readFileSync(path, "utf-8"));
    return Identity.fromSeedB64(data.seed_b64);
  }

  /** Load identity from `path`, generating and saving a new one if absent. */
  static loadOrCreate(path: string): Identity {
    if (existsSync(path)) return Identity.load(path);
    const id = Identity.generate();
    id.save(path);
    return id;
  }
}

/** Derive the expected Noise static public key from an Ed25519 public key (base64). */
export function noiseStaticPublicFromEd25519B64(edPubB64: string): Uint8Array {
  return edwardsToMontgomeryPub(b64decode(edPubB64));
}

/** Re-export curve primitives used by the Noise transport. */
export { ed25519, x25519 };
