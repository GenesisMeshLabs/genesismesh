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
- the offline verifier `genesis-mesh-verify` and, from 1.7.0, the edge agent
  `genesis-mesh-edge` (both released with the Rust SDK)

Every coordinated release tags each component repository with the same
`vX.Y.Z` value. A component with no functional changes still receives the
coordinated version after its compatibility tests pass. Decision
{doc}`decisions/0001-release-model` replaces this lockstep with a pinned
contract bundle; it is not implemented yet, so the rules on this page apply.

From 1.1.0, the release also publishes the container images
`ghcr.io/genesismeshlabs/genesis-mesh` and
`ghcr.io/genesismeshlabs/genesis-mesh-gateway` with the same `X.Y.Z` tag.
From 1.5.0 the Rust SDK's release also carries the offline verifier
`genesis-mesh-verify` (static Linux binaries for x86-64 and arm64, with
`SHA256SUMS` and Sigstore bundles), versioned with the Rust SDK. It is a
hand-ported second implementation of the Python reference's verification: a
Rust port checked against a corpus the reference generates. The
published-artifacts check verifies its signatures and runs it on the frozen
1.5.0 audit pack with the network off. From 1.7.0 the Rust SDK's release also
carries the edge agent `genesis-mesh-edge` (beta): static Linux binaries for
x86_64 and aarch64 listed in `SHA256SUMS-edge`, and the image
`ghcr.io/genesismeshlabs/genesis-mesh-edge`, tagged `X.Y.Z` only while it is
beta.

The authoritative development version is stored in `VERSION` in each
repository; the gateway has no `VERSION` file and keeps it in `Cargo.toml`.
Package manifests must match it. Publishing workflows reject a tag
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

A release tag is tested against the core release of the same version, never
core `main`, which may already carry the next version's changes: the core's
image workflow builds the gateway's tag of its version, and the SDKs' and the
gateway's tag builds check out the core tag of theirs.

## Cutting a release and propagating it

Nobody edits version numbers by hand.

- **The core states its version in one command.** Besides `VERSION`,
  `pyproject.toml` and the source fallback, the core states the current release
  in its README, the gateway and SDK pages, the install commands and the
  Compose and Kubernetes examples. `scripts/check_version.py` lists every such
  statement (`SITES`): the check (pre-commit, CI, the publish workflows) fails
  when one lags `VERSION`, and `python scripts/check_version.py --set X.Y.Z`
  writes them all. A page that starts stating the current release, for example
  an install command with the version, is added to `SITES` in the same pull
  request. Historical mentions ("from 1.7.0") are not sites.
- **The train is cut at once.** `devtools/release.py prepare X.Y.Z --title
  "..."` opens `release/X.Y.Z` in the six repositories: it writes the version
  everywhere each declares it, folds the changelog fragments (a component with
  none gets "Nothing changes in this SDK"), runs the repository's own version
  check and opens the pull request. The core's pull request then gets its
  release narrative; the Maintainer merges the core first, then the
  components. `devtools/release.py tag X.Y.Z` signs and pushes the tags, the
  core first, and creates the core's GitHub release, which publishes it.
- **Everything that pins a release follows.** The MCP server, the labs, the
  Backstage plugin, the sandbox and the websites extend the shared Renovate
  preset (`devtools/renovate/genesis-mesh.json`). When a version is published,
  Renovate opens one "Update Genesis Mesh" pull request in each; the .NET SDK
  uses it to move its API baseline once NuGet has the release.
- **The live hosts.** The Azure reference instance deploys a tag through
  `deploy-release-azure-vm.yml`; mesh.genesismesh.org upgrades with
  `infrastructure/mesh-demo/upgrade.sh X.Y.Z`. Both are production changes the
  Maintainer starts.

## Changelogs: fragments, folded at release

Work for the next version often starts before the current release merges. Two
pull requests that edit the top of a changelog conflict: the release PR dates
the version heading, the feature PR adds the next version's section right
above it. So pull requests never edit `CHANGELOG.md` (the core and the four
SDKs, since 1.3.0; the gateway has no changelog: its release notes are in
the pull request and the GitHub release):

1. A change adds its entry as a fragment, `changelog.d/<version>/<name>.md`,
   written as the changelog entry under `### Added`, `### Changed`, `### Fixed`,
   `### Security`, `### Upgrading` (or another `###` heading). Any number of
   pull requests can add fragments for one version.
2. The release PR (branch `release/<version>`, for example `release/1.3.1`)
   folds them into `CHANGELOG.md` and removes them, writing the sections in a
   fixed order: Security, Added, Changed, Deprecated, Removed, Fixed, any
   other section in the order it first appears, then Upgrading. It refuses a
   heading that does not name the version, and a version `CHANGELOG.md`
   already has:

   ```bash
   python scripts/changelog.py preview 1.3.0
   python scripts/changelog.py release 1.3.0 --heading "## v1.3.0 - Observations, Judgements and Break-Glass"
   ```

   The TypeScript, Go and .NET SDKs use the heading form
   `## [1.3.0] - 2026-10-11`; the Rust SDK uses `## 1.3.0 - 2026-10-11`.
3. CI (`Changelog fragments`) checks every fragment, refuses one for a version
   already released or outside `changelog.d/<version>/` (the release would
   never fold it), and refuses any change to `CHANGELOG.md` (added, removed or
   rewritten lines) from a branch other than `release/<version>`. A fragment
   holds only `### Section` headings at the start of a line, no line starting
   with `## ` even in a code block (it would end the version's release
   notes), and no byte order mark.
4. Upgrade notes work the same way: a change that needs an operator step on
   upgrade adds `upgrade.d/<version>/<name>.md` (see `upgrade.d/README.md`),
   and the release PR folds them into `docs/operations/upgrade.md` with
   `python scripts/upgrade_notes.py release <version>`. The same CI check
   refuses an "Upgrading to" section for a version newer than `VERSION`.

Documentation follows the same rule for versioned headings: a section for an
unreleased version carries its marker on a line of its own below the heading
(`*Unreleased.*`), never in the heading, so the release removes a line no
feature pull request for the next version touches.

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

Published tags are immutable. In each of the six repositories a ruleset
("release tags are immutable", on `refs/tags/v*`) refuses moving or deleting
a release tag. The one recorded exception: the Rust SDK's `v1.7.0`
tag was re-pointed to a workflow fix after the edge release job failed
before it signed or published anything, with the Maintainer's approval and
the rule disabled for that push. Historical tags are not rewritten to repair
metadata. Corrections ship in the next coordinated release.

Before a release is published:

1. All component `VERSION` files and package manifests must match.
2. Core and SDK test suites must pass against the same Trust API contract.
3. Security policies must identify the coordinated supported minor line.
4. Changelogs must distinguish historical component releases from the current
   product release.
5. Public documentation and the website must use the coordinated product
   version when describing Genesis Mesh as a whole.
