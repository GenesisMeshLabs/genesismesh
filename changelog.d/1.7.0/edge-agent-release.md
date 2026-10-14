### Added

- **The edge agent's release is checked as a consumer gets it.** The `Published artifacts` workflow's `edge` job
  (from 1.7.0) downloads `genesis-mesh-edge` for x86_64 and aarch64 and `SHA256SUMS-edge` from the Rust SDK
  release, verifies their Sigstore signatures and checksums, checks the binary is static and reports the release,
  verifies the signed image `ghcr.io/genesismeshlabs/genesis-mesh-edge` and that it holds the released binary, and
  runs the released agent against the released Network Authority image (`scripts/container_smoke.py --edge-image`):
  it enrols with an edge invite, gets a decision for one action and reaches state `revoked` after one
  `/admin/revoke`.
