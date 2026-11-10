### Fixed

- **The gateway image is published again, and is static** (gateway
  1.10.1). Its runtime was `distroless/cc-debian13`, whose glibc, OpenSSL and
  zlib the gateway does not use; the release scan stopped the 1.9.2 and
  1.10.0 gateway images on that zlib (CVE-2026-76844 and CVE-2026-85091,
  high), so neither was published. From 1.10.1 the gateway's binaries are
  static (musl) and its runtime is `distroless/static`, with no libc or
  shared libraries. The image's user, port, health check and state are
  unchanged. Nothing else changes in 1.10.1.
