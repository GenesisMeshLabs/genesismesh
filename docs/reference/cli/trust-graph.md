# Trust Graph Commands

Commands that decide over a recognition-graph export, sign the result, and
build and cache the Trust Atlas.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Trust Decision Commands

The `genesis-mesh trust` group evaluates trust decisions over a recognition-graph
export and issues signed TrustEvidence records that a second sovereign can verify
offline, without sharing a backend, database, or identity provider.

All commands operate over a graph export: the recognition graph a Network
Authority serves at `GET /recognition-graph`, saved to a file (for example
`curl -s https://na.example.org/recognition-graph > fleet-graph.json`).

### `genesis-mesh trust decide`

*Beta.*

Evaluates a trust decision from one sovereign toward another and prints the
verdict, justifying signals, and trust path.

```bash
genesis-mesh trust decide \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer
```

The verdict is one of `allow`, `warn`, `block`, or `escalate`:

| Verdict | Meaning |
|---|---|
| `allow` | Active treaty path with no risk signals. |
| `warn` | Active path, but one or more treaties are expiring soon. |
| `escalate` | Active path, but a revocation feed targets a sovereign on the path. |
| `block` | No active path, or requested roles are outside treaty scope. |

The exit code mirrors the verdict: `0`=allow, `1`=warn, `2`=escalate, `3`=block.
Use `--format json` for machine-readable output.

### `genesis-mesh trust evidence`

*Beta.*

Evaluates trust and emits a signed TrustEvidence record. The evidence binds
the verdict to the recognition-graph state via a SHA-256 digest so a second
sovereign can independently verify it later.

```bash
genesis-mesh trust evidence \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer \
  --issuer-sovereign sovereign-a \
  --signing-key keys/na.key \
  --key-id na-2026-q1 \
  --output evidence-a-b.json
```

The output file is a signed JSON record containing the verdict, signals,
trust path, graph digest, and issuer Ed25519 signature.

### `genesis-mesh trust verify-evidence`

*Beta.*

Verifies the signature on a TrustEvidence record. Without `--graph`, checks
only the Ed25519 signature. With `--graph`, also re-derives the graph digest
and confirms the evidence was produced over the same graph state.

```bash
# Signature check only
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key>

# Strict: signature + graph-state binding
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key> \
  --graph fleet-graph.json
```

Exits `0` on success, `1` on any verification failure. Use `--format json`
for machine-readable output.

## Atlas Commands

The `genesis-mesh atlas` group builds a read-only trust graph explorer from a
recognition-graph export. It surfaces sovereigns, relationships, treaty scope,
and verified TrustEvidence records without write paths or ranking.

### `genesis-mesh atlas build`

*Beta.*

Reads a recognition-graph JSON export, optionally verifies TrustEvidence
records against it, and writes a self-contained `atlas.json` + `atlas.html` to
the output directory.

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/
```

With TrustEvidence overlay:

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/ \
  --evidence ./evidence/ \
  --public-key <sovereign-a-public-key-base64> \
  --public-key <sovereign-b-public-key-base64>
```

| Option | Description |
|---|---|
| `--graph` | Recognition graph JSON export path (required). |
| `--output` | Directory to write `atlas.json` and `atlas.html` (required). |
| `--evidence` | Directory of TrustEvidence JSON files to overlay (optional). |
| `--public-key` | Issuer public key (base64) for signature verification. Repeatable. |

Exit codes:
- `0` — Build succeeded (all supplied evidence verified or none supplied).
- `1` — One or more evidence files could not be parsed or signature verification failed.

The operator console also exposes a live `/atlas` page and `/atlas.json` endpoint
generated from the NA's live recognition graph.

## Trust Atlas Cache and Pruning Commands

The following commands (v0.46) extend the existing `genesis-mesh atlas`
group with path caching and graph pruning.

### `genesis-mesh atlas cache`

*Beta.*

Pre-compute trust paths for (source, target) pairs and write a signed
`TrustPathCache`.

```bash
genesis-mesh atlas cache \
    --graph graph.json \
    --pairs pairs.json \
    --operator-sovereign operator-1 \
    --path-ttl-seconds 300 \
    --signing-key keys/operator.key \
    --output cache.json
```

### `genesis-mesh atlas lookup`

*Beta.*

Query a `TrustPathCache` for a specific pair. Exits non-zero on cache miss.

```bash
genesis-mesh atlas lookup \
    --cache cache.json \
    --from sovereign-a \
    --to sovereign-b \
    --format json
```

### `genesis-mesh atlas prune`

*Beta.*

Prune expired/revoked/empty-scope edges from a graph and produce a signed
`PrunedAtlasExport` with per-edge audit entries.

```bash
genesis-mesh atlas prune \
    --graph graph.json \
    --policy policy.json \
    --operator-sovereign operator-1 \
    --signing-key keys/operator.key \
    --output-graph pruned.json \
    --output-audit audit.json
```
