# Trust Model

Genesis Mesh is a permissioned system. Trust starts with the genesis block and
flows through signed operational objects.

```{mermaid}
flowchart TD
    rs["Root Sovereign"]
    genesis["Genesis Block"]
    na["Network Authority"]
    operator["Operator Keys"]
    cert["Join Certificates"]
    crl["Certificate Revocation List"]
    policy["Policy Manifest"]
    node["Mesh Nodes"]

    rs -->|signs| genesis
    genesis -->|authorizes| na
    genesis -->|lists or references| operator
    operator -->|admin signatures| na
    na -->|signs| cert
    na -->|signs| crl
    na -->|signs| policy
    node -->|trusts via genesis| na
    node -->|validates| cert
    node -->|checks| crl
    node -->|applies| policy
```

## Trust Anchors

### Root Sovereign

The Root Sovereign is offline. Nodes trust its public key because it appears in
the genesis block. The Root Sovereign signs the genesis block and is the
authority for high-impact trust changes.

### Network Authority

The Network Authority is online and operational. It signs:

- join certificates
- certificate revocation lists
- policy manifests

The Network Authority private key should stay inside the NA process, a secret
manager, or an HSM. It should not be used by external admin clients.

### Operator Keys

Operator keys authenticate administrative requests such as invite creation,
revocation, and policy publication. Operator public keys are configured in
genesis or policy; operator private keys remain with administrators or automated
operations systems.

## Signed Objects

- **Genesis block**: signed by the Root Sovereign.
- **Join certificate**: signed by the Network Authority and bound to a node
  public key.
- **CRL**: signed by the Network Authority and consumed by nodes before
  accepting peers.
- **Policy manifest**: signed by the Network Authority and used to describe
  operational constraints.

## Replay Protection

Node and admin requests include timestamps, nonces, and signatures. The Network
Authority persists nonces by scope so a nonce accepted for one key or request
class cannot be replayed in another context.
