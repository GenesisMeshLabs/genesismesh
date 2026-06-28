# Example: Trust Path Performance and Atlas Pruning

The Genesis Mesh recognition graph grows monotonically: every treaty, revocation,
and recognition event adds an edge or modifies a node. At small scale (tens of
sovereigns), path traversal is fast. At the scale projected for 2026–2027
deployments (hundreds to thousands of sovereigns), two problems emerge:

1. **Path traversal latency**: Computing the shortest trusted path requires
   graph traversal. Stale entries that are never pruned make path computation
   slow and incorrect (expired treaties appear as active edges).

2. **Trust Atlas staleness**: The existing `evaluate_trust_decision()` operates
   over a static graph export without any concept of "how old is this graph?"
   or "which edges have definitively expired?"

v0.46 introduces:
- `TrustPathCache`: a signed, TTL-bound cache of recently computed trust paths.
- `GraphPruningPolicy`: operator-defined rules for edge removal.
- `PrunedAtlasExport`: signed pruned graph snapshot with full audit trail.

---

```{image} assets/images/genesis-mesh-trust-path-performance.gif
:alt: Trust path performance demo
:class: screenshot
```

## Step 1 — Pre-compute a trust path cache

```bash
# pairs.json: [["sovereign-a", "sovereign-b"], ["sovereign-a", "sovereign-c"]]
genesis-mesh trust atlas cache \
    --graph graph.json \
    --pairs pairs.json \
    --operator-sovereign operator-1 \
    --path-ttl-seconds 300 \
    --signing-key keys/operator.key \
    --output cache.json
```

```text
[OK] TrustPathCache 3a7f1b22-...
     Pairs  : 2
     TTL    : 300s
     Output : cache.json
```

---

## Step 2 — Query the cache

```bash
genesis-mesh trust atlas lookup \
    --cache cache.json \
    --from sovereign-a \
    --to sovereign-b
```

```text
[OK] allow — sovereign-a -> sovereign-b (1 hop(s))
     Path: sovereign-a > sovereign-b
```

Cache miss returns exit code 1 — the caller should fall back to a full graph
traversal and then update the cache.

---

## Step 3 — Prune expired and revoked edges

```bash
genesis-mesh trust atlas prune \
    --graph graph.json \
    --operator-sovereign operator-1 \
    --signing-key keys/operator.key \
    --output-graph pruned-graph.json \
    --output-audit prune-audit.json
```

```text
[OK] PrunedAtlasExport 9c4a1f22-...
     Original edges : 47
     Pruned edges   : 44
     Removed edges  : 3
     Graph output   : pruned-graph.json
     Audit output   : prune-audit.json
```

---

## Use in code

```python
from genesis_mesh.trust.atlas import (
    cache_trust_path,
    lookup_trust_path,
    build_trust_path_cache,
    prune_graph,
)
from genesis_mesh.models.atlas import GraphPruningPolicy

# Warm the cache
cache = build_trust_path_cache(
    pairs=[("sovereign-a", "sovereign-b"), ("sovereign-a", "sovereign-c")],
    graph=graph_export,
    operator_sovereign_id="operator-1",
    signing_key=operator_sk,
    path_ttl_seconds=300,
)

# Cache-first lookup (O(1) when warm)
entry = lookup_trust_path(cache, "sovereign-a", "sovereign-b")
if entry is not None:
    print(f"Cache hit: {entry.verdict}, {entry.hop_count} hops")
else:
    # Cache miss: recompute
    entry = cache_trust_path("sovereign-a", "sovereign-b", graph, "op-1", sk)

# Prune stale graph
policy = GraphPruningPolicy(
    operator_sovereign_id="operator-1",
    prune_expired_treaties_after_seconds=86400,
    prune_revoked_certificates=True,
    prune_empty_scopes=True,
    max_graph_age_seconds=3600,
)
pruned_graph, audit_export = prune_graph(graph_export, policy, "operator-1", sk)
```

---

## GraphPruningPolicy rules

| Rule | Default | Trigger |
|------|---------|---------|
| `prune_expired_treaties_after_seconds` | 86400 | Edge `valid_until` > N seconds in the past |
| `prune_revoked_certificates` | True | Edge `status == "revoked"` |
| `prune_empty_scopes` | True | Edge `scope_ids == []` |
| `max_graph_age_seconds` | 3600 | Graph is older than N seconds — refuse to prune |

**Staleness guard**: if the graph's `exported_at` is older than
`max_graph_age_seconds`, `prune_graph()` raises `ValueError` rather than
pruning a graph that may have new active edges not yet reflected.

---

## PruningAuditEntry.removal_reason values

| Value | Cause |
|-------|-------|
| `expired_treaty` | `valid_until` is more than `prune_expired_treaties_after_seconds` in the past |
| `revoked_cert` | `status == "revoked"` |
| `empty_scope` | `scope_ids == []` |

---

## Cache invalidation

A cache entry is invalid (treated as a miss) if:
- Its `valid_until` is in the past (TTL expired)
- Its `graph_digest` differs from the cache's `graph_digest` (stale graph)

Both conditions are checked by `lookup_trust_path()` automatically.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust atlas` reference
- {doc}`sovereign-overlay-discovery` — discovering sovereign endpoints
- {doc}`verifiable-logic-attestation` — attestation of what is at each hop
