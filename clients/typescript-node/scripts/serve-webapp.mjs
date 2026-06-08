// Tiny static file server for the demo webapp (no dependencies).
// Usage: node scripts/serve-webapp.mjs [port]
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..", "webapp");
const port = Number(process.argv[2] ?? 5173);
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };

createServer(async (req, res) => {
  try {
    // Work in URL space (forward slashes) before touching the OS path module.
    let urlPath = decodeURIComponent((req.url ?? "/").split("?")[0]);
    if (urlPath === "/" || urlPath.endsWith("/")) urlPath += "index.html";
    const rel = normalize(urlPath).replace(/^([/\\])+/, ""); // strip leading separators
    const file = join(root, rel);
    if (!file.startsWith(root)) {
      res.writeHead(403).end("forbidden");
      return;
    }
    const data = await readFile(file);
    res.writeHead(200, { "content-type": types[extname(file)] ?? "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404).end("not found");
  }
}).listen(port, () => {
  console.log(`webapp on http://127.0.0.1:${port}  (control API expected at http://127.0.0.1:9100)`);
  console.log(`if your daemon uses another control port: http://127.0.0.1:${port}/?api=http://127.0.0.1:9118`);
});
