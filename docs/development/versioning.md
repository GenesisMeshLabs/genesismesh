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
- `genesis-mesh-sdk`, the Rust SDK (`GenesisMeshLabs/sdk-rust`)
- `genesis-mesh-gateway`, the Rust trust gateway (`GenesisMeshLabs/gateway`)
- official independent protocol verifiers

Every coordinated release tags each component repository with the same
`vX.Y.Z` value. A component with no functional changes still receives the
coordinated version after its compatibility tests pass.

The authoritative development version is stored in `VERSION` in each
repository. Package manifests must match it. Publishing workflows reject a tag
that does not match the repository's declared version.

## The core leads the train

The core repository (`genesismesh`) chooses each coordinated version, and no
component may release ahead of it. Two automated gates enforce this:

- **Core gate.** `scripts/check_release_train.py` runs in CI and before PyPI
  publication. It fails when any component repository, or the core itself, has
  already published a tag newer than the core `VERSION`. A new core version must
  therefore be newer than every version already released anywhere in the train.
- **Component gate.** Each component's CI fails when its declared version is
  newer than the core `VERSION` on `main`, and a tag build fails unless its
  version equals that `VERSION` or an existing core tag.

A component that needs a fix between coordinated releases waits for, or triggers,
the next coordinated patch release; it does not take the next number on its own.

### v0.57: a skipped version

Before the gateway and the Rust SDK joined the train, the gateway released
`v0.57.0` through `v0.57.2` on its own. To keep one number per release, the core
and the other SDKs skipped 0.57: the release planned as core v0.57.0 (Declarative
Boundary Policy) shipped as v0.58.0, and every component, including the gateway
and the Rust SDK, joined the coordinated train at v0.58.0. Tags `v0.57.x` exist
only in the gateway repository.

## 1.0.0 and the 1.x line

`1.0.0` marks a stable public contract, not the completion of every goal:
the surfaces classified stable in {doc}`../reference/public-contract` follow
`DEPRECATION_POLICY.md` for the whole 1.x line. The conditions for tagging it
are the go/no-go gate in `ops/plan-v1.0.0.md`. Evidence that 1.0.0 does not
yet have (a second independently implemented sovereign, an external operator
proof) is listed as pending in its release notes rather than claimed.

Within 1.x the release train works as before: the core leads, components
follow with the same version, and a minor version may add surfaces but not
break stable ones.

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
