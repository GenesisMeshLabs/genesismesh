# Gateway alignment with v0.56.0

Align the Rust trust gateway with the existing SDK release train at v0.56.0.
Publish its source tag and a GitHub release in the existing
GenesisMeshLabs/gateway repository, matching the SDK repositories' Latest
release convention. Existing SDK and protocol tags remain immutable.

Release scope: embedded endpoint explorer, operator-scoped verification,
authenticated network data, signed CRL refresh, bounded CPU admission, metrics,
and portable Windows / Linux AMD64 / Linux ARM64 distributions.

Gates: Rust tests, formatting, Clippy, release builds, archive checksums,
configuration validation, and local/public readiness. ARM64 runtime checks use
emulation; cluster deployment and accreditation are outside this release.
