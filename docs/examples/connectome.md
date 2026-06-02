# Example: Connectome Operator View

The Connectome turns recognition graph data into an operator-facing view of
sovereigns, direct-recognition edges, trust paths, and revocation impact. It is
not a new trust source. It is a window over the signed treaties and imported
revocation feeds already stored by the Network Authority.

```{mermaid}
flowchart LR
    graph["/recognition-graph"]
    json["/connectome.json"]
    page["/connectome"]
    path["/connectome/trust-path"]
    operator["Operator"]

    graph --> json
    json --> page
    json --> path
    operator --> page
    operator --> path
```

## What This Proves

- Operators can inspect the recognition network without reading raw treaty
  JSON.
- Active and revoked recognition edges are visible from the same source of
  truth.
- A direct trust-path check explains whether one sovereign currently recognizes
  another.
- Imported sovereign revocation feeds expose their blast radius: which
  accepting sovereigns are affected by a revoked membership attestation.

## Endpoints

### `GET /connectome.json`

Returns a derived Connectome view:

```json
{
  "summary": {
    "sovereign_count": 2,
    "recognition_edge_count": 1,
    "active_edge_count": 1,
    "revoked_edge_count": 0,
    "revoked_trust_material_count": 1,
    "imported_revocation_count": 1
  },
  "recognition_edges": [
    {
      "from": "sovereign-a",
      "to": "sovereign-b",
      "status": "active",
      "treaty_id": "..."
    }
  ],
  "revocation_blast_radius": [
    {
      "type": "membership_attestation",
      "issuer_sovereign_id": "sovereign-b",
      "affected_accepting_sovereigns": ["sovereign-a"],
      "reason": "key_compromise"
    }
  ]
}
```

### `GET /connectome/trust-path`

Explains whether one sovereign currently recognizes another:

```text
GET /connectome/trust-path?from=sovereign-a&to=sovereign-b
```

Response:

```json
{
  "from": "sovereign-a",
  "to": "sovereign-b",
  "trusted": true,
  "reason": "active_treaty_path",
  "hop_count": 1,
  "path": [
    {
      "from": "sovereign-a",
      "to": "sovereign-b",
      "status": "active",
      "treaty_id": "..."
    }
  ]
}
```

If the direct treaty was revoked, the endpoint returns
`trusted: false` with `reason: direct_treaty_revoked`. If no active path exists,
it returns `reason: no_active_treaty_path`.

### `GET /connectome`

Renders a self-contained HTML operator page with summary cards, recognition
edges, revoked trust material, and revocation blast-radius rows. The page links
back to `/recognition-graph` and `/connectome.json` so operators can compare
the derived view with the raw export.

## Run the Demo

```powershell
python docs\examples\assets\scripts\connectome-demo.py
```

The demo creates two in-process Network Authorities:

1. Sovereign B issues a membership attestation.
2. Sovereign A issues an active recognition treaty for Sovereign B.
3. Sovereign B revokes the attestation and publishes a signed revocation feed.
4. Sovereign A imports the feed.
5. The Connectome view reports the active recognition edge and the imported
   revocation's affected accepting sovereigns.

To inspect the operator page in a browser, run the same seeded flow in server
mode:

```powershell
python docs\examples\assets\scripts\connectome-demo.py --serve --port 8765
```

Then open:

```text
http://127.0.0.1:8765/connectome
```

The server exposes the same seeded graph at `/connectome.json` and the direct
trust-path explanation at
`/connectome/trust-path?from=sovereign-a&to=sovereign-b`.

Static walkthrough:

```{image} assets/images/genesis-mesh-connectome.png
:alt: Static Connectome screenshot showing recognition edges and revocation impact
:class: screenshot
```

Animated execution:

```{image} assets/images/genesis-mesh-connectome.gif
:alt: Animated Connectome demo showing graph summary and trust path output
:class: screenshot
```

## Expected Proof

```text
==> Connectome summary
    sovereigns:              2
    recognition edges:       1
    active edges:            1
    imported revocations:    1

==> Direct trust path
    from:    sovereign-a
    to:      sovereign-b
    trusted: True
    reason:  active_treaty_path

==> Revocation blast radius
    revoked attestation: <attestation-id>
    issuer:              sovereign-b
    affected acceptors:  sovereign-a
    reason:              key_compromise
```

## Design Boundary

The Connectome is deliberately read-only. It visualizes and explains trust
state, but the authoritative records remain signed treaties, signed
attestations, imported signed revocation feeds, and the local Network Authority
database.
