# MCP Server

[GenesisMeshLabs/genesismesh-mcp](https://github.com/GenesisMeshLabs/genesismesh-mcp)
is a [Model Context Protocol](https://modelcontextprotocol.io/) server for
Genesis Mesh. It gives an AI assistant or agent the Network Authority's
operations, offline verification and signing as typed tools, so it can inspect,
verify and administer a sovereign, and, when its grant allows, run one.

The server is an adapter, not a second implementation. It calls this
package's own code for canonical forms, signatures and trust decisions, and
pins one Genesis Mesh release exactly: it refuses to start against another.

## Status

`0.1.0.dev0`, unreleased and outside the coordinated release train. It is
pinned to one exact Genesis Mesh release (its `pyproject.toml`). CI runs it on
Windows and Linux with Python 3.12 and 3.14, and requires full line and branch
coverage of its adapters.

## What it covers

- **284 tools**:
  - one named adapter for each of the 116 public HTTP operations of the
    Network Authority, plus signed node and attestation rosters;
  - 140 offline tools (agreements, delegation, recognition, tokens,
    freshness, decisions, execution evidence, audit packs, disclosure,
    consensus, data governance, grants, key history);
  - workflows for federation, fleets, audit packs and archives, treaty
    renewal and node enrollment.
- **Resources**: model schemas, the CLI reference, the server's coverage and
  compatibility, and guides such as `genesis-mesh://guide/enroll-node`.
- **Prompts**: `inspect_trust`, `verify_evidence`, `governed_operation` and
  `enroll_node`.

## Profiles and keys

The operator configures destinations, keys and storage in a local file. A
model never supplies a key, a key path or an authority URL. Tools are grouped
into profiles, enabled in the configuration:

| Profile | Allows |
| --- | --- |
| `read`, `verify` | Public reads, verification endpoints and offline checks |
| `operator`, `write` | Operator-signed authority operations and mutations; the operator key's tier still applies |
| `node` | Node identity operations |
| `sign` | Offline signing, each signer allowed for named tools only |
| `local`, `provision`, `execute`, `maintain` | Workspace artifacts, fleet provisioning, configured peer sends and guard actions, canary and proof maintenance |

A policy ALLOW returned by a tool is an assessment, not proof that an external
action ran.

## Transports

- **stdio** (`genesismesh-mcp`): for a host on the same machine, such as
  Claude Desktop or Claude Code. The user running it is the security boundary.
- **Streamable HTTP with OAuth** (`genesismesh-mcp-http`): for hosts that
  connect by URL, such as claude.ai connectors and agent runtimes.
  - The server is its own OAuth 2.1 authorization server. Clients register
    themselves and use PKCE.
  - An operator-issued, single-use approval code authorizes each client and
    caps its scopes. `genesismesh-mcp-admin issue-code` issues one.
  - Scopes `gm:<profile>`, or `gm:admin` for all, narrow the configured
    profiles per request.
  - Autonomous agents use scoped tokens from
    `genesismesh-mcp-admin create-agent`.
  - Tokens are short-lived, stored only as digests, and revocable per
    client.

Every client acts with the same configured keys, limited by its scopes: it is
one operator's server, not a multi-tenant service. Give `gm:admin`,
`gm:operator` or `gm:write` only to clients you would give the operator key to.

## Nodes and agents that hold their own keys

The server issues invites; it never holds an outside node's private key. The
node joins and registers itself:

1. Issue an invite with `na_admin_create_invite`, bound to the node's public
   key. The result's `token_id` is the single-use invite token itself.
2. On the node's machine, join at the authority's public node URL with that
   token, signing with the node's own key.
3. On the node's machine, register the node's signed descriptor at
   `/agents` on the same URL.

The server's instructions, the invite result and the
`genesis-mesh://guide/enroll-node` resource say this to every client, with
the URL the operator configures as `node_enrollment_url`.

## The live instance

`https://mcp.genesismesh.org/mcp` serves the Network Authority behind
[mesh.genesismesh.org](https://mesh.genesismesh.org), with an operator key of
its own (`mcp-ops`). Access needs an approval code from the maintainer.
Nodes and agents join that authority at `https://na.mesh.genesismesh.org`, which
serves only its node routes. The deployment is described in
`infrastructure/mesh-demo/`.
