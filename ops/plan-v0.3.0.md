# v0.3.0 Plan - Production CLI, Sphinx Documentation, NA Console

## Goal

Make Genesis Mesh easier to understand and operate by adding persona-oriented
CLI workflows, generated documentation, and a Network Authority console with
node visibility.

## Release Narrative

v0.3.0 moves the project from "runtime exists" to "operators can inspect and
drive it." The work packages the protocol into clearer command paths, documents
the system with a Sphinx site, and gives the Network Authority a browser-visible
surface for node state.

This release is the first major usability layer on top of the hardened v0.2.0
runtime.

## Success Criteria

- [x] CLI commands are organized around operator personas and workflows.
- [x] The node CLI command is separated and easier to discover.
- [x] Sphinx documentation exists and can be generated.
- [x] Project docs explain architecture and operation.
- [x] Network Authority console exposes node visibility.
- [x] Local generated artifacts and documentation hygiene are improved.

## Scope

### In Scope

- [x] Persona-oriented CLI workflows.
- [x] Node CLI command refactor.
- [x] Sphinx documentation site.
- [x] Generated documentation pages.
- [x] Network Authority console.
- [x] Node visibility in the NA surface.
- [x] Production docs and local artifact hygiene.

### Out of Scope

- [x] GitHub Pages publishing workflow.
- [x] Live cloud deployment proof.
- [x] Multi-hop and failover demos.
- [x] External operator workflows.

## Implementation Phases

### Phase 1 - CLI Reshape

- [x] Move node command code into clearer ownership.
- [x] Add persona-oriented workflows.
- [x] Keep existing command behavior compatible where possible.

### Phase 2 - Documentation Site

- [x] Add Sphinx configuration.
- [x] Add generated API and project pages.
- [x] Document production usage and local artifacts.

### Phase 3 - Network Authority Console

- [x] Add browser console surface.
- [x] Show node visibility in the Network Authority.
- [x] Keep console behavior aligned with the existing NA runtime.

## Verification Commands

```powershell
python -m pytest
sphinx-build -b html docs docs/_build/html
genesis-mesh --help
genesis-mesh node --help
```

## Release Gate

- [x] CLI help and persona workflows are usable.
- [x] Documentation builds successfully.
- [x] NA console exposes node visibility without breaking authority endpoints.
