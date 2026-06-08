/**
 * MeshNode: a full Genesis Mesh peer running in Node.js.
 *
 * Responsibilities (ported from genesis_mesh/node + runtime):
 *  - enroll with the NA (join), keep the certificate alive (heartbeat/renew)
 *  - LISTEN for inbound peers (Noise XX responder) — the reason a node must run
 *    in Node.js, not a browser
 *  - CONNECT outbound to peers (Noise XX initiator)
 *  - validate every peer certificate AND bind it to the Noise static key, the
 *    same check genesis_mesh/node/peer_identity.py performs
 *  - send/receive DATA messages over established encrypted sessions
 *
 * Scope note: this is direct neighbour messaging + enrollment. Multi-hop route
 * propagation / CRL gossip are not yet ported (see README "Roadmap").
 */
import { EventEmitter } from "node:events";
import { WebSocketServer } from "ws";
import { Identity, noiseStaticPublicFromEd25519B64 } from "./identity.js";
import { constantTimeEqual } from "./noise.js";
import { NoiseTransport } from "./transport.js";
import { Connection } from "./connection.js";
import { NaClient } from "./naClient.js";
import {
  type GenesisBlock,
  type JoinCertificate,
  type MeshMessage,
  MessageType,
  makeMessage,
  certIsValid,
} from "./models.js";
import { b64encode } from "./identity.js";

const dec = new TextDecoder();

export interface MeshNodeOptions {
  identity: Identity;
  naEndpoint: string;
  listenHost?: string;
  listenPort?: number;
}

export class MeshNode extends EventEmitter {
  readonly identity: Identity;
  readonly na: NaClient;
  genesis?: GenesisBlock;
  cert?: JoinCertificate;
  private certB64 = "";
  private server?: WebSocketServer;
  private heartbeatTimer?: NodeJS.Timeout;
  readonly connections = new Map<string, Connection>(); // peerId -> Connection

  constructor(private readonly opts: MeshNodeOptions) {
    super();
    this.identity = opts.identity;
    this.na = new NaClient(opts.naEndpoint, opts.identity);
  }

  get nodeId(): string {
    return this.identity.nodeId;
  }

  /** Fetch + verify genesis (root signature). Required before joining. */
  async loadGenesis(): Promise<GenesisBlock> {
    this.genesis = await this.na.fetchGenesis();
    return this.genesis;
  }

  /** Enroll: exchange an invite token for a signed, verified join certificate. */
  async join(inviteToken: string, roles: string[], validityHours = 168): Promise<JoinCertificate> {
    if (!this.genesis) await this.loadGenesis();
    this.cert = await this.na.join(this.genesis!, { inviteToken, roles, validityHours });
    this.certB64 = encodeCertB64(this.cert);
    this.emit("status", this.status());
    return this.cert;
  }

  /** Load a previously issued certificate (e.g. persisted) and adopt it. */
  adoptCertificate(cert: JoinCertificate): void {
    this.cert = cert;
    this.certB64 = encodeCertB64(cert);
  }

  /** Start listening for inbound peer connections (Noise XX responder). */
  async listen(port = this.opts.listenPort ?? 0, host = this.opts.listenHost ?? "0.0.0.0"): Promise<number> {
    if (!this.cert) throw new Error("Cannot listen without a join certificate");
    this.server = new WebSocketServer({ host, port });
    this.server.on("connection", (ws) => void this.acceptPeer(ws));
    await new Promise<void>((resolve, reject) => {
      this.server!.once("listening", resolve);
      this.server!.once("error", reject);
    });
    const addr = this.server.address();
    const boundPort = typeof addr === "object" && addr ? addr.port : port;
    this.startHeartbeat();
    this.emit("status", this.status());
    return boundPort;
  }

