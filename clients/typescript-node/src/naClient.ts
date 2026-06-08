/**
 * Network Authority REST client. Talks the same HTTP/JSON + Ed25519-signed
 * request protocol as the Python `MeshNode`:
 *
 *   GET  /genesis            -> signed genesis block (verified against root key)
 *   GET  /policy             -> signed policy manifest
 *   GET  /crl                -> signed certificate revocation list
 *   GET  /nodes              -> enrolled node summary
 *   POST /join     (signed)  -> JoinCertificate
 *   POST /heartbeat(signed)  -> { ack, server_time }
 *   POST /renew    (signed)  -> JoinCertificate
 */
import { signRequest, verifyAnyModelSignature } from "./crypto.js";
import type { JsonValue } from "./canonical.js";
import type { Identity } from "./identity.js";
import {
  type GenesisBlock,
  type JoinCertificate,
  type PolicyManifest,
  certIsValid,
} from "./models.js";

export class NaError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "NaError";
  }
}

export class NaClient {
  readonly base: string;

  constructor(
    naEndpoint: string,
    private readonly identity: Identity,
  ) {
    this.base = naEndpoint.replace(/\/+$/, "");
  }

  private async get(path: string): Promise<Record<string, JsonValue>> {
    const res = await fetch(this.base + path);
    if (!res.ok) throw new NaError(`GET ${path} failed`, res.status);
    return (await res.json()) as Record<string, JsonValue>;
  }

  private async postSigned(
    path: string,
    payload: Record<string, JsonValue>,
  ): Promise<Record<string, JsonValue>> {
    const res = await fetch(this.base + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(signRequest(payload, this.identity)),
    });
    const body = (await res.json().catch(() => ({}))) as Record<string, JsonValue>;
    if (!res.ok) {
      const code = (body.code as string) ?? undefined;
      const msg = (body.error as string) ?? (body.message as string) ?? `POST ${path} failed`;
      throw new NaError(msg, res.status, code);
    }
    return body;
  }

  /** Fetch the genesis block and verify the Root Sovereign signature. */
  async fetchGenesis(): Promise<GenesisBlock> {
    const raw = await this.get("/genesis");
    if (!verifyAnyModelSignature(raw, raw.root_public_key as string)) {
      throw new Error("Genesis block signature verification failed");
    }
    return raw as unknown as GenesisBlock;
  }

  async fetchPolicy(genesis: GenesisBlock): Promise<PolicyManifest> {
    const raw = await this.get("/policy");
    const naKey = genesis.network_authority.public_key;
    if (!verifyAnyModelSignature(raw, naKey)) {
      throw new Error("Policy manifest signature verification failed");
    }
    return raw as unknown as PolicyManifest;
  }

  async fetchCrl(genesis: GenesisBlock): Promise<Record<string, JsonValue>> {
    const raw = await this.get("/crl");
    const naKey = genesis.network_authority.public_key;
    if (!verifyAnyModelSignature(raw, naKey)) {
      throw new Error("CRL signature verification failed");
    }
    return raw;
  }

  async listNodes(): Promise<Record<string, JsonValue>> {
    return this.get("/nodes");
  }

  /** Verify a join certificate against the genesis NA key (network + validity + signature). */
  verifyCertificate(certRaw: Record<string, JsonValue>, genesis: GenesisBlock): JoinCertificate {
    const cert = certRaw as unknown as JoinCertificate;
    if (cert.network_name !== genesis.network_name) {
      throw new Error("Certificate network name mismatch");
    }
    if (!certIsValid(cert)) {
      throw new Error("Certificate is expired or not yet valid");
    }
    if (!verifyAnyModelSignature(certRaw, genesis.network_authority.public_key)) {
      throw new Error("Join certificate signature verification failed");
    }
    return cert;
  }

  /** Request a join certificate using a single-use invite token. */
  async join(
    genesis: GenesisBlock,
    opts: { inviteToken: string; roles: string[]; validityHours?: number },
  ): Promise<JoinCertificate> {
    const raw = await this.postSigned("/join", {
      node_public_key: this.identity.publicKeyB64,
      roles: opts.roles,
      validity_hours: opts.validityHours ?? 168,
      invite_token: opts.inviteToken,
    });
    return this.verifyCertificate(raw, genesis);
  }

  async heartbeat(cert: JoinCertificate, status = "healthy"): Promise<boolean> {
    const body = await this.postSigned("/heartbeat", {
      cert_id: cert.cert_id,
      node_public_key: this.identity.publicKeyB64,
      status,
    });
    return body.ack === true;
  }

  async renew(
    genesis: GenesisBlock,
    cert: JoinCertificate,
    validityHours = 168,
  ): Promise<JoinCertificate> {
    const raw = await this.postSigned("/renew", {
      cert_id: cert.cert_id,
      node_public_key: this.identity.publicKeyB64,
      roles: cert.roles,
      validity_hours: validityHours,
    });
    return this.verifyCertificate(raw, genesis);
  }
}
