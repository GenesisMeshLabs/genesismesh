# Security Policy

Genesis Mesh is a permissioned mesh network with cryptographic identity, signed
trust, and revocation. The security posture is intentional and bounded. This
document states what the project defends against, what it explicitly does not,
and how to report a vulnerability.

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security report.** Use the private
disclosure channel instead.

- Open a draft advisory at
  [github.com/GenesisMeshLabs/genesismesh/security/advisories/new](https://github.com/GenesisMeshLabs/genesismesh/security/advisories/new).
- Include: a description, reproduction steps, the version (`pip show
  genesis-mesh`), and any logs or proof-of-concept code.
- You should receive acknowledgement within **5 business days**.
- Expect a remediation plan within **30 days** for confirmed issues, longer for
  cryptographic findings that require a redesign.

Coordinated disclosure is preferred. If you publish before a fix exists,
please give the project a reasonable window first.

## Supported Versions

Only the latest minor release receives security fixes.

| Version | Status |
|---|---|
| `0.51.x` | Supported |
| `< 0.51` | Unsupported |

## In Scope: What Genesis Mesh Defends Against

Each defense is enforced in code today. Each item is testable against the live
deployment.

### Enrollment

- **Unauthenticated enrollment.** A node can only join with a single-use
  invite token that was signed into existence by an operator-authenticated
  `/admin/invite` call.
- **Token reuse.** Invite tokens are consumed atomically in the NA's SQLite
  database; a second `/join` with the same token returns 403.
- **Operator request forgery.** Every admin call (`/admin/invite`,
  `/admin/revoke`, …) is verified against an Ed25519 signature over a canonical
  JSON envelope with timestamp and nonce. Unknown operator key IDs, expired
  timestamps, or replayed nonces are rejected.
- **Privilege escalation via renewal.** Certificate renewal cannot extend
  beyond the original max-validity cap recorded on the issued cert.

### Identity and Transport

- **Cross-network certificate misuse.** Every join certificate is bound to a
  `network_name`. Peers reject certificates from a different network.
- **Certificate forgery.** Join certificates carry an Ed25519 signature from
  the Network Authority key; peers validate the signature against the
  `network_authority.public_key` field of the signed genesis block.
- **Unauthenticated peer connections.** All peer sessions use Noise XX with
  mutual authentication. The handshake fails if either side cannot present a
  valid join certificate, and the X25519 static key must derive from the
  Ed25519 key embedded in that certificate (key-binding check).
- **Passive eavesdropping.** Noise XX provides per-session ephemeral keys.
  Captured traffic from a past session cannot be decrypted by compromising the
  long-term key later (perfect forward secrecy).
- **Control-message replay.** The runtime maintains a replay cache of
  processed control-message IDs; duplicates are dropped.

### Revocation

- **Continued use of a revoked identity.** Revocation is enforced across
  multiple surfaces:
  - `/heartbeat` returns 403
  - `/renew` returns 403
  - Peer handshake is closed with an audit log entry
  - Route announcements from a revoked sender are ignored
- **Stale CRL propagation.** CRL versions are monotonic and signed. Nodes
  bootstrap the CRL from the NA on startup and refresh it via gossip; older
  CRL versions are not accepted.

### Operational

- **NA private key exposure.** The NA private key never leaves the NA
  process; admin callers use **operator keys**, not the NA key.
- **Reverse-proxy IP spoofing.** The NA trusts exactly one proxy hop via
  `ProxyFix(x_for=1)`, so `X-Forwarded-For` from arbitrary clients cannot
  forge `request.remote_addr`.

## Out of Scope: What Genesis Mesh Does NOT Defend Against

These are real risks. They are out of scope **by design**, by maturity stage,
or because they belong to a deeper layer of the stack. Operators must mitigate
them externally.

### Trust-root compromise

- **Root Sovereign key compromise.** If the Root Sovereign key leaks, the
  entire trust chain collapses. Mitigation is operational: keep this key
  offline, ideally on hardware.
- **Network Authority private key compromise.** A compromised NA key allows
  forging certificates for any identity. Mitigation: HSM or external secret
  manager, plus rotation.
- **Operator workstation compromise.** An attacker who steals an operator
  private key can issue invites and revoke certificates. Mitigation:
  workstation hygiene, hardware key, short-lived operator credentials.
- **Insider abuse by an authorized operator.** Genesis Mesh enforces what an
  operator is *cryptographically allowed* to do; it does not detect a
  legitimate operator acting maliciously.

### Network-layer attacks

- **Denial of service.** There is no rate-limiting on `/join`, `/heartbeat`,
  or peer connections beyond what the underlying transport provides. An
  attacker with sufficient bandwidth can exhaust the NA or a router. Mitigate
  with a CDN, WAF, or load balancer in front of the NA.
- **Traffic analysis.** Noise XX hides payload content; it does not hide that
  two peers are communicating, message timing, or message sizes.
- **Resource exhaustion via routing churn.** A compromised peer can announce
  many routes or churn them rapidly. Routing-table memory bounds are not
  enforced.

### Cryptographic boundaries

- **Quantum-cryptanalytic threats.** Ed25519 and X25519 are not
  post-quantum-secure. A future shift to a hybrid scheme is anticipated but
  not implemented.
- **Side-channel attacks.** Constant-time primitives come from PyNaCl;
  side-channel resistance of the Python wrapper has not been independently
  audited.
- **Clock skew.** Certificate expiry and admin-request timestamps assume the
  system clock is reasonably correct. Run NTP.

### Software-supply-chain

- **Transitive dependency compromise.** Direct dependencies are pinned in
  `pyproject.toml`. Transitive dependencies and the Python runtime itself are
  not independently audited. `pip-audit` runs in CI but only catches publicly
  known CVEs.
- **Build provenance.** Wheels published to PyPI are built by GitHub Actions
  via Trusted Publishing (OIDC). Reproducible builds are not currently
  verified.
- **VM/host compromise.** Compromising the host that runs the NA gives the
  attacker the NA private key. Mitigations are container hardening, systemd
  hardening (see `infrastructure/systemd/`), and an external secret manager.

### Application-level

- **Application-payload security.** `genesis-mesh send` transports arbitrary
  bytes. Authentication and authorization of *application messages* are the
  responsibility of the application, not the mesh.
- **Routing-layer integrity beyond signature checks.** Distance-vector
  protocols are vulnerable to malicious-but-authenticated route announcements;
  Genesis Mesh validates the signer's identity and rejects metric-0 claims,
  but does not detect a compromised authenticated router that lies about
  metric N.

## Hardening Resources

- [Trust model](https://genesismesh.connectorzzz.com/concepts/trust-model.html)
- [Security model](https://genesismesh.connectorzzz.com/concepts/security-model.html)
- [Certificate lifecycle](https://genesismesh.connectorzzz.com/concepts/certificate-lifecycle.html)
- [Revocation operations](https://genesismesh.connectorzzz.com/operations/revocation.html)
