# v0.5.1 Plan - PyPI Packaging and Reproducible VM Bootstrap

## Goal

Make Genesis Mesh installable and repeatable by adding PyPI release support,
pre-commit hygiene, canonical systemd units, and a VM bootstrap runbook.

## Release Narrative

v0.5.1 turns the live proof into something operators can reproduce. The release
focuses on packaging, release mechanics, and VM operation rather than new mesh
features.

This is the bridge between "the maintainer can deploy it" and "another operator
can install and run the same service layout."

## Success Criteria

- [x] Package metadata is ready for PyPI publishing.
- [x] Release scripts and documentation explain the publishing path.
- [x] Pre-commit checks are configured and documented.
- [x] Canonical systemd units exist for VM operation.
- [x] VM bootstrap runbook documents repeatable setup.
- [x] README and installation docs are aligned with package usage.

## Scope

### In Scope

- [x] PyPI package configuration.
- [x] Publishing scripts.
- [x] README installation updates.
- [x] Pre-commit configuration.
- [x] CONTRIBUTING guidance.
- [x] JSON and docs formatting hygiene.
- [x] Canonical systemd units.
- [x] VM bootstrap runbook.
- [x] Version bump to v0.5.1.

### Out of Scope

- [x] New protocol behavior.
- [x] New demos beyond packaging and bootstrap proof.
- [x] External operator recognition.
- [x] Managed service operations.

## Implementation Phases

### Phase 1 - Packaging

- [x] Update package metadata for PyPI.
- [x] Add publishing scripts.
- [x] Update README installation instructions.
- [x] Bump package version.

### Phase 2 - Repository Hygiene

- [x] Add pre-commit configuration.
- [x] Add contributing documentation.
- [x] Normalize JSON and docs formatting.
- [x] Link docs consistently.

### Phase 3 - VM Operation

- [x] Add canonical systemd units.
- [x] Add VM bootstrap runbook.
- [x] Align bootstrap docs with the deployed service layout.

## Verification Commands

```powershell
pre-commit run --all-files
python -m pytest
python -m build
twine check dist/*
```

## Release Gate

- [x] Package artifacts can be built and checked.
- [x] Pre-commit hooks pass.
- [x] VM bootstrap documentation matches the systemd service layout.
