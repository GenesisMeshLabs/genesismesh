# Security Policy

Genesis Mesh is security-sensitive infrastructure. Report vulnerabilities
privately before opening public issues.

## Supported Scope

Security review should focus on:

- private key handling
- signature verification
- canonical JSON signing payloads
- invite-token enrollment
- certificate renewal and revocation
- peer handshake authentication
- replay protection
- deployment secret handling

## Reporting

Until a dedicated security contact is published, do not include exploit details
in public issues. Share a minimal private report with:

- affected component
- expected behavior
- observed behavior
- reproduction steps
- impact assessment
- suggested fix, if known

## Disclosure Expectations

Security fixes should include tests where practical and should avoid unrelated
refactors. If a fix changes trust boundaries or operational procedures, update
the relevant docs in the same change.
