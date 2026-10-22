### Documentation

- **Every page checked against the code.** The operations, operator,
  reference, development, example, concept, SDK and API pages were audited
  against `main`. Wrong defaults, commands that did not run, stale versions
  and overclaims are fixed. Pages that predate key succession now say that
  planned rotation is possible, and that a compromised key still means a new
  identity.
- **Off-by-default features are marked.** Every page states which settings
  a guarantee depends on. The evidence store, out-of-band records,
  remediation and grants are off by default. The outbox, break-glass and
  grant holders exist only in the TypeScript and Rust SDKs and the edge
  agent.
- **Safer instructions.** `terraform apply` no longer uses
  `-auto-approve`. `proof cleanup` is documented as deleting every treaty,
  attestation and feed. `treaty renew` documents its 24-hour default. The
  incident runbook revokes a treaty with a signed command.
- **New walkthroughs with recorded runs:**
  - boundary policies;
  - the evidence store;
  - out-of-band changes;
  - pre-issued grants;
  - evidence anchors, a restore drill, audit verification, key succession
    and the edge agent;
  - the SDK tutorial, interoperability and `dev up`;
  - the Tamarin proofs.

  `docs/examples/assets/scripts/render_terminal_gif.py` renders a captured
  run as a GIF, so each recording can be rebuilt.
- **Grouped navigation.** The phases, the governed-change runbooks, the CLI
  reference, the SDK pages and the project pages are grouped instead of
  being long flat lists.
