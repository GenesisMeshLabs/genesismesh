# Security Model

Genesis Mesh is designed around explicit admission, short-lived credentials, and
revocation.

```{mermaid}
sequenceDiagram
    participant N as Node
    participant NA as Network Authority
    participant P as Peer

    N->>NA: POST /join with invite token and node signature
    NA->>NA: Validate invite, proof-of-possession, role policy, and key status
    NA-->>N: Signed join certificate
    N->>P: Noise XX handshake with join certificate payload
    P->>P: Verify NA signature, expiry, network, CRL, key binding
    P-->>N: Encrypted peer session accepted
```

## Admission

Nodes cannot join by sending only a public key. A node must present a valid
single-use invite token and a request signature from the corresponding node
private key. The Network Authority verifies proof-of-possession before consuming
the invite token, assigns roles from the invite, and ignores client-supplied
role claims.

## Peer Authentication

Persistent peers authenticate with Noise XX over WebSocket. The Noise handshake
exchanges join certificates as handshake payloads. After the cryptographic
handshake, the runtime validates:

- Network Authority signature on the certificate.
- Certificate expiry.
- Network name.
- CRL revocation state.
- Binding between the certificate Ed25519 key and the Noise X25519 static key.

## Peer Discovery

Peer discovery messages carry signed `PeerInfo` announcements. A received
announcement is accepted only when it includes a certificate ID, timestamp,
nonce, and signature. The runtime verifies the signature against the peer's join
certificate, derives roles from that certificate, rejects stale timestamps, and
tracks nonces to prevent replay.

## Administrative Authentication

Admin endpoints use operator keys, not the Network Authority private key.
Requests are signed over canonical JSON plus key ID, timestamp, and nonce. This
keeps the NA private key isolated inside the service.

## Revocation

The Network Authority publishes a signed CRL. Nodes reject revoked certificates
during handshakes, and the NA rejects heartbeat and renewal requests for revoked
certificates.

The NA also enforces certificate validity windows server-side. Expired
certificates cannot heartbeat or renew, and renewal validity cannot exceed the
maximum validity associated with the original invite policy.

## Deployment Boundary

The container startup path fails closed when required genesis and NA key files
are not mounted. Demo key generation is kept outside production startup.

## Current Gaps

Before production deployment, verify the open hardening items in
[](../development/roadmap.md), especially integration coverage, CRL gossip
propagation, route rejection for revoked senders, and container runtime checks.
