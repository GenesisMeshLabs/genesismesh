# Trust Model

Genesis Mesh is a permissioned system. Trust starts with the genesis block and
flows through signed records. A sovereign's trust can also reach other
sovereigns: they recognize its Network Authority through signed treaties and
check what it signed offline.

```{mermaid}
flowchart TD
    rs["Root Sovereign"]
    genesis["Genesis Block"]
    history["NA Key History"]
    na["Network Authority"]
    operator["Operator Keys"]
    cert["Join Certificates"]
    crl["Certificate Revocation List"]
    policy["Policies and Decisions"]
    records["Attestations, Treaties, Evidence"]
    node["Mesh Nodes and Verifiers"]

    rs -->|signs| genesis
    rs -->|signs successions| history
    genesis -->|names first NA key| na
    history -->|names current NA key| na
    operator -->|admin signatures| na
    na -->|signs| cert
    na -->|signs| crl
    na -->|signs| policy
    na -->|signs| records
    node -->|trusts via genesis and key history| na
    node -->|validates| cert
    node -->|checks| crl
    node -->|verifies| records
```

## Trust Anchors

### Root Sovereign

The Root Sovereign is offline. Nodes and verifiers trust its public key
because it appears in the genesis block. The Root Sovereign signs the genesis
block and each key succession of the Network Authority, and is the authority
for high-impact trust changes. Keep its private key offline and off the NA
host (see {doc}`../operations/key-succession`, *The root key ceremony*).

### Network Authority

The Network Authority is online and operational. Its private key should stay
inside the NA process, a secret manager, or an HSM. It should not be used by
external admin clients. The records it signs are listed under
[Signed Objects](#signed-objects).

### Operator Keys

Operator keys authenticate administrative requests such as invite creation,
revocation, and policy publication. Operator public keys are set in the NA's
settings (`OPERATOR_PUBLIC_KEYS_JSON`), each with a tier, `read`, `standard`
or `privileged` (`OPERATOR_KEY_TIERS_JSON`); `genesis-mesh init` writes a
first key for local use. Operator private keys remain with administrators or
automated operations systems. An operator can switch a key off at once
(`genesis-mesh admin revoke-operator-key`). Operator keys never sign records;
they sign requests, and the NA signs the result.

## Signed Objects

| Record | Signed by |
| --- | --- |
| Genesis block | the Root Sovereign |
| Key succession record | the root key, the new NA key and the outgoing NA key |
| Join certificate | the NA, bound to a node public key |
| CRL | the NA; nodes check it before accepting peers |
| Policy manifest and boundary policy versions | the NA |
| Boundary decision and justification proof | the NA |
| Membership attestation | the NA, at an operator's request |
| Recognition treaty | the issuing (accepting) sovereign's NA |
| Sovereign revocation feed | the NA; lists revoked attestations, and revoked grants when grants are on |
| Trust evidence, data-usage policies and intents | the NA |
| Agreement offers and acceptances, consensus votes and proofs | each party or validator; the NA signs those it takes part in |
| Store anchor, retention checkpoint | the NA (evidence store, off by default) |
| Judgement, quarantine, registry and review entries | the NA (off by default) |
| Grant, time token, grant revocation | the NA (grants, off by default) |
| Audit pack manifest, archive record | the NA |
| Execution evidence, break-glass record, remediation, grant use | an executor key the NA registered |
| Observation | an observer key the NA registered |

What each of the evidence records is, and which setting turns it on, is in
{doc}`governed-changes`.

## Key succession

Since 1.5.0 the root key, kept offline, names the NA's next key in a signed
**key succession** record. The new key signs it to prove it is held, and the
NA countersigns it with its outgoing key. The genesis key and the successions
form the NA's **key history** (`GET /na/key-history`).

- Records signed by the old key keep verifying: a verifier that holds the
  root public key rebuilds the key history from it and checks each signature
  with the key that was valid at the record's own time.
- Mesh nodes follow the key history and check certificates, policies and CRLs
  with the key valid at each one's `issued_at`.
- The genesis block does not change, and `/sovereign.json` keeps naming the
  genesis key as the NA's identity.
- A compromised NA key is not covered: whoever holds a copy can still sign
  records dated inside its window, and a lost key cannot sign its own
  succession. Plan for a new identity.

See {doc}`../operations/key-succession`.

## Replay Protection

Node and admin requests include timestamps, nonces, and signatures. The Network
Authority stores each nonce under a scope: an admin nonce is single-use for
its operator key (`admin:<key_id>`) within the freshness window, on every
route. The admin signature also covers the method, path, query and the NA's
public key, so a request cannot be replayed against another route or NA.
