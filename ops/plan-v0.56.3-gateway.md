# Gateway v0.56.3: operator federation and repository boundaries

Approved scope: clean up Python operations in the Rust gateway, complete guided
recognition, automatic revocation propagation and native onboarding preflight.
Supports Phase 2 externalization; does not claim completed independent adoption.

## Delivered behavior

- Rust `genesis-mesh-operator` checks pinned identity, signatures, freshness,
  delegation validity and wire shape; produces a policy fragment only on success.
- UI prepares scoped, directed treaties for explicit operator signing and shows
  verified source versus reported imported revocation sequences.
- Python authority maintenance moved to `scripts/authority_ops`; demo setup and
  live propagation tests moved to sandbox. Rust gateway tools contain PowerShell
  packaging and a JavaScript signing check. Reference Python fixtures are isolated
  under gateway `tests/reference`.
- Each reference authority runs its own pinned-peer consumer. Active signed
  recognition is required; stale, forged, rollback and equivocal feeds fail closed.
- Native distribution includes gateway and operator binaries, checksums and docs.

## Validation

- 62 Rust tests including protocol interoperability, API isolation and feed health.
- Clippy with warnings denied; browser/Python canonical signing agreement.
- Four isolated reference maintenance tests, including restart high-water marks.
- Live canary accepted by three peers, then rejected by all after automatic import
  in 10.45–10.63 seconds. No manual feed import in this test.
- Native preflight passes both fleet authorities. Existing remote and anonymous
  identities fail delegation-window checks; renewal belongs to their operators.
- Windows binaries and Linux AMD64/ARM64 container builds; ARM64 operator smoke.

## Evidence boundaries

Matching sequence numbers are not a heartbeat or proof of enforcement. Full RFC
conformance, independent authority implementations and external adoption need
separate evidence. Demo memberships remain clearly labeled sample trust records.
Existing signed identities, keys and revocation history are preserved.
