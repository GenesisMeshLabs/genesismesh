### Added

- **The SDKs apply the vouching horizon.** From 1.8.1 the TypeScript, Rust,
  Go and .NET SDKs judge NA-signed records for the present when asked. A
  record of a key that has ended vouches only until that key's end, the
  hand-over and the grace, as the Network Authority and mesh nodes judge it
  since 1.8.0. Each SDK runs the shared `vouching` conformance suite, and the
  interoperability check compares their copies with the core's. The SDK
  guides say what each one offers: offline verifiers with a `now`, the
  reference's `na_record_refusal`, and in TypeScript and Rust a grant holder
  that orders revocation feeds by their signer's key.
