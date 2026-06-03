# v0.4.0 Plan - Documentation Site, Revocation Demo, Production Cleanup

## Goal

Publish a stronger documentation and demo layer around Genesis Mesh, including a
runnable revocation proof and production cleanup work that makes the project
easier to evaluate.

## Release Narrative

v0.4.0 is the release where Genesis Mesh becomes explainable outside the source
tree. It adds the GitHub Pages documentation path, improves diagram and README
quality, documents production-sensitive behavior, and introduces a revocation
demo so trust removal is visible instead of theoretical.

This release also continues runtime cleanup around renewal, heartbeat, proof of
possession, capped renewals, metrics, and deployment verification.

## Success Criteria

- [x] Documentation can be published through GitHub Pages.
- [x] Revocation is demonstrated through a runnable example.
- [x] Heartbeat and renewal validity behavior is covered.
- [x] Proof-of-possession and capped renewal behavior is documented and tested.
- [x] Metrics, Terraform, and deployment docs are clearer.
- [x] Diagrams and example assets render reliably.

## Scope

### In Scope

- [x] GitHub Pages documentation workflow.
- [x] Documentation cleanup and custom footer.
- [x] Runnable demo walkthroughs.
- [x] Revocation demo.
- [x] Certificate ID utility.
- [x] Heartbeat and renewal validity tests.
- [x] Proof-of-possession and capped renewal improvements.
- [x] Metrics and Terraform verification docs.
- [x] Diagram readability and image path fixes.
- [x] Python version requirement clarification.

### Out of Scope

- [x] Live Azure deployment.
- [x] Kubernetes manifests.
- [x] Multi-hop routing proof.
- [x] External sovereign recognition.

## Implementation Phases

### Phase 1 - Publishable Docs

- [x] Add GitHub Pages workflow.
- [x] Clean documentation navigation and generated pages.
- [x] Fix image paths and diagram readability.
- [x] Add project footer and production notes.

### Phase 2 - Revocation Demo

- [x] Add a runnable revocation walkthrough.
- [x] Add certificate ID helper behavior needed by the demo.
- [x] Document expected operator observations.

### Phase 3 - Runtime Cleanup

- [x] Add heartbeat and renewal validity tests.
- [x] Document proof-of-possession and capped renewals.
- [x] Improve metrics and deployment verification material.

## Verification Commands

```powershell
python -m pytest
sphinx-build -b html docs docs/_build/html
python scripts/record_revocation_demo.py
```

## Release Gate

- [x] Docs build and are suitable for GitHub Pages.
- [x] Revocation can be demonstrated from a clean local workflow.
- [x] Runtime cleanup has regression coverage.
