# Revocation

Revocation removes trust from an issued certificate before natural expiry.

```{mermaid}
sequenceDiagram
    participant O as Operator
    participant NA as Network Authority
    participant DB as SQLite
    participant N as Revoked Node
    participant P as Peer

    O->>NA: POST /admin/revoke with operator signature
    NA->>DB: Mark certificate revoked
    NA->>DB: Store signed CRL sequence N+1
    N->>NA: heartbeat or renew
    NA-->>N: 403 certificate revoked
    N->>P: new peer handshake
    P->>P: Check CRL
    P-->>N: Reject handshake
```

## Revoke a Certificate

Use the operator-authenticated `/admin/revoke` endpoint:

```json
{
  "cert_id": "<certificate-id>",
  "reason": "key_compromise"
}
```

The Network Authority:

1. Loads the issued certificate from SQLite.
2. Marks the certificate revoked.
3. Creates a new CRL with an incremented sequence.
4. Signs the CRL with the NA key.
5. Stores the active CRL.

## Reasons

| Reason | Effect |
|---|---|
| `key_compromise` | Revokes the certificate and blocks future joins with the same node public key. |
| `cessation_of_operation` | Revokes the certificate but allows future re-enrollment. |
| `superseded` | Revokes the certificate because it has been replaced. |
| `unspecified` | Revokes the certificate without a more specific reason. |

## Enforcement

The Network Authority rejects revoked certificates during heartbeat and renewal.
The peer runtime rejects revoked certificates during handshake validation.

## Operator Checklist

- Confirm the target `cert_id`.
- Choose the narrowest accurate revocation reason.
- Verify `/crl` returns the updated sequence.
- Verify the revoked node cannot heartbeat or renew.
- Verify peers reject new handshakes from the revoked certificate.
