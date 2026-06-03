# Supply-Chain Trust Gate

This example shows Genesis Mesh acting as a narrow CI/release gate. It does not
replace a package registry, transparency log, or provenance system. It proves
one smaller claim:

> A project can accept or reject a maintainer action based on a portable
> attestation issued by another sovereign, and revocation of that attestation
> blocks the action without local re-enrollment.

## Flow

```{mermaid}
sequenceDiagram
    participant A as Project A Sovereign
    participant B as Project B Sovereign
    participant CI as CI / Release Gate

    A->>A: Issue Alice maintainer attestation
    B->>B: Sign treaty recognizing Project A maintainer role
    CI->>CI: Verify attestation + treaty
    CI-->>B: Allow release action
    A->>A: Revoke Alice attestation
    A-->>CI: Publish signed revocation feed
    CI->>CI: Verify same attestation + imported feed
    CI-->>B: Deny release action
```

## Maintainer Claim Profile

The gate uses the existing `MembershipAttestation` primitive with a scoped
supply-chain profile:

```json
{
  "profile": "genesis-mesh/supply-chain-maintainer/v1",
  "project_id": "pypi:demo-package",
  "repository": "https://github.com/example/demo-package",
  "delegated_role": "release-maintainer"
}
```

The attestation role must include:

```text
role:supply-chain:release-maintainer
```

The accepting project signs a recognition treaty that allows that role from the
issuing project sovereign.

## Run The Demo

Generate the checked-in demo artifacts and PNG/GIF assets:

```powershell
python docs\examples\assets\scripts\supply-chain-trust-gate-demo.py
```

Run the verifier before revocation:

```powershell
$KEY = Get-Content docs\examples\assets\supply-chain-trust-gate\treaty-issuer-public-key.txt

genesis-mesh supply-chain verify `
  --attestation docs\examples\assets\supply-chain-trust-gate\maintainer-attestation.json `
  --treaty docs\examples\assets\supply-chain-trust-gate\recognition-treaty.json `
  --treaty-issuer-public-key $KEY `
  --project-id pypi:demo-package `
  --repository https://github.com/example/demo-package `
  --proof-bundle supply-chain-trust-gate-proof.json
```

Expected result:

```text
ALLOW supply-chain trust gate
  reason:       accepted
  exit_code:    0
```

Run the same verifier with Project A's signed revocation feed:

```powershell
genesis-mesh supply-chain verify `
  --attestation docs\examples\assets\supply-chain-trust-gate\maintainer-attestation.json `
  --treaty docs\examples\assets\supply-chain-trust-gate\recognition-treaty.json `
  --treaty-issuer-public-key $KEY `
  --project-id pypi:demo-package `
  --repository https://github.com/example/demo-package `
  --revocation-feed docs\examples\assets\supply-chain-trust-gate\revocation-feed.json
```

Expected result:

```text
DENY supply-chain trust gate
  reason:       attestation_locally_revoked
  exit_code:    10
```

The verifier prints only a compact audit summary. It does not print private
keys, full request bodies, or signed payload bodies.

## GitHub Actions Example

The sample workflow lives at
`docs/examples/assets/github-actions/supply-chain-trust-gate.yml`. It installs
Genesis Mesh, verifies the checked-in attestation and treaty, and writes a
redacted proof bundle suitable for CI artifacts.

## What This Proves

- A maintainer action can be authorized by a portable sovereign attestation.
- A second project can recognize the issuing sovereign through a signed treaty.
- The gate returns stable CI exit codes: `0` for allow, `10` for deny, `2` for
  verifier errors.
- A signed revocation feed blocks the same maintainer without local
  re-enrollment.
- The audit output explains the issuer, treaty, role, revocation reason, and
  trust path.

## What This Does Not Claim

- It does not replace Sigstore, SLSA, npm provenance, PyPI attestations, GitHub
  artifact attestations, or transparency logs.
- It does not publish packages to a registry.
- It does not provide package-manager policy plugins.
- It does not prove all supply-chain security. It proves portable trust
  enforcement at one release gate.

See also:

- [Why a maintainer would run a sovereign](maintainer-sovereign-pitch.md)
- [Genesis Mesh vs Sigstore and SLSA](sigstore-comparison.md)

```{image} assets/images/genesis-mesh-supply-chain-trust-gate.png
:alt: Static supply-chain trust gate proof showing allow before revocation and deny after revocation
:width: 100%
```

```{image} assets/images/genesis-mesh-supply-chain-trust-gate.gif
:alt: Animated supply-chain trust gate proof showing portable maintainer trust and revocation
:width: 100%
```
