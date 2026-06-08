# Genesis Mesh — TypeScript node + webapp control

Run a **full Genesis Mesh peer node in TypeScript (Node.js)** and drive it from a
**browser webapp**. The node is a faithful port of the Python node's two wire
protocols, so it interoperates with the live network:

1. **NA control plane** — HTTP + JSON with Ed25519-signed request bodies
   (`join`, `heartbeat`, `renew`, plus `genesis` / `policy` / `crl` / `nodes`).
2. **Peer transport** — `Noise_XX_25519_AESGCM_SHA256` over WebSocket, with the
   X25519 static key derived from the node's Ed25519 identity, exactly as the
   Python node does.

## Why the node runs in Node.js, not the browser

A mesh peer must **listen for inbound** Noise sessions (the Python runtime does
`websockets.serve(...)`). Browsers cannot accept inbound socket connections, so a
browser can never be a full peer/router. The architecture is therefore:

```
┌─────────────────────────┐      HTTP + WS        ┌──────────────────────────┐   Noise XX over WS   ┌───────────┐
│  Browser webapp (UI)     │  ──/api/* + /events──▶│  Node.js peer node (TS)  │ ◀───────────────────▶ │ mesh peers │
│  webapp/index.html       │ ◀───────────────────  │  src/* + control server  │                       └───────────┘
└─────────────────────────┘                        │           │ HTTP + Ed25519
                                                    │           ▼
                                                    │   Network Authority (enroll / heartbeat / renew)
                                                    └──────────────────────────┘
```

The browser is the **control surface**; the Node.js process is the **node**.

## Quick start

```bash
cd clients/typescript-node
npm install

# 1) Start the node + local control API (verifies the live genesis on boot).
#    Get an invite token from an operator (CLI: `genesis-mesh admin invite --role client`).
GM_INVITE="<invite-token>" GM_ROLES="role:client" npm run daemon
#    -> control API on http://127.0.0.1:9100, peer listener on an ephemeral port

# 2) In another terminal, serve the webapp and open it.
npm run webapp        # http://127.0.0.1:5173
```

Open `http://127.0.0.1:5173`. If your control port isn't 9100, use
`http://127.0.0.1:5173/?api=http://127.0.0.1:<controlPort>`.

You can also join from the webapp instead of `GM_INVITE`: paste the token, pick
roles, click **Join network**, then **Start listener** and **Connect** to a peer.

### Environment variables (daemon)

| Var | Default | Meaning |
|-----|---------|---------|
| `GM_NA` | `https://na.genesismesh.connectorzzz.com` | Network Authority endpoint |
| `GM_IDENTITY` | `./gm-identity.json` | Ed25519 identity file (auto-created, **keep secret**) |
| `GM_LISTEN_PORT` | `0` | Peer listen port. Set a fixed, reachable port if peers should dial you |
| `GM_CONTROL_PORT` | `9100` | Control API port (bound to `127.0.0.1`) |
| `GM_INVITE` | — | Optional invite token to auto-join on startup |
| `GM_ROLES` | `role:client` | Comma-separated roles for auto-join |

## Control API

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| GET | `/api/status` | — | node + peer status |
| GET | `/api/nodes` | — | NA's enrolled-node view |
| POST | `/api/join` | `{inviteToken, roles?, validityHours?}` | enroll, get a verified certificate |
| POST | `/api/listen` | `{port?}` | start accepting inbound peers |
| POST | `/api/connect` | `{endpoint}` | dial a peer (`host:port` or `ws[s]://`) |
| POST | `/api/send` | `{peerId, text}` | send a DATA message to a peer |
| WS | `/events` | — | live stream: `status`, `peer:connected/disconnected`, `data`, `warn` |

CORS is permissive by default for local development. **In production, bind the
control API to `127.0.0.1` and put auth in front of it** — anyone who can reach
it can act as your node.

## Use the node as a library

```ts
import { Identity, MeshNode } from "@genesis-mesh/node";

const node = new MeshNode({
  identity: Identity.loadOrCreate("./gm-identity.json"),
  naEndpoint: "https://na.genesismesh.connectorzzz.com",
});
await node.loadGenesis();                       // fetch + verify root signature
await node.join("<invite>", ["role:client"]);   // signed enroll, verified cert
const port = await node.listen(7000);           // accept inbound peers
node.on("data", (d) => console.log("from", d.from, ":", d.text));
const conn = await node.connect("peer-host:7000");
node.sendData(conn.peerId, "hello over Noise XX");
```

## What's verified

Run the test scripts:

```bash
npm run test:canonical     # canonical JSON is byte-identical to Python; verifies the LIVE genesis root signature
npx tsx scripts/test-noise.ts   # Noise XX handshake + transport + Ed25519->X25519 binding (loopback)
npx tsx scripts/test-e2e.ts     # two nodes: Noise XX + peer-cert validation + DATA both directions
```

These confirm the security-critical interop points:
- **Canonical JSON** matches Python's `json.dumps(sort_keys=True, separators=(',',':'))`
  with `ensure_ascii` — so Ed25519 signatures verify across both stacks
  (proven against the live NA genesis block: 447 bytes, signature valid).
- **X25519 static key** derived via `@noble/curves` `edwardsToMontgomery*` equals
  what a peer derives from your certificate's Ed25519 key — the binding
  `genesis_mesh/node/peer_identity.py` enforces.
- **Noise XX** completes and transport frames round-trip, with the responder's
  cert in message 2 and the initiator's cert in message 3, matching
  `genesis_mesh/transport/noise_handshake.py`.

## Interop caveats / roadmap

This is a **direct-neighbour peer + enrollment** implementation. Not yet ported
from the Python runtime:

- **Multi-hop routing** (`routing/`): route announcements, forwarding, TTL decrement.
  This node delivers DATA to directly-connected peers only.
- **CRL gossip** (`gossip/`): the node verifies the NA's CRL on demand but does not
  gossip revocations to peers. (Peer certs are still validated and bound on connect.)
- **Peer-discovery announcements**: the signed `PeerInfo` gossip uses a float
  timestamp; Python's float `repr` and JS number formatting can differ, so
  signing/verifying those announcements is intentionally out of scope for now.
  All core flows (NA requests, cert verification) sign only strings/ints and are
  byte-exact.
- **Live Noise interop** is implemented to spec and self-tested in-process; the
  final gate is a handshake against a live Python peer. Point `connect()` at a
  running `genesis-mesh` node's peer port to validate.

## Files

```
src/
  identity.ts      Ed25519 keypair + X25519 (Noise static) derivation
  canonical.ts     Python-compatible canonical JSON
  crypto.ts        sign/verify, signed-request builder, model-signature verify
  models.ts        wire types (genesis, certificate, policy, MeshMessage)
  naClient.ts      Network Authority REST client
  noise.ts         Noise_XX_25519_AESGCM_SHA256 handshake + transport ciphers
  transport.ts     WebSocket + Noise session (initiator / responder)
  connection.ts    MeshMessage framing + ping/pong
  node.ts          MeshNode: join, listen, connect, send, peer-cert binding
  controlServer.ts local HTTP + WS control API for the webapp
  daemon.ts        CLI entry point (node + control API)
webapp/
  index.html       zero-build control UI (vanilla JS)
scripts/
  test-canonical.ts / test-noise.ts / test-e2e.ts / serve-webapp.mjs
```
