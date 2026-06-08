/**
 * A peer connection: MeshMessage framing over a Noise transport, plus ping/pong
 * keepalive. Mirrors genesis_mesh/transport/connection.py — one JSON-encoded
 * MeshMessage per transport frame.
 */
import { EventEmitter } from "node:events";
import { NoiseTransport } from "./transport.js";
import {
  type MeshMessage,
  MessageType,
  makeMessage,
  encodeMessage,
  decodeMessage,
} from "./models.js";

export class Connection extends EventEmitter {
  private running = false;
  constructor(
    /** Remote peer node id == its node_public_key (base64). */
    readonly peerId: string,
    private readonly transport: NoiseTransport,
    private readonly localNodeId: string,
    /** host:port the peer was reached at, if outbound. */
    readonly endpoint = "",
  ) {
    super();
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    void this.receiveLoop();
  }

  private async receiveLoop(): Promise<void> {
    try {
      while (this.running) {
        const data = await this.transport.receive();
        if (data === null) break;
        let msg: MeshMessage;
        try {
          msg = decodeMessage(data);
        } catch {
          continue; // ignore undecodable frames
        }
        await this.handle(msg);
      }
    } finally {
      this.close();
    }
  }

  private async handle(msg: MeshMessage): Promise<void> {
    if (msg.message_type === MessageType.PING) {
      this.send(
        makeMessage(MessageType.PONG, this.localNodeId, {
          recipient_id: msg.sender_id,
          payload: { ping_timestamp: msg.payload.ping_timestamp ?? msg.timestamp },
        }),
      );
      return;
    }
    if (msg.message_type === MessageType.PONG) {
      this.emit("pong", msg);
      return;
    }
    this.emit("message", msg);
  }

  send(msg: MeshMessage): void {
    this.transport.send(encodeMessage(msg));
  }

  ping(): void {
    this.send(
      makeMessage(MessageType.PING, this.localNodeId, {
        recipient_id: this.peerId,
        payload: { timestamp: Date.now() / 1000 },
      }),
    );
  }

  close(): void {
    if (!this.running) return;
    this.running = false;
    this.transport.close();
    this.emit("close", this);
  }
}
