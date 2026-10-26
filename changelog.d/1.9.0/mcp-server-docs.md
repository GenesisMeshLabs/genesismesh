### Documentation

- **The MCP server.** A concept page describes `genesismesh-mcp`, the Model
  Context Protocol server that gives AI assistants and agents the Network
  Authority's operations, offline verification and signing: its tools,
  profiles, transports (stdio, and Streamable HTTP with OAuth approval codes
  and scoped agent tokens), how nodes that hold their own keys enroll, and the
  live instance at mcp.genesismesh.org. The README lists it among the
  components.
- **The mesh.genesismesh.org stack.** `infrastructure/mesh-demo/` matches the
  deployed stack: the `mcp` service and its `mcp-ops` key, the Caddy sites
  `mcp.genesismesh.org` and `na.mesh.genesismesh.org` (the NA's node routes
  only), and `NA_PROXY_HOPS=1`. The deployment page says the same.
