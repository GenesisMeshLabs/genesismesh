# v0.12.1 Plan - Independent Sovereigns Operational Proof

## Goal

Prove Genesis Mesh sovereignty across two independently hosted authorities by
running one sovereign on Azure and one on DigitalOcean, then demonstrating
recognition, attestation acceptance, revocation import, and rejection.

## Release Narrative

v0.12.1 is an operational proof release. v0.12.0 introduced the Connectome and
cross-sovereign trust model; this patch proves the flow on real infrastructure
from empty Connectome state.

The important claim is not "two services are online." The claim is that two
separate sovereigns can hold separate keys and trust state while recognition and
revocation propagate across provider boundaries.

## Success Criteria

- [x] Azure sovereign starts from empty Connectome state.
- [x] DigitalOcean sovereign starts from empty Connectome state.
- [x] Sovereign B uses the network name `USG-NB`.
- [x] NB issues a membership attestation.
- [x] Azure recognizes NB through a treaty.
- [x] Azure accepts the NB-issued attestation before revocation.
- [x] NB revokes the attestation.
- [x] Azure imports NB revocation material.
- [x] Azure rejects the same attestation after revocation.
- [x] Example documentation, PNG, GIF, and transcript renderer exist.

## Scope

### In Scope

- [x] Independent sovereigns example.
- [x] Provider-neutral Ubuntu VM bootstrap script.
- [x] DigitalOcean bootstrap path for Sovereign B.
- [x] Azure + DigitalOcean proof transcript.
- [x] Live-mode transcript renderer.
- [x] PNG and GIF release assets.
- [x] Documentation explaining the operational context.

### Out of Scope

- [x] External future external operator.
- [x] Long-lived production treaty registry.
- [x] Automated cleanup across all deployed sovereigns.
- [x] Managed sovereign backup/restore.
- [x] Supply-chain CI gate.

## Implementation Phases

### Phase 1 - Provider-Neutral Bootstrap

- [x] Add Ubuntu VM bootstrap script.
- [x] Document Azure and DigitalOcean setup paths.
- [x] Support clean Network Authority service startup on the VM.
- [x] Keep service configuration usable for NB naming.

### Phase 2 - Independent Sovereign Proof

- [x] Start both authorities from empty Connectome state.
- [x] Create treaty from Azure sovereign to NB.
- [x] Issue NB attestation.
- [x] Verify Azure accepts before revocation.
- [x] Revoke on NB.
- [x] Import revocation into Azure.
- [x] Verify Azure rejects after revocation.

### Phase 3 - Evidence Assets

- [x] Add independent-sovereigns example markdown.
- [x] Add transcript renderer with live mode.
- [x] Add PNG asset.
- [x] Add GIF asset.
- [x] Capture release evidence in changelog.

## Verification Commands

```powershell
curl -fsS https://na.genesismesh.connectorzzz.com/healthz
curl -fsS https://na.genesismesh.connectorzzz.com/connectome.json
curl -fsS http://164.92.250.135:8443/healthz
curl -fsS http://164.92.250.135:8443/connectome.json
python scripts/render_independent_sovereigns_transcript.py --live
```

## Release Gate

- [x] Two live sovereigns prove recognition and revocation across Azure and
  DigitalOcean.
- [x] Connectome evidence shows both sovereigns and trust state.
- [x] Release assets make the proof reviewable without rerunning the VMs.
