# v0.41.0 Plan -- Context-Injection Defense Gate

## Positioning

Verifiable Logic Attestation (v0.40) proves that an agent's *configuration*
(model, system prompt, tools) matches what was authorized.  But configuration
verification cannot protect against what happens to the agent's inputs at
runtime.  Prompt injection -- the insertion of adversarial instructions into
tool outputs, user turns, or retrieved documents -- bypasses attestation because
it does not modify the declared system prompt.  The system prompt hash checks out;
the actual context the model sees has been contaminated.

arXiv:2605.04093 (Decision Evidence Maturity Model) identifies this as the
"container fallacy": the assumption that because the container (system prompt,
model weights) is verified, all context arriving in the container is also trusted.
The 2026 research consensus is that context-injection is now the leading jailbreak
vector in deployed multi-agent systems.

v0.41 addresses this with `ContextIntegrityRecord`: a pre-execution commitment
to the base context *and* the typed, bounded append segments that are permitted
to arrive after that base (tool results, retrieval payloads, user turns).
The `ContextInjectionGate` verifies that the final context at execution time
equals the committed base plus exactly the declared append segments -- no more,
no less.

> **Critical invariant**: The final context hash is NOT expected to equal the
> pre-execution hash.  Tool-using agents naturally receive tool outputs, retrieved
> documents, and user turns after the initial context is committed.  The threat
> is not context growth per se -- it is *undeclared* context growth.  The
> security property is:
>
>     final_context = committed_base + declared_typed_append_segments
>
> Any segment present in the final context that was not declared (typed, sized,
> and provenance-linked) before execution is a violation.  This blocks injection
> via tool outputs and retrieval without disrupting legitimate agent operation.

> **Scope constraint**: Context integrity operates on structural properties:
> segment types, provenance hash, size bounds, and canonical tree structure.
> LLM-based semantic content analysis is out of scope.

v0.41 should prove:

> A `ContextIntegrityRecord` commits to the pre-execution base context hash and
> a list of declared `ContextAppendSegments` (each typed, sized, and provenance-
> linked).  A `ContextInjectionGate` passes if the final context matches the
> committed base plus all declared segments, and blocks if any undeclared,
> out-of-bounds, or untyped segment is present.

## Design

### New model: `genesis_mesh/models/context_integrity.py`

```python
class ContextTree(BaseModel):
    """Canonical representation of agent context for hashing."""
    system_prompt_hash: str
    turn_count: int
    message_hashes: list[str]      # SHA-256 of each turn's content
    tool_result_hashes: list[str]  # SHA-256 of each tool result
    total_token_estimate: int      # approximate size bound

    def canonical_hash(self) -> str:
        data = json.dumps(self.model_dump(mode="json"),
                          sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


class ContextAppendSegment(BaseModel):
    """A declared, typed unit of post-base context that is permitted to arrive.

    All context growth after the base must be declared as a ContextAppendSegment
    before execution.  Undeclared growth is treated as a context injection.
    """
    segment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    segment_type: str = Field(
        ...,
        description='"tool_result" | "retrieval" | "user_turn" | "system_observation"',
    )
    source_id: str = Field(
        ...,
        description="Tool name, retrieval source ID, or system component identifier.",
    )
    max_tokens: int = Field(
        ...,
        description="Maximum token count this segment may contribute. "
                    "Violation if actual exceeds this.",
    )
    provenance_digest: str = Field(
        ...,
        description="SHA-256 of the declared source metadata "
                    "(tool manifest hash, retrieval URI hash, etc.).",
    )
    signature: Signature | None = None


class ContextIntegrityRecord(BaseModel):
    """Pre-execution commitment: base context hash + declared append segments."""
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    decision_id: str
    committed_base_context_hash: str = Field(
        ...,
        description="SHA-256 canonical hash of the ContextTree at commitment time. "
                    "The FINAL context hash is NOT expected to equal this -- "
                    "only the base before declared segments are appended.",
    )
    declared_append_segments: list[ContextAppendSegment] = Field(
        default_factory=list,
        description="All segments permitted to be appended after the base. "
                    "Any undeclared segment in the final context is a violation.",
    )
    max_total_tokens: int = Field(
        ...,
        description="Hard cap: base tokens + sum of all declared segment max_tokens.",
    )
    committed_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class ContextViolationReport(BaseModel):
    """Record of a detected context integrity violation."""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    record_id: str
    agent_sovereign_id: str
    detected_at: datetime
    violation_type: str  # see ContextIntegrityReason
    committed_value: str
    observed_value: str
    severity: str  # "warning" | "block"
```

### New trust module: `genesis_mesh/trust/context_integrity.py`

