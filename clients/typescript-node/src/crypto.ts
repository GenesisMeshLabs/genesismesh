/**
 * Signing / verification helpers matching the Python node's wire contracts:
 *
 *  - signed NA requests (`MeshNode._sign_request` / `verify_node_request_signature`)
 *  - signed models (genesis, join certificate) via `to_canonical_json()`
 *
 * The signature always covers canonical JSON (sorted keys, compact separators,
 * ASCII-escaped) of the payload with the `signature` field removed.
 */
import { ed25519, b64decode } from "./identity.js";
import { canonicalize, canonicalizeExcluding } from "./canonical.js";
import type { JsonValue } from "./canonical.js";
import type { Identity } from "./identity.js";

const enc = new TextEncoder();

/** Verify a base64 Ed25519 signature over `message` with a base64 public key. */
export function verifySignature(
  message: Uint8Array,
  signatureB64: string,
  publicKeyB64: string,
): boolean {
  try {
    return ed25519.verify(b64decode(signatureB64), message, b64decode(publicKeyB64));
  } catch {
    return false;
  }
}

/**
 * Verify a signature on a model object (raw JSON as received from the NA).
 * Canonicalizes the object with the `signatures` field removed — keeping every
 * other value (including datetime strings) exactly as received.
 */
export function verifyModelSignature(
  model: Record<string, JsonValue>,
  signatureB64: string,
  publicKeyB64: string,
): boolean {
  const canonical = canonicalizeExcluding(model, ["signatures"]);
  return verifySignature(enc.encode(canonical), signatureB64, publicKeyB64);
}

/** True if any signature in `model.signatures` verifies against `publicKeyB64`. */
export function verifyAnyModelSignature(
  model: Record<string, JsonValue>,
  publicKeyB64: string,
): boolean {
  const sigs = (model.signatures as Array<{ sig: string }> | undefined) ?? [];
  return sigs.some((s) => verifyModelSignature(model, s.sig, publicKeyB64));
}

/**
 * Add `timestamp`, `nonce`, and `signature` to a request payload, signed with
 * the node identity — byte-compatible with `MeshNode._sign_request`.
 *
 * The timestamp is an ISO-8601 string (`Date.toISOString()` → `...Z`), which
 * Python's `datetime.fromisoformat` (3.11+) parses. The NA only checks the
 * timestamp is within ±300s and that the signature covers the exact string.
 */
export function signRequest(
  payload: Record<string, JsonValue>,
  identity: Identity,
): Record<string, JsonValue> {
  const signed: Record<string, JsonValue> = {
    ...payload,
    timestamp: new Date().toISOString(),
    nonce: crypto.randomUUID(),
  };
  const canonical = canonicalize(omit(signed, "signature"));
  signed.signature = identity.sign(enc.encode(canonical));
  return signed;
}

function omit(obj: Record<string, JsonValue>, key: string): Record<string, JsonValue> {
  const copy: Record<string, JsonValue> = {};
  for (const k of Object.keys(obj)) if (k !== key) copy[k] = obj[k];
  return copy;
}
