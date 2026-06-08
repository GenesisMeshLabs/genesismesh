/**
 * Local control API that a browser webapp drives. The browser CANNOT be a mesh
 * peer (it can't listen for inbound Noise sessions), so it talks to THIS process
 * over a small HTTP + WebSocket API, and this process is the real node.
 *
 *   GET  /api/status                  current node + peer status
 *   POST /api/join     {inviteToken, roles?, validityHours?}
 *   POST /api/listen   {port?}        start accepting inbound peers
 *   POST /api/connect  {endpoint}     dial a peer (host:port or ws[s]://)
 *   POST /api/send     {peerId, text} send a DATA message to a peer
 *   GET  /api/nodes                   NA's enrolled-node view
 *   WS   /events                      live stream: status, peer:*, data, warn
 *
 * CORS is permissive by default so a webapp on another origin (e.g. a Vite dev
 * server) can call it. Bind to 127.0.0.1 in production and front with auth.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import type { MeshNode } from "./node.js";

export interface ControlServerOptions {
  host?: string;
  port?: number;
  /** Allowed CORS origin. Default "*". */
  corsOrigin?: string;
}

export class ControlServer {
  private http = createServer((req, res) => void this.handle(req, res));
  private wss = new WebSocketServer({ noServer: true });
  private clients = new Set<WebSocket>();

  constructor(
    private readonly node: MeshNode,
    private readonly opts: ControlServerOptions = {},
  ) {
    this.http.on("upgrade", (req, socket, head) => {
      if ((req.url ?? "").split("?")[0] !== "/events") {
        socket.destroy();
        return;
      }
      this.wss.handleUpgrade(req, socket, head, (ws) => {
        this.clients.add(ws);
        ws.on("close", () => this.clients.delete(ws));
        ws.send(JSON.stringify({ type: "status", data: this.node.status() }));
      });
    });

    // Fan out node events to all connected webapp clients.
    const forward = (type: string) => (data: unknown) => this.broadcast(type, data);
    node.on("status", forward("status"));
    node.on("peer:connected", forward("peer:connected"));
    node.on("peer:disconnected", forward("peer:disconnected"));
    node.on("warn", (msg: string) => this.broadcast("warn", { message: msg }));
    node.on("data", (evt: { from: string; text: string | null }) =>
      this.broadcast("data", { from: evt.from, text: evt.text }),
    );
  }

  private broadcast(type: string, data: unknown): void {
    const payload = JSON.stringify({ type, data });
    for (const ws of this.clients) {
      if (ws.readyState === ws.OPEN) ws.send(payload);
    }
  }

  async start(): Promise<number> {
    const port = this.opts.port ?? 9100;
    const host = this.opts.host ?? "127.0.0.1";
    await new Promise<void>((resolve) => this.http.listen(port, host, resolve));
    const addr = this.http.address();
    return typeof addr === "object" && addr ? addr.port : port;
  }

  async stop(): Promise<void> {
    for (const ws of this.clients) ws.close();
    await new Promise<void>((r) => this.http.close(() => r()));
  }

  private cors(res: ServerResponse): void {
    res.setHeader("Access-Control-Allow-Origin", this.opts.corsOrigin ?? "*");
    res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "content-type");
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    this.cors(res);
    if (req.method === "OPTIONS") {
      res.writeHead(204).end();
      return;
    }
    const url = (req.url ?? "/").split("?")[0];
    try {
      if (req.method === "GET" && url === "/api/status") return this.json(res, 200, this.node.status());
      if (req.method === "GET" && url === "/api/nodes") return this.json(res, 200, await this.node.na.listNodes());

      if (req.method === "POST" && url === "/api/join") {
        const body = await readJson(req);
        const cert = await this.node.join(
          String(body.inviteToken),
          Array.isArray(body.roles) ? body.roles : ["role:client"],
          body.validityHours,
        );
        return this.json(res, 200, { ok: true, certId: cert.cert_id, roles: cert.roles });
      }
      if (req.method === "POST" && url === "/api/listen") {
        const body = await readJson(req);
        const port = await this.node.listen(body.port);
        return this.json(res, 200, { ok: true, port });
      }
      if (req.method === "POST" && url === "/api/connect") {
        const body = await readJson(req);
        const conn = await this.node.connect(String(body.endpoint));
        return this.json(res, 200, { ok: true, peerId: conn.peerId });
      }
      if (req.method === "POST" && url === "/api/send") {
        const body = await readJson(req);
        this.node.sendData(String(body.peerId), String(body.text ?? ""));
        return this.json(res, 200, { ok: true });
      }
      this.json(res, 404, { error: "not found" });
    } catch (err) {
      this.json(res, 400, { error: (err as Error).message });
    }
  }

  private json(res: ServerResponse, status: number, data: unknown): void {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(data));
  }
}

function readJson(req: IncomingMessage): Promise<Record<string, any>> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf-8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(new Error("invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}
