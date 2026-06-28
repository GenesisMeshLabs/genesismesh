# v0.46.0 Plan -- Trust Path Performance and Atlas Pruning

## Positioning

The Genesis Mesh recognition graph (Trust Atlas) grows monotonically: every
treaty, revocation, and recognition event adds an edge or modifies a node.  At
small scale (tens of sovereigns), path traversal is fast and the graph fits in
memory.  At the scale projected for 2026-2027 deployments (hundreds to thousands
of sovereigns in a federation), two problems emerge:

1. **Path traversal latency**: Computing the shortest trusted path between two
   sovereigns requires traversing the graph.  If the graph is large and stale
   entries are never pruned, path computation becomes slow and incorrect (expired
   treaties still appear as edges).

2. **Trust Atlas staleness**: The current `evaluate_trust_decision()` operates
   over a static graph export.  It does not have a concept of "how old is this
   graph?" or "which edges have definitively expired and can be removed?"
   Operators must manually trigger graph exports and cannot rely on the Atlas
   remaining accurate between exports.

This plan introduces:
- `TrustPathCache`: a signed, TTL-bound cache of recently computed trust paths.
- `GraphPruningPolicy`: operator-defined rules for when an edge may be safely
  removed from the active graph (expired treaties, revoked certificates, etc.)
- `PrunedAtlasExport`: a signed, pruned graph snapshot with a proof of what
  was removed and why.
- Trust decision performance improvement via cache-first path lookup.

> **Scope constraint**: This plan optimizes path computation and graph management.
> It does not implement a live distributed graph database or real-time push updates.
> Graph exports remain the canonical data source.  The cache accelerates
> repeat computations over the same graph.

v0.46 should prove:

> A `TrustPathCache` entry for a (source, target) pair is valid for its TTL.
> Cache-first lookup on a warm cache returns results in O(1).
> A `PrunedAtlasExport` provably removes only edges that satisfy the pruning
> policy, with a signed `PruningAuditLog` recording what was removed.

## Design

### New model: `genesis_mesh/models/atlas.py`

```python
class TrustPathEntry(BaseModel):
    """Cached result of a single source -> target trust path computation."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_sovereign_id: str
    target_sovereign_id: str
    verdict: str                 # "allow" | "warn" | "escalate" | "block"
    hop_count: int
    path_sovereign_ids: list[str]
    graph_digest: str            # SHA-256 of the graph used for computation
    computed_at: datetime
    valid_until: datetime        # TTL-bound: must recompute after this
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def is_fresh(self, at_time: datetime | None = None) -> bool: ...


class TrustPathCache(BaseModel):
    """Collection of TrustPathEntries for a given graph snapshot."""
    cache_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    graph_digest: str
    entries: list[TrustPathEntry]
    created_at: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def lookup(
        self, source: str, target: str, at_time: datetime | None = None
    ) -> TrustPathEntry | None: ...

    def to_canonical_json(self) -> str: ...


class GraphPruningPolicy(BaseModel):
    """Rules for which graph edges may be safely removed."""
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    prune_expired_treaties_after_seconds: int = Field(
        default=86400,
        description="Remove treaty edges > N seconds past their valid_until.",
    )
    prune_revoked_certificates: bool = True
    prune_empty_scopes: bool = Field(
        default=True,
        description="Remove treaty edges where the scope is empty after "
                    "revocation propagation.",
    )
    max_graph_age_seconds: int = Field(
        default=3600,
        description="Refuse to prune a graph older than N seconds (staleness guard).",
    )
    signature: Signature | None = None


class PruningAuditEntry(BaseModel):
    edge_id: str
    removed_at: datetime
    removal_reason: str   # "expired_treaty" | "revoked_cert" | "empty_scope"
    edge_type: str
    source_sovereign_id: str
    target_sovereign_id: str


class PrunedAtlasExport(BaseModel):
    """Pruned, signed graph export with audit trail of what was removed."""
    export_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_graph_digest: str
    pruned_graph_digest: str
    policy_id: str
    original_edge_count: int
    pruned_edge_count: int
    removed_edge_count: int
    audit_entries: list[PruningAuditEntry]
    exported_at: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
```

### New trust functions: `genesis_mesh/trust/atlas.py`

```python
def cache_trust_path(
    source: str,
    target: str,
    graph: dict,
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    path_ttl_seconds: int = 300,
    now: datetime | None = None,
) -> TrustPathEntry:
    """Compute trust path and cache the result with a TTL."""

def lookup_trust_path(
    cache: TrustPathCache,
    source: str,
    target: str,
    *,
    at_time: datetime | None = None,
) -> TrustPathEntry | None:
    """Return cached entry if present and fresh; None otherwise."""

def prune_graph(
    graph: dict,
    policy: GraphPruningPolicy,
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> tuple[dict, PrunedAtlasExport]:
    """Apply pruning policy to graph, returning (pruned_graph, audit_export)."""

def build_trust_path_cache(
    pairs: list[tuple[str, str]],
    graph: dict,
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    path_ttl_seconds: int = 300,
    now: datetime | None = None,
) -> TrustPathCache:
    """Pre-compute trust paths for multiple (source, target) pairs."""
```

### CLI: `genesis_mesh/cli/atlas_ops.py` (extended)

```
trust atlas cache    --graph graph.json --pairs pairs.json
                      --operator-sovereign <id>
                      --signing-key operator.key --output cache.json

trust atlas lookup   --cache cache.json --from <id> --to <id>
                      [--format json]

trust atlas prune    --graph graph.json --policy policy.json
                      --operator-sovereign <id>
                      --signing-key operator.key
                      --output-graph pruned.json
                      --output-audit audit.json
```

### Test plan: `genesis_mesh/tests/test_trust_path_performance.py`

~28 tests:
- `cache_trust_path()`: path computed, signed, TTL set
- `lookup_trust_path()`: warm cache returns entry without recomputing
- Expired cache entry -> None (cache miss)
- Different graph_digest -> None (cache miss -- stale graph)
- `prune_graph()`: expired treaties removed
- Revoked certificates pruned when policy.prune_revoked_certificates=True
- Empty scope edges pruned when policy.prune_empty_scopes=True
- Audit log records every removed edge
- `max_graph_age_seconds` exceeded -> raises ValueError (refuse to prune stale graph)
- `build_trust_path_cache()`: all pairs computed
- Pruned graph digest differs from original
- `PrunedAtlasExport` verifiable against operator key
- CLI: cache / lookup / prune exit 0
- Cache with 0 entries -> lookup returns None

## Success Criteria

- [x] `TrustPathEntry`, `TrustPathCache`, `GraphPruningPolicy`, `PrunedAtlasExport` models
- [x] `cache_trust_path()`, `lookup_trust_path()`, `prune_graph()`, `build_trust_path_cache()`
- [x] Cache invalidation on TTL expiry and graph digest mismatch
- [x] Pruning audit log with per-edge removal reasons
- [x] CLI `trust atlas` extension with cache / lookup / prune
- [x] 21 tests; all pass; full suite passes (1004)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.46.0`
- [x] CHANGELOG entry
- [x] `docs/examples/trust-path-performance.md` worked example
- [x] CLI reference updated
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2605.05440 -- Authorization Propagation: Req 5 (temporal decay), Req 6 (path efficiency)
- arXiv:2606.12320 -- Five-Plane Architecture: Network Plane routing efficiency
