# v0.7.1 Plan - Discovery and LLM Demo Polish

## Goal

Polish the discovery and LLM-backed agent demo so the registry story is visible,
recordable, and safe to publish.

## Release Narrative

v0.7.1 is a demo-quality release. v0.7.0 introduced discovery; this patch makes
the story easier to see by placing capability discovery before requester action,
refreshing image and GIF assets, redacting provider secrets, and ensuring the
LLM-backed demo can be reproduced with real provider settings.

## Success Criteria

- [x] Discovery is shown before requester invocation.
- [x] LLM demo recorder polls `llm:chat`.
- [x] Secrets are redacted from recorded output.
- [x] Static PNG and refreshed GIF assets exist.
- [x] Demo sections are ordered for comprehension.
- [x] Focused tests and Sphinx docs pass.

## Scope

### In Scope

- [x] LLM-backed agent demo polish.
- [x] Capability discovery ordering in docs/examples.
- [x] Recorder polling for `llm:chat`.
- [x] Secret redaction.
- [x] Static PNG asset.
- [x] Refreshed GIF asset.
- [x] Focused tests and docs verification.

### Out of Scope

- [x] New orchestration protocol.
- [x] Trust-aware failover.
- [x] External providers beyond configured LLM settings.
- [x] Cross-sovereign proof.

## Implementation Phases

### Phase 1 - Demo Flow

- [x] Reorder demo sections around capability discovery.
- [x] Show requester behavior after discovery.
- [x] Keep the demo aligned with actual registry behavior.

### Phase 2 - Recording Safety

- [x] Poll `llm:chat` capability during recording.
- [x] Redact LLM provider secrets.
- [x] Validate with real `LLM_*` provider settings.

### Phase 3 - Assets and Docs

- [x] Add static PNG.
- [x] Refresh GIF.
- [x] Update docs and example references.
- [x] Build Sphinx documentation.

## Verification Commands

```powershell
python -m pytest tests -k "discovery or llm"
sphinx-build -b html docs docs/_build/html
python scripts/record_llm_discovery_demo.py
```

## Release Gate

- [x] Demo can be recorded without leaking secrets.
- [x] Documentation shows discovery before invocation.
- [x] Updated assets render in docs.
