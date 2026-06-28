# Example: Trust Atlas

The Trust Atlas is a read-only explorer over the recognition graph. It shows
sovereigns, trust relationships, treaty scope, and — when supplied —
TrustEvidence records overlaid on the edges they describe. It derives
everything from signed protocol data and exposes no write paths.

Two consumption modes:

- **Live operator console** (`/atlas`) — rendered from the NA's live
  recognition graph on every request.
- **Static snapshot** (`atlas build`) — a self-contained `atlas.html` +
  `atlas.json` you can publish anywhere, with optional TrustEvidence overlay.

```{mermaid}
flowchart LR
    graph["/recognition-graph"]
    atlas_json["/atlas.json"]
    atlas_page["/atlas"]
    build["atlas build"]
    static["atlas.html / atlas.json"]
    evidence["TrustEvidence files"]
    operator["Operator"]
    external["External viewer"]

    graph --> atlas_json
    graph --> atlas_page
    graph --> build
    evidence --> build
    build --> static
    operator --> atlas_page
    external --> static
```

```{image} assets/images/genesis-mesh-atlas.gif
:alt: Trust atlas demo
:class: screenshot
```

## What This Proves

- Any party with the recognition graph export and a set of TrustEvidence files
  can produce a verifiable, self-contained Atlas snapshot without running an NA.
- Active, expiring-soon, and revoked edges are distinct and labelled.
- Treaty scope (allowed roles) is visible per relationship.
- Verified TrustEvidence records are displayed against the edges they describe;
  unverifiable records are shown as unverified, never silently accepted.
- The `graph_digest` in `atlas.json` and `atlas.html` ties the snapshot to the
  exact graph state it was built from.

## Prerequisites

A running Network Authority with at least one recognition treaty issued. For
the static build, a recognition graph JSON export (from `/recognition-graph`).
For the evidence overlay, TrustEvidence files produced by
`genesis-mesh trust evidence` (see {doc}`trust-evidence`).

## Part 1: Live operator console

The `/atlas` page is available on any running NA at `http://<na>/atlas`. It
requires no extra configuration and refreshes from the live graph on each
request. The top navigation bar links to it directly next to Connectome.

The companion `/atlas.json` endpoint returns a machine-readable summary:

```bash
curl -s https://na.example.org/atlas.json | python -m json.tool
```

Expected shape:

```text
{
  "sovereigns": [{"sovereign_id": "sovereign-a"}, {"sovereign_id": "sovereign-b"}],
  "recognition_edges": [ ... ],
  "active_treaty_count": 2,
  "revoked_trust_material_count": 0,
  "graph_digest": "<sha256-hex>"
}
```

The `graph_digest` is the SHA-256 hex of the canonical graph export. It is
deterministic: the same graph state always produces the same digest.

## Part 2: Static snapshot (`atlas build`)

### 1. Export the recognition graph

```bash
curl -s https://na-a.example.org/recognition-graph > fleet-graph.json
```

### 2. Build the static Atlas

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/
```

This writes:
- `atlas-snapshot/atlas.json` — machine-readable snapshot with graph digest
- `atlas-snapshot/atlas.html` — self-contained HTML page (no server, no CSS
  dependencies, viewable offline)

### 3. Open the static Atlas

```bash
# Open in a browser
start atlas-snapshot/atlas.html       # Windows
open atlas-snapshot/atlas.html        # macOS
xdg-open atlas-snapshot/atlas.html   # Linux
```

Or publish to GitHub Pages, object storage, or any static host.

## Part 3: TrustEvidence overlay

The Atlas can overlay verified TrustEvidence records produced by
`genesis-mesh trust evidence`. Each record is signature-checked against the
supplied public key(s) and its `graph_digest` is compared against the
snapshot's own graph digest.

### 1. Issue TrustEvidence records (Sovereign A)

```bash
genesis-mesh trust evidence \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer \
  --issuer-sovereign sovereign-a \
  --signing-key .genesis-mesh/keys/na.key \
  --key-id na-2026-q1 \
  --output evidence/a-b.json
```

Repeat for each relationship you want to overlay.

### 2. Build the Atlas with evidence overlay

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/ \
  --evidence ./evidence/ \
  --public-key <sovereign-a-public-key-base64>
```

Evidence in `./evidence/` is read, verified, and overlaid. The summary output:

```
Graph: 2 sovereign(s), 2 edge(s) — digest a3f1b2c8d9e0...
  atlas.json: atlas-snapshot/atlas.json
  atlas.html: atlas-snapshot/atlas.html
  evidence: 1/1 verified, 0 unreadable
```

Exit code 0 when all evidence verifies. Exit code 1 if any record fails
verification or cannot be parsed — the Atlas is still written but the
caller knows something is wrong.

### 3. Failure cases

**Wrong public key supplied** — evidence appears as `unverified` in the HTML;
exit code 1.

**Evidence file is not a TrustEvidence JSON** — skipped and counted in
`unverifiable_count`; exit code 1.

**Graph has changed since evidence was issued** — evidence digest does not
match current graph digest; marked `unverified`.

## What Atlas is not

- Atlas is not a trust authority. It describes the graph; it does not rate or
  rank participants.
- Atlas cannot mutate treaties, feeds, or decisions. All surfaces are read-only.
- Atlas does not replace the Connectome. The Connectome is the detailed operator
  view of edges, revocation blast radius, and trust-path explanations. Atlas is
  the broader relational view — who can do what, under what scope — with evidence
  overlay.

## See also

- {doc}`connectome` — detailed operator view of recognition edges and revocation
- {doc}`trust-evidence` — produce and verify TrustEvidence records for overlay
- {doc}`recognition-treaties` — issue the recognition treaties that Atlas displays
