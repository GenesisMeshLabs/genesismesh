# Authorization Controls

Invocation-bound capability tokens, human oversight, selective disclosure,
process-level mediation, and the ephemeral identity purge.

- {doc}`invocation-bound-tokens` — a signed token an agent carries to prove what it may do, offline
- {doc}`human-oversight` — policy checks and dual-signed commitments for high-stakes actions
- {doc}`selective-disclosure` — proving one capability without revealing the others
- {doc}`process-level-mediation` — GenesisGuard, a local sidecar that checks before it runs a process
- {doc}`ephemeral-identity-purge` — signed receipts for purged ephemeral identities

```{toctree}
:hidden:

invocation-bound-tokens
human-oversight
selective-disclosure
process-level-mediation
ephemeral-identity-purge
```
