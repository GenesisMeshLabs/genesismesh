/**
 * WebSocket transport with a Noise XX encrypted session, matching
 * genesis_mesh/transport/websocket_transport.py. Each Noise message and each
 * post-handshake transport frame is one WebSocket *binary* message.
 */
import WebSocket from "ws";
import { HandshakeState, type CipherState } from "./noise.js";

const enc = new TextEncoder();
const dec = new TextDecoder();

function toBytes(data: WebSocket.RawData): Uint8Array {
  if (Buffer.isBuffer(data)) return new Uint8Array(data);
  if (Array.isArray(data)) return new Uint8Array(Buffer.concat(data));
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  return new Uint8Array(Buffer.from(data as Buffer));
}

/** Wraps a ws socket so discrete binary frames can be awaited in order. */
class FramedSocket {
  private queue: Uint8Array[] = [];
  private waiters: Array<(v: Uint8Array | null) => void> = [];
  private closed = false;

  constructor(readonly ws: WebSocket) {
    ws.on("message", (data) => {
      const bytes = toBytes(data);
      const w = this.waiters.shift();
      if (w) w(bytes);
      else this.queue.push(bytes);
    });
    const onEnd = () => {
      this.closed = true;
      while (this.waiters.length) this.waiters.shift()!(null);
    };
    ws.on("close", onEnd);
    ws.on("error", onEnd);
  }

  send(bytes: Uint8Array): void {
    this.ws.send(bytes, { binary: true });
  }

  receive(): Promise<Uint8Array | null> {
    const queued = this.queue.shift();
    if (queued) return Promise.resolve(queued);
    if (this.closed) return Promise.resolve(null);
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  close(): void {
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }
}

export interface NoiseConnectResult {
  transport: NoiseTransport;
  remoteCertB64: string;
  remoteStaticPub: Uint8Array;
}

export class NoiseTransport {
  private closed = false;
  private constructor(
    private readonly framed: FramedSocket,
    private readonly sendCipher: CipherState,
    private readonly recvCipher: CipherState,
  ) {}

  /** Outbound: connect to a peer WebSocket and run Noise XX as initiator. */
  static async connectInitiator(
    url: string,
    staticPriv: Uint8Array,
    localCertB64: string,
    timeoutMs = 10000,
  ): Promise<NoiseConnectResult> {
    const ws = new WebSocket(url);
    await waitOpen(ws, timeoutMs);
    const framed = new FramedSocket(ws);
    const hs = HandshakeState.create(true, staticPriv);

    framed.send(hs.writeMessage1());
    const m2 = await framed.receive();
    if (!m2) throw new Error("Noise: connection closed during handshake (msg2)");
    const remoteCert = hs.readMessage2(m2);
    const { msg: m3, result } = hs.writeMessage3(enc.encode(localCertB64));
    framed.send(m3);

    return {
      transport: new NoiseTransport(framed, result.send, result.receive),
      remoteCertB64: dec.decode(remoteCert),
      remoteStaticPub: result.remoteStaticPub,
    };
  }

  /** Inbound: run Noise XX as responder over an accepted ws socket. */
  static async acceptResponder(
    ws: WebSocket,
    staticPriv: Uint8Array,
    localCertB64: string,
  ): Promise<NoiseConnectResult> {
    const framed = new FramedSocket(ws);
    const hs = HandshakeState.create(false, staticPriv);

    const m1 = await framed.receive();
    if (!m1) throw new Error("Noise: connection closed during handshake (msg1)");
    hs.readMessage1(m1);
    framed.send(hs.writeMessage2(enc.encode(localCertB64)));
    const m3 = await framed.receive();
    if (!m3) throw new Error("Noise: connection closed during handshake (msg3)");
    const result = hs.readMessage3(m3);

    return {
      transport: new NoiseTransport(framed, result.send, result.receive),
      remoteCertB64: dec.decode(result.remotePayload),
      remoteStaticPub: result.remoteStaticPub,
    };
  }

  send(plaintext: Uint8Array): void {
    if (this.closed) throw new Error("transport closed");
    this.framed.send(this.sendCipher.encryptWithAd(new Uint8Array(0), plaintext));
  }

  async receive(): Promise<Uint8Array | null> {
    if (this.closed) return null;
    const frame = await this.framed.receive();
    if (frame === null) return null;
    return this.recvCipher.decryptWithAd(new Uint8Array(0), frame);
  }

  close(): void {
    this.closed = true;
    this.framed.close();
  }
}

function waitOpen(ws: WebSocket, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      ws.terminate();
      reject(new Error("WebSocket open timed out"));
    }, timeoutMs);
    ws.once("open", () => {
      clearTimeout(timer);
      resolve();
    });
    ws.once("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}
