# Phase A -- Foundation

**Versions**: v0.1.0 – v0.5.2
**Question**: Can we build a permissioned mesh of authenticated nodes?

## What Changed

A signed Genesis block defined the network root, policy, and authority. A
Network Authority issued join certificates. Nodes joined under those
certificates and spoke to each other over Noise XX transport. Messages
routed across the mesh. Revocation, health, metrics, and audit existed
at first-pass quality.

Subsequent releases in the phase hardened authorization and concurrency
(unauthenticated heartbeats, renewal as a privilege-escalation path,
replay-cache targeting, peer-manager deadlocks), added a persona-oriented
CLI, a browser-visible operator console, GitHub Pages documentation,
and a runnable revocation demo.

The first infrastructure proof shipped as Azure deployment via Terraform
and GitHub Actions. PyPI packaging made the project installable. VM
bootstrap runbooks, systemd units, and Kubernetes manifests followed.
SECURITY.md and a threat model established the public security posture.

## Value Added

- A permissioned mesh runs in production on Azure.
- Nodes hold cryptographic identity and speak Noise XX to each other.
- The Network Authority issues and revokes join certificates.
- The project is installable from PyPI and has a documented security posture.
- Operators can inspect node state and Connectome health through a browser console.

## What Became Possible

With authenticated routing and a working control plane, the mesh could
carry real application workloads. Phase B built the agent layer directly
on top of this foundation without changing a single transport primitive.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.1.0 | First usable runtime: Genesis block, NA, Noise XX transport, routing |
| v0.2.0 | Authorization and concurrency hardening: replay caches, heartbeat auth, renewal privilege |
| v0.3.0 | Operator CLI workflows, Sphinx docs site, NA browser console |
| v0.4.0 | GitHub Pages docs, revocation demo, proof-of-possession improvements |
| v0.5.0 | Azure Terraform deployment, GitHub Actions, multi-hop and failover demos |
| v0.5.1 | PyPI packaging, systemd units, VM bootstrap runbook |
| v0.5.2 | SECURITY.md, threat model, integration test markers |
