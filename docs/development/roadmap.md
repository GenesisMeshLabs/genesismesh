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

## Completed Hardening Work

- Multi-node integration tests cover authenticated runtime connections and
  routed data through an intermediate peer.
- CRL gossip tests cover newer CRL acceptance, sequence announcements, update
  requests, and sending newer local CRLs to peers.
- Route handling rejects revoked senders, metric-zero gossip routes, stale
  sequences, and invalid withdrawals.
- Peer discovery verifies signed announcements, rejects unsigned/stale/replayed
  announcements, caps response size, and derives roles from verified
  certificates.
- Container checks build the image and verify fail-closed startup when required
  Network Authority secrets are missing.
- CI runs dependency auditing with `pip-audit`.
- Backup and restore operations are documented in
  `operations/backup-restore.md`.
- Client-side policy verification rejects policy manifests not signed by the
  Network Authority key.
- Browser probes of peer WebSocket ports are verified to return upgrade errors
  without noisy traceback logs.
- Optional bootstrap failures, including HTTP 404 and timeout cases, are logged
  with endpoint context and do not block runtime startup.
- Invalid Noise/certificate key binding failures are sanitized and do not expose
  certificate payloads.
- Persistent runtime cancellation and runtime shutdown stop certificate
  management, CRL gossip, peer discovery, routing protocol, routing table
  maintenance, and the WebSocket server.
- `genesis-mesh dev down` reports locked generated state with remediation
  guidance.
- Local certificates rejected by a wiped or reset Network Authority fail with a
  clean re-enrollment message.
- Running two Network Authority processes against the same SQLite database is
  documented as unsupported.
- Readiness and CLI status output expose the configured DB path.
- Invalid admin signatures, replayed admin nonces, revoked heartbeat, revoked
  renewal, and invalid node signatures create sanitized audit events without
  signed request bodies or invite token secrets.
