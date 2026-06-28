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

Pay extra attention to changes that touch:

- private key handling
- signature verification
- canonical JSON signing payloads
- invite-token enrollment
- certificate renewal and revocation
- peer handshake authentication
- replay protection
- deployment secret handling

## Reporting

Open a draft advisory at
[github.com/GenesisMeshLabs/genesismesh/security/advisories/new](https://github.com/GenesisMeshLabs/genesismesh/security/advisories/new).
See [SECURITY.md](https://github.com/GenesisMeshLabs/genesismesh/blob/main/SECURITY.md)
for the full reporting process, acknowledgement timeline, and remediation
expectations.
