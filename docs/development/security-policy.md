# Security Policy

The canonical security policy lives at
[`SECURITY.md`](https://github.com/GenesisMeshLabs/genesismesh/blob/main/SECURITY.md)
in the repo root. It documents:

- What Genesis Mesh defends against (in scope)
- What Genesis Mesh does **not** defend against (out of scope)
- How to report a vulnerability privately
- Supported versions

This page covers only the **development-side** expectations for writing and
reviewing security-sensitive changes.

## Reviewing a Security Change

A security change should:

- include a test that fails without the fix and passes with it
- avoid unrelated refactors
- update the relevant docs in the same change if it touches a trust boundary
  or operational procedure

## Areas Requiring Careful Review

Pay extra attention to changes that touch (paths are under `genesis_mesh/`):

- private key handling
- signature verification
- canonical JSON signing payloads
- invite-token enrollment
- certificate renewal and revocation
- the root key and key succession (`trust/key_succession.py`,
  `na_service/services/key_history.py`)
- evidence store chains, anchors and retention (`trust/evidence_store.py`)
- grants and their budgets (`trust/grants.py`), and out-of-band records
  such as break-glass (`trust/out_of_band.py`)
- edge invites and node-signed requests (`crypto/node_auth.py`,
  `na_service/routes/edge.py`)
- strict JSON input and the canonical field registry (`strict_json.py`,
  `models/canonical_registry.py`)
- database migrations
- replay protection
- deployment secret handling
- peer handshake authentication (the dormant mesh node runtime)

Changes to the public contract, conformance vectors, migrations, signing
code, workflows or `SECURITY.md` wait for the Maintainer
({doc}`decisions/0006-review`).

## Reporting

Open a draft advisory at
[github.com/GenesisMeshLabs/genesismesh/security/advisories/new](https://github.com/GenesisMeshLabs/genesismesh/security/advisories/new).
See [SECURITY.md](https://github.com/GenesisMeshLabs/genesismesh/blob/main/SECURITY.md)
for the full reporting process, acknowledgement timeline, and remediation
expectations.
