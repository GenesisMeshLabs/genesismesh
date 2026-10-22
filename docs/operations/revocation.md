# Revocation

Revocation removes trust from an issued certificate before natural expiry.

```{mermaid}
sequenceDiagram
    participant O as Operator
    participant NA as Network Authority
    participant DB as Database
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

Use the operator-authenticated `/admin/revoke` endpoint. It needs a
**privileged** operator key. From the CLI:

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise \
  --na https://na.example.org \
  --operator-key keys/ops.key --operator-key-id <privileged-key-id>
```

The request body:

```json
{
  "cert_id": "<certificate-id>",
  "reason": "key_compromise"
}
```

The Network Authority:

1. Loads the issued certificate from the database.
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

## Edge nodes

Since 1.7, revoking any certificate of an edge node revokes the node as a
whole: every certificate it holds, in one CRL; its executor key is retired;
and the grants that key bears are revoked. The response has an `edge_node`
block that lists what was done. See {doc}`edge-agent`, *Revoking a device*.

## Enforcement

The Network Authority rejects revoked certificates during heartbeat and renewal.
The peer runtime rejects revoked certificates during handshake validation.

## Operator Checklist

- Confirm the target `cert_id`.
- Choose the narrowest accurate revocation reason.
- Verify `/crl` returns the updated sequence.
- Verify the revoked node cannot heartbeat or renew.
- Verify peers reject new handshakes from the revoked certificate.

## Other revocations

Certificates are one kind of trust material. The others are revoked
elsewhere:

| What | How | Where it propagates |
| --- | --- | --- |
| A membership attestation | `genesis-mesh attestation revoke` | Through this NA's revocation feed, when partners next import it |
| A recognition treaty | `genesis-mesh treaty revoke <treaty-id> --na ... --reason ...` | At this NA at once |
| An operator key | `genesis-mesh admin revoke-operator-key` ({doc}`incident-response`) | At this NA at once; terminal |
| A pre-issued grant (with `EVIDENCE_GRANTS=on`) | `POST /admin/grants/<grant_id>/revoke` ({doc}`grants`) | Through the revocation feed, at the holder's next sync |
| A partner's revocations | `genesis-mesh treaty import-feed` on a schedule | Within your import interval |

A revocation made at a partner reaches you only when you import its feed, so
the import interval is the propagation window.
