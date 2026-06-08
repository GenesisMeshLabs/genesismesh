/**
 * Wire models. These mirror the Python pydantic models. For anything that gets
 * signature-verified (genesis, certificate) we ALSO keep the raw JSON object so
 * we can canonicalize the exact bytes the NA signed — see `crypto.ts`.
 */
import type { JsonValue } from "./canonical.js";

export interface Signature {
  key_id: string;
  sig: string;
}

export interface GenesisBlock {
  network_name: string;
  network_version: string;
  root_public_key: string;
  network_authority: {
    public_key: string;
    valid_from: string;
    valid_to: string;
  };
  allowed_crypto_suites: string[];
  allowed_transports: string[];
  policy_manifest: { hash: string; url: string | null };
  bootstrap_anchors: Array<{ id: string; endpoint: string }>;
  signatures: Signature[];
}

export interface JoinCertificate {
  cert_id: string;
  node_public_key: string;
  network_name: string;
  roles: string[];
  issued_at: string;
  expires_at: string;
  issued_by: string;
  signatures: Signature[];
}

export interface PolicyManifest {
  policy_id: string;
  issued_at: string;
  issued_by: string;
  min_client_version: string;
  allowed_ports: number[];
  allowed_services: string[];
  signatures: Signature[];
}

/** Mesh peer message types (subset relevant to this node). */
export enum MessageType {
  PING = "ping",
  PONG = "pong",
  DISCONNECT = "disconnect",
  DATA = "data",
  DATA_ACK = "data_ack",
}

export interface MeshMessage {
  message_id: string;
  message_type: string;
  timestamp: number;
  sender_id: string;
  recipient_id: string | null;
  ttl: number;
  payload: Record<string, JsonValue>;
  signature: string | null;
}

/** Build a MeshMessage with the same defaults as the Python `MeshMessage`. */
export function makeMessage(
  type: MessageType,
  senderId: string,
  opts: Partial<MeshMessage> = {},
): MeshMessage {
  return {
    message_id: crypto.randomUUID(),
    message_type: type,
    timestamp: Date.now() / 1000,
    sender_id: senderId,
    recipient_id: opts.recipient_id ?? null,
    ttl: opts.ttl ?? 10,
    payload: opts.payload ?? {},
    signature: opts.signature ?? null,
  };
}

export function encodeMessage(msg: MeshMessage): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(msg));
}
export function decodeMessage(bytes: Uint8Array): MeshMessage {
  return JSON.parse(new TextDecoder().decode(bytes)) as MeshMessage;
}

/** Certificate validity check matching JoinCertificate.is_valid (±5 min skew). */
export function certIsValid(cert: JoinCertificate, now: Date = new Date()): boolean {
  const skewMs = 5 * 60 * 1000;
  const issued = Date.parse(cert.issued_at);
  const expires = Date.parse(cert.expires_at);
  return issued - skewMs <= now.getTime() && now.getTime() <= expires + skewMs;
}
