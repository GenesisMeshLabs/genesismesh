# Versioning

Genesis Mesh uses one coordinated product version across the reference
implementation and every official SDK. Version `0.56.0` is the first release
train governed by this policy.

## Coordinated release train

The following components publish the same version:

- `genesis-mesh`, the Python reference implementation and Network Authority
- `genesis-mesh-sdk`, the TypeScript SDK
- `github.com/GenesisMeshLabs/sdk-go`, the Go SDK
- `genesismesh-sdk-dotnet`, the .NET SDK
- official independent protocol verifiers

Every coordinated release tags each component repository with the same
`vX.Y.Z` value. A component with no functional changes still receives the
coordinated version after its compatibility tests pass.

The authoritative development version is stored in `VERSION` in each
repository. Package manifests must match it. Publishing workflows reject a tag
that does not match the repository's declared version.

## Versions that remain independent

Product versions do not replace wire-format or evidence-schema versions.

- RFC revisions identify protocol specifications.
- Conformance vectors keep their own schema version.
- Network genesis documents keep their declared network version.
- Deployments identify the product version and exact source commit.

Documentation must label these values explicitly. An SDK's historical first
release is not the current Genesis Mesh product version.

## Release integrity

Published tags are immutable. Historical tags are not rewritten to repair
metadata. Corrections ship in the next coordinated release.

Before a release is published:

1. All component `VERSION` files and package manifests must match.
2. Core and SDK test suites must pass against the same Trust API contract.
3. Security policies must identify the coordinated supported minor line.
4. Changelogs must distinguish historical component releases from the current
   product release.
5. Public documentation and the website must use the coordinated product
   version when describing Genesis Mesh as a whole.
