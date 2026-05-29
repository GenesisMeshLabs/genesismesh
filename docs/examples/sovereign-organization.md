# Example: Sovereign Organization

This example shows Genesis Mesh for an organization that wants to own the root
of trust for its internal node network.

```{mermaid}
flowchart TB
    root["Root Sovereign<br/>Offline"]
    genesis["Signed Genesis Block"]
    na["Network Authority"]
    hq["HQ Node<br/>role:anchor"]
    branch_a["Branch A<br/>role:branch"]
    branch_b["Branch B<br/>role:branch"]
    branch_c["Branch C<br/>role:branch"]

    root -->|signs| genesis
    genesis -->|authorizes| na
    na -->|invite + cert| hq
    na -->|invite + cert| branch_a
    na -->|invite + cert| branch_b
    na -->|invite + cert| branch_c

    hq <-->|Noise XX| branch_a
    hq <-->|Noise XX| branch_b
    branch_b <-->|Noise XX| branch_c
```

## Deployment Steps

1. Generate Root Sovereign and Network Authority keys.
2. Sign a genesis block that records the network name, NA public key, policy
   pointer, and bootstrap anchors.
3. Store the Root Sovereign private key offline.
4. Start the Network Authority with its private key and operator public keys.
5. Enroll HQ and branch nodes through invite tokens.

## Certificates Issued

Certificates bind each branch identity to its role and validity window:

| Node | Role |
|---|---|
| HQ | `role:anchor` |
| Branch A | `role:branch` |
| Branch B | `role:branch` |
| Branch C | `role:branch` |

## Routes Established

HQ can act as an anchor while branches exchange routes through authenticated
peer sessions. The Network Authority remains the control plane, not the data
path for every message.

## Revocation Drill

If Branch C's key is compromised:

1. Revoke the certificate with reason `key_compromise`.
2. Publish a new CRL.
3. Block future enrollment with the same node public key.
4. Generate a new node key, issue a new invite, and enroll Branch C again only
   after incident review.