```python
ContextIntegrityReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "undeclared_segment",          # final context contains segment not in declared_append_segments
    "segment_token_exceeded",      # a segment's actual tokens exceed its declared max_tokens
    "total_token_exceeded",        # total final tokens exceed max_total_tokens
    "base_context_tampered",       # the committed base portion of final context does not match hash
]

def create_context_integrity_record(
    agent_sovereign_id: str,
    decision_id: str,
    base_context_tree: ContextTree,
    declared_segments: list[ContextAppendSegment],
    signing_key: nacl.signing.SigningKey,
    *,
    max_total_tokens: int = 8192,
    valid_for_seconds: int = 600,
    now: datetime | None = None,
) -> ContextIntegrityRecord: ...

def verify_context_integrity(
    record: ContextIntegrityRecord,
    final_context_tree: ContextTree,
    observed_segments: list[ContextAppendSegment],
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, ContextIntegrityReason, ContextViolationReport | None]:
    """Verify that final context = committed base + declared append segments.

    A "valid" result requires ALL of:
    1. Record signature valid
    2. Record not expired
    3. Base portion of final_context_tree matches committed_base_context_hash
    4. Every observed_segment appears in record.declared_append_segments
    5. No observed segment's token count exceeds its declared max_tokens
    6. Total final tokens <= record.max_total_tokens
    """

class ContextInjectionGate:
    """Callable gate: passes only if final context = committed base + declared segments.

    Usage:
        gate = ContextInjectionGate(
            record=pre_execution_record,
            final_context=post_tool_call_context_tree,
            observed_segments=segments_present_after_execution,
            agent_public_keys=[agent_pub_b64],
        )
        engine.add_gate(gate)
    """
    def __init__(
        self,
        record: ContextIntegrityRecord,
        final_context: ContextTree,
        observed_segments: list[ContextAppendSegment],
        agent_public_keys: list[str],
    ) -> None: ...

    def __call__(self, context: object, terms: object) -> object: ...
```

### CLI: `genesis_mesh/cli/context_integrity_ops.py`

```
trust context commit   --agent-sovereign <id> --decision-id <id>
                        --system-prompt-file prompt.txt
                        --max-turns 20 --max-tool-results 50
                        --signing-key agent.key --output record.json

trust context verify   --record record.json --final-context context.json
                        --public-key agent.pub [--format json]
```

### Injection pattern detection (heuristic, non-blocking)

```python
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"system\s*prompt\s*override",
    r"<\|im_start\|>",    # OpenAI chat format injection
    r"\[INST\]",          # Llama instruction injection
    r"JAILBREAK",
]

def scan_for_injection_markers(
    content: str,
    patterns: list[str] | None = None,
) -> list[str]:
    """Returns list of matched pattern strings. Non-blocking -- caller decides."""
```

### Test plan: `genesis_mesh/tests/test_context_injection_defense.py`

~30 tests:
- `ContextTree.canonical_hash()`: deterministic, order-sensitive
- Identical trees -> identical hashes
- Single byte change -> different hash
- `create_context_integrity_record()`: base hash captured, segments declared
- `verify_context_integrity()`: base + all declared segments present -> valid
- Final context has zero undeclared segments and matching base -> valid
- Undeclared segment in final context -> undeclared_segment
- Declared segment whose actual tokens exceed declared max -> segment_token_exceeded
- Total tokens exceed max_total_tokens -> total_token_exceeded
- Base context hash mismatch (base was tampered) -> base_context_tampered
- Expired record -> expired
- `ContextInjectionGate`: passes when final = base + declared segments
- `ContextInjectionGate`: blocks on undeclared_segment
- `ContextInjectionGate`: blocks on segment_token_exceeded
- `ContextInjectionGate`: blocks on base_context_tampered
- `scan_for_injection_markers()`: detects known patterns
- Test with 3 declared segments (tool_result, retrieval, user_turn) all present -> valid
- CLI: commit / verify exit 0

## Success Criteria

- [x] `ContextTree`, `ContextAppendSegment`, `ContextIntegrityRecord`, `ContextViolationReport` models
- [x] `create_context_integrity_record()` and `verify_context_integrity()`
- [x] `ContextInjectionGate` with 8 typed reason codes (updated invariant: base + declared segments)
- [x] `scan_for_injection_markers()` heuristic scanner
- [x] Explicit test that tool results appended as declared segments pass the gate
- [x] CLI `trust integrity` subgroup with commit / verify (renamed from `context` to avoid collision)
- [x] >= 28 tests (36); all pass; full suite passes (875)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.41.0`
- [x] CHANGELOG entry
- [x] `docs/examples/context-injection-defense.md` worked example
- [x] CLI reference updated with `trust integrity`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2605.04093 -- Decision Evidence Maturity Model: the "container fallacy"
- arXiv:2604.02767 -- SentinelAgent: Property 4, input integrity verification
- arXiv:2606.12320 -- Five-Plane Architecture: Data Plane integrity requirements
