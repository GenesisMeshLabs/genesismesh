# Certificate Lifecycle

Nodes use short-lived join certificates issued by the Network Authority.

```{mermaid}
stateDiagram-v2
    [*] --> Invited
    Invited --> Issued: join with valid invite
    Issued --> Renewed: renewal accepted
    Renewed --> Renewed: renewal accepted
    Issued --> Expired: validity window passes
    Renewed --> Expired: validity window passes
    Issued --> Revoked: operator revokes cert
    Renewed --> Revoked: operator revokes cert
    Revoked --> BlockedKey: reason is key_compromise
    Revoked --> Invited: non-compromise re-enrollment
    Expired --> Invited: new invite
```

## Enrollment

1. An operator creates an invite token with allowed roles and maximum validity.
2. The node generates or loads its Ed25519 keypair.
3. The node submits its public key, invite token, requested validity, and a
   signature proving possession of the node private key.
4. The Network Authority validates the invite, node proof-of-possession, and
   validity cap, then issues a signed certificate.
5. The invite token is marked used atomically with certificate issuance.

## Renewal

Nodes can renew certificates before expiry. The Network Authority verifies:

- the original certificate exists
- the requester proves possession of the same node private key
- the certificate is still inside its validity window
- the certificate is not revoked
- roles are preserved from server-side state
- requested validity does not exceed the original invite's maximum validity

Renewal creates a new certificate while preserving the node identity and role
set. If a node asks for a longer renewal than allowed, the Network Authority
caps the renewed certificate to the stored maximum validity. The predecessor
stays usable for `RENEWAL_GRACE_SECONDS` (default 900), then the NA revokes it
and lists it in the CRL.

## Revocation

Operators revoke certificates through `/admin/revoke`, which needs a
`privileged` operator key. Revocation creates a new signed CRL version and
marks the certificate revoked in persistent state.

Revocation reasons matter:

- `key_compromise` blocks future joins using the same node public key.
- `cessation_of_operation`, `superseded`, and `unspecified` revoke the current
  certificate without permanently blocking that public key from re-enrollment.

Edge nodes (beta, 1.7.0): revoking one of an edge node's certificates revokes
the node. Every certificate it holds goes into one CRL, its executor key is
retired, and the grants that key bears are revoked. From then on its
heartbeats and renewals are refused (`403 edge_node_retired`). The
attestations issued to its sovereign ID are not revoked; revoke them
separately. See {doc}`../operations/edge-agent`.

## Expiry

Expired certificates fail peer validation and are rejected by the Network
Authority for heartbeat and renewal. Nodes should renew before expiry and should
treat renewal failures as operationally significant. Once a certificate expires,
the node needs a new invite and enrollment flow unless the operator provides a
different re-enrollment policy.

## Key Succession

When the NA's key is succeeded (1.5.0), certificates it issued before keep
verifying: nodes follow the NA's key history and check each certificate and
CRL with the NA key that was valid at its `issued_at`. See
{doc}`../operations/key-succession`.