  private async acceptPeer(ws: import("ws").WebSocket): Promise<void> {
    try {
      const { transport, remoteCertB64, remoteStaticPub } = await NoiseTransport.acceptResponder(
        ws,
        this.identity.noiseStaticPrivate(),
        this.certB64,
      );
      const cert = this.validatePeerCert(remoteCertB64, remoteStaticPub);
      this.registerPeer(cert, transport);
    } catch (err) {
      this.emit("warn", `rejected inbound peer: ${(err as Error).message}`);
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }

  /** Connect outbound to a peer endpoint ("host:port" or ws(s):// URL). */
  async connect(endpoint: string): Promise<Connection> {
    if (!this.cert) throw new Error("Cannot connect without a join certificate");
    const url = endpointToUrl(endpoint);
    const { transport, remoteCertB64, remoteStaticPub } = await NoiseTransport.connectInitiator(
      url,
      this.identity.noiseStaticPrivate(),
      this.certB64,
    );
    const cert = this.validatePeerCert(remoteCertB64, remoteStaticPub);
    return this.registerPeer(cert, transport, endpoint);
  }

  /**
   * Validate a peer certificate and bind it to the Noise static key — the exact
   * checks RuntimePeerIdentity.validate_peer_cert performs.
   */
  private validatePeerCert(remoteCertB64: string, remoteStaticPub: Uint8Array): JoinCertificate {
    let certRaw: Record<string, unknown>;
    try {
      certRaw = JSON.parse(dec.decode(Buffer.from(remoteCertB64, "base64")));
    } catch (e) {
      throw new Error(`invalid peer certificate payload: ${(e as Error).message}`);
    }
    const cert = certRaw as unknown as JoinCertificate;
    if (cert.network_name !== this.genesis!.network_name) throw new Error("peer certificate network mismatch");
    if (!certIsValid(cert)) throw new Error("peer certificate expired or not yet valid");
    this.na.verifyCertificate(certRaw as never, this.genesis!); // NA signature + network + validity
    const expected = noiseStaticPublicFromEd25519B64(cert.node_public_key);
    if (!constantTimeEqual(expected, remoteStaticPub)) {
      throw new Error("peer certificate key does not match Noise static key");
    }
    return cert;
  }

  private registerPeer(cert: JoinCertificate, transport: NoiseTransport, endpoint = ""): Connection {
    const peerId = cert.node_public_key;
    const existing = this.connections.get(peerId);
    if (existing) existing.close();

    const conn = new Connection(peerId, transport, this.nodeId, endpoint);
    conn.on("message", (msg: MeshMessage) => this.onPeerMessage(msg, conn));
    conn.on("close", () => {
      if (this.connections.get(peerId) === conn) this.connections.delete(peerId);
      this.emit("peer:disconnected", { peerId });
      this.emit("status", this.status());
    });
    this.connections.set(peerId, conn);
    conn.start();
    this.emit("peer:connected", { peerId, roles: cert.roles, certId: cert.cert_id, endpoint });
    this.emit("status", this.status());
    return conn;
  }

  private onPeerMessage(msg: MeshMessage, conn: Connection): void {
    if (msg.message_type === MessageType.DATA) {
      const b64 = msg.payload.data as string | undefined;
      const bytes = b64 ? new Uint8Array(Buffer.from(b64, "base64")) : new Uint8Array(0);
      this.emit("data", { from: msg.sender_id, bytes, text: safeUtf8(bytes), message: msg });
    } else {
      this.emit("message", { message: msg, peerId: conn.peerId });
    }
  }

  /** Send a DATA message to a directly-connected peer. */
  sendData(peerId: string, data: Uint8Array | string): void {
    const conn = this.connections.get(peerId);
    if (!conn) throw new Error(`not connected to peer ${peerId}`);
    const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
    conn.send(
      makeMessage(MessageType.DATA, this.nodeId, {
        recipient_id: peerId,
        payload: { data: b64encode(bytes) },
      }),
    );
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer || !this.cert) return;
    const tick = async () => {
      try {
        if (this.cert) await this.na.heartbeat(this.cert);
      } catch (e) {
        this.emit("warn", `heartbeat failed: ${(e as Error).message}`);
      }
    };
    void tick();
    this.heartbeatTimer = setInterval(() => void tick(), 120_000);
  }

  status() {
    return {
      nodeId: this.nodeId,
      network: this.genesis?.network_name ?? null,
      hasCertificate: !!this.cert,
      certId: this.cert?.cert_id ?? null,
      certExpires: this.cert?.expires_at ?? null,
      roles: this.cert?.roles ?? [],
      listening: !!this.server,
      peers: [...this.connections.values()].map((c) => ({ peerId: c.peerId, endpoint: c.endpoint })),
    };
  }

  async stop(): Promise<void> {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    for (const conn of this.connections.values()) conn.close();
    this.connections.clear();
    if (this.server) await new Promise<void>((r) => this.server!.close(() => r()));
  }
}

function encodeCertB64(cert: JoinCertificate): string {
  return Buffer.from(JSON.stringify(cert), "utf-8").toString("base64");
}
function endpointToUrl(endpoint: string): string {
  if (endpoint.startsWith("ws://") || endpoint.startsWith("wss://")) return endpoint;
  return `ws://${endpoint}`;
}
function safeUtf8(bytes: Uint8Array): string | null {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
