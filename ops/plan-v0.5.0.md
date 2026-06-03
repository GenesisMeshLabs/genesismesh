# v0.5.0 Plan - Live Azure Deployment and Mesh Proof

## Goal

Prove Genesis Mesh outside localhost by deploying it on Azure and demonstrating
live authority, node, routing, multi-hop, and failover behavior.

## Release Narrative

v0.5.0 is the first infrastructure proof release. The project moves from
documented local demos to a live cloud deployment story with Azure automation,
service configuration, network security rules, operational docs, and example
artifacts.

The release also adds Kubernetes examples so the deployment model is not locked
to one VM shape.

## Success Criteria

- [x] Azure deployment material can stand up the Network Authority and nodes.
- [x] GitHub Actions can drive deployment automation.
- [x] Live deployment docs explain the operator path.
- [x] Heartbeat and peer liveness work in cloud conditions.
- [x] Peer-to-peer send, multi-hop, and failover demos exist.
- [x] Kubernetes manifests are available as deployment examples.

## Scope

### In Scope

- [x] Azure infrastructure and NSG material.
- [x] GitHub Actions deployment workflow.
- [x] Live deployment documentation.
- [x] ProxyFix and cloud runtime adjustments.
- [x] Heartbeat loop and bootstrap peer behavior.
- [x] Send command and peer-to-peer messaging demo.
- [x] Multi-hop demo and GIF asset.
- [x] Failover demo.
- [x] Kubernetes deployment manifests and example README.

### Out of Scope

- [x] PyPI packaging.
- [x] Reproducible VM bootstrap script.
- [x] Independent second cloud provider.
- [x] Cross-sovereign recognition.

## Implementation Phases

### Phase 1 - Azure Deployment

- [x] Add Azure infrastructure configuration.
- [x] Add deployment workflow automation.
- [x] Configure network security for authority and node traffic.
- [x] Document the live deployment path.

### Phase 2 - Runtime Cloud Fixes

- [x] Add ProxyFix behavior for cloud ingress.
- [x] Repair heartbeat loop behavior in deployed mode.
- [x] Improve bootstrap peer startup.

### Phase 3 - Mesh Proofs

- [x] Add peer-to-peer send command.
- [x] Record peer-to-peer send demo.
- [x] Record multi-hop routing demo and GIF.
- [x] Record failover behavior.

### Phase 4 - Deployment Examples

- [x] Add Kubernetes manifests.
- [x] Add Kubernetes example README.
- [x] Keep live deployment docs aligned with the examples.

## Verification Commands

```powershell
python -m pytest
genesis-mesh send --help
python scripts/record_p2p_send_demo.py
python scripts/record_multihop_demo.py
python scripts/record_failover_demo.py
```

## Release Gate

- [x] Azure deployment can be followed from documentation.
- [x] Live mesh messaging proof exists.
- [x] Multi-hop and failover are demonstrated.
- [x] Kubernetes examples are included without changing the core runtime.
