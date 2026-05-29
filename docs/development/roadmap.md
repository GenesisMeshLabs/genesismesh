# Roadmap

Genesis Mesh is in a production-hardening phase. The implementation has a real
cryptographic foundation and runtime path, but some hardening work remains.

## Implemented and Tested

- Ed25519 key generation, signing, and verification.
- Canonical JSON signing helpers.
- Signed genesis block model.
- Join certificate model.
- Invite-token-backed enrollment.
- SQLite persistence for Network Authority state.
- Operator-key admin authentication.
- Signed CRL endpoint and revocation enforcement for NA heartbeat/renewal.
- Noise XX handshake proof and peer runtime connection test.
- Gunicorn WSGI entry point.
- Sphinx/Furo/MyST documentation build.

## Remaining Hardening Work

- Multi-node integration tests.
- CRL gossip propagation verification.
- Route rejection from revoked senders.
- Signed peer announcements.
- Container build and fail-closed runtime verification.
- Dependency audit automation.
- Production backup and restore runbooks.
- Client-side policy signature verification.
