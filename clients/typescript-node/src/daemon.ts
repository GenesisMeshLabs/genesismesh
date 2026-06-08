#!/usr/bin/env node
/**
 * Node daemon: starts a Genesis Mesh peer + the local control API for a webapp.
 *
 * Env / flags:
 *   GM_NA            NA endpoint (default https://na.genesismesh.connectorzzz.com)
 *   GM_IDENTITY      identity file path (default ./gm-identity.json, auto-created)
 *   GM_LISTEN_PORT   peer listen port (default 0 = ephemeral; set a fixed,
 *                    reachable port if other peers should dial you)
 *   GM_CONTROL_PORT  control API port (default 9100, bound to 127.0.0.1)
 *   GM_INVITE        optional invite token to auto-join on startup
 *   GM_ROLES         comma-separated roles for auto-join (default role:client)
 *
 * Example:
 *   GM_INVITE=$INVITE GM_ROLES=role:client npm run daemon
 */
import { Identity } from "./identity.js";
import { MeshNode } from "./node.js";
import { ControlServer } from "./controlServer.js";

async function main() {
  const naEndpoint = process.env.GM_NA ?? "https://na.genesismesh.connectorzzz.com";
  const identityPath = process.env.GM_IDENTITY ?? "./gm-identity.json";
  const listenPort = Number(process.env.GM_LISTEN_PORT ?? 0);
  const controlPort = Number(process.env.GM_CONTROL_PORT ?? 9100);

  const identity = Identity.loadOrCreate(identityPath);
  console.log(`[gm] identity ${identity.nodeId}`);
  console.log(`[gm] NA ${naEndpoint}`);

  const node = new MeshNode({ identity, naEndpoint, listenPort });
  node.on("warn", (m) => console.warn("[gm:warn]", m));
  node.on("peer:connected", (p) => console.log("[gm] peer connected", p.peerId.slice(0, 12), p.endpoint));
  node.on("peer:disconnected", (p) => console.log("[gm] peer disconnected", p.peerId.slice(0, 12)));
  node.on("data", (d) => console.log(`[gm] data from ${d.from.slice(0, 12)}: ${d.text ?? "<binary>"}`));

  const genesis = await node.loadGenesis();
  console.log(`[gm] genesis verified: network=${genesis.network_name} ${genesis.network_version}`);

  if (process.env.GM_INVITE) {
    const roles = (process.env.GM_ROLES ?? "role:client").split(",").map((r) => r.trim());
    const cert = await node.join(process.env.GM_INVITE, roles);
    console.log(`[gm] joined: cert ${cert.cert_id} roles=${cert.roles.join(",")}`);
    const port = await node.listen(listenPort);
    console.log(`[gm] listening for peers on :${port}`);
  } else {
    console.log("[gm] no GM_INVITE set — use the webapp/control API to join");
  }

  const control = new ControlServer(node, { port: controlPort });
  const cp = await control.start();
  console.log(`[gm] control API on http://127.0.0.1:${cp}  (webapp -> /api/*, events -> ws://127.0.0.1:${cp}/events)`);

  const shutdown = async () => {
    console.log("\n[gm] shutting down");
    await control.stop();
    await node.stop();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((err) => {
  console.error("[gm] fatal:", err);
  process.exit(1);
});
