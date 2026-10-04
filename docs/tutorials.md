# Tutorials

The walkthroughs below build on each other. Do them in this order the first
time; each one links to the commands and code it uses.

1. [Build and verify trust evidence](tutorial.md): sign an evidence record
   with an SDK and verify it.
2. [Independent sovereigns](examples/independent-sovereigns.md): run two
   sovereigns that share no root of trust.
3. [Federation bootstrap and trust bundle exchange](examples/operator-onboarding-exchange.md):
   exchange public trust material and recognize another sovereign.
4. [Treaty lifecycle management](examples/treaty-lifecycle-management.md):
   inspect, renew, replace and revoke treaties.
5. [Cross-sovereign revocation](examples/cross-sovereign-revocation.md): watch
   a revocation propagate to a recognizing sovereign.
6. [Declarative boundary policy](examples/declarative-boundary-policy.md):
   limit what a recognized sovereign may do.
7. [Governed SDK actions](sdk/typescript/governance.md): run an action that is
   authorized, executed and recorded as evidence.
8. [Evidence and audit](examples/trust-evidence-audit.md): export the evidence
   and verify it offline.

Prefer to look first? [mesh.genesismesh.org](https://mesh.genesismesh.org)
shows recognition, revocation, boundary policy, governed actions and
evidence live, with demo access and a guided tour.
