# Deployment Scenarios

Genesis Mesh is easiest to understand when mapped to real operating models.
These examples are not separate products; they are common shapes for the same
trust, identity, authorization, and revocation model. Some use the peer mesh
between nodes; the cross-sovereign scenario needs only the Network Authorities
and verifiers.

## AI Agent Network

```{mermaid}
flowchart TB
    na["Network Authority"]
    supervisor["Supervisor Agent"]
    finance["Finance Agent"]
    crm["CRM Agent"]
    support["Support Agent"]
    policy["Signed Policy"]
    crl["Signed CRL"]

    na -->|join cert| supervisor
    na -->|join cert| finance
    na -->|join cert| crm
    na -->|join cert| support
    na -->|publishes| policy
    na -->|publishes| crl

    supervisor <-->|Noise XX + routes| finance
    supervisor <-->|Noise XX + routes| crm
    supervisor <-->|Noise XX + routes| support
```

Use this shape when autonomous or semi-autonomous agents need to communicate
without becoming anonymous processes on a flat network. Genesis Mesh gives each
agent a signed identity, assigns roles during enrollment, distributes policy,
and lets the operator revoke a compromised or retired agent identity.

## Edge Fleet

```{mermaid}
flowchart LR
    na["Network Authority"]
    factory_a["Factory A<br/>Edge Node"]
    factory_b["Factory B<br/>Edge Node"]
    factory_c["Factory C<br/>Edge Node"]
    control["Operations Control"]

    na -->|certs, policy, CRL| factory_a
    na -->|certs, policy, CRL| factory_b
    na -->|certs, policy, CRL| factory_c
    control -->|signed admin actions| na

    factory_a <-->|peer route| factory_b
    factory_b <-->|peer route| factory_c
    factory_a -. multi-hop DATA .-> factory_c
```

Use this shape when sites need authenticated peer communication across
locations but the organization still needs central admission, revocation, and
policy control. The Network Authority manages trust state; edge nodes use that
state to communicate directly.

From 1.7.0 the edge agent `genesis-mesh-edge` (beta) runs on each device. It
asks the Network Authority for decisions while it can reach it, acts under
pre-issued grants or records break-glass while it cannot, and uploads its
records in order when it reconnects. Revoking one of its certificates revokes
the whole node: its certificates, its executor key and its grants. See
{doc}`../operations/edge-agent`.

## Sovereign Organization

```{mermaid}
flowchart TB
    root["Root Sovereign"]
    genesis["Signed Genesis Block"]
    na["Network Authority"]
    hq["HQ Node"]
    branch_a["Branch A Node"]
    branch_b["Branch B Node"]
    branch_c["Branch C Node"]

    root -->|signs| genesis
    genesis -->|authorizes| na
    na -->|enrolls| hq
    na -->|enrolls| branch_a
    na -->|enrolls| branch_b
    na -->|enrolls| branch_c

    hq <-->|Noise XX| branch_a
    hq <-->|Noise XX| branch_b
    branch_b <-->|Noise XX| branch_c
```

Use this shape when a company, lab, public-sector team, or defense environment
must own its root of trust. Genesis Mesh keeps membership, policy, certificate
validity, and revocation under the operator's control instead of relying only
on a third-party network control plane.

## Cross-Sovereign Recognition

```{mermaid}
flowchart LR
    subgraph sa["Sovereign A"]
        na_a["Network Authority A"]
        agent["Agent or service"]
    end
    subgraph sb["Sovereign B"]
        na_b["Network Authority B"]
        treaty["Recognition treaty<br/>accepts A's attestations"]
        app["Relying application"]
    end

    na_a -->|signs attestation| agent
    na_b -->|signs| treaty
    agent -->|presents attestation| app
    app -->|verifies against| treaty
    na_a -.->|signed revocation feed| na_b
```

Use this shape when organizations each run their own sovereign and need to
recognize each other's members without merging into one network. Sovereign A
issues a membership attestation to its agent. Sovereign B signs a recognition
treaty that accepts A's attestations within a scope (roles, statuses,
validity). B's verifiers then check A's attestation through the treaty without
asking A, and import A's signed revocation feed to learn what A has revoked.
Recognition is directed: mutual recognition takes two treaties. Each side keeps
its own root key, policy and revocation. See
{doc}`../examples/recognition-treaties`, {doc}`../operators/recognition-playbook`
and {doc}`../examples/cross-sovereign-revocation`.

## Distributed Compute Cluster

```{mermaid}
flowchart LR
    na["Network Authority"]
    scheduler["Trusted Scheduler"]
    worker_a["Worker A"]
    worker_b["Worker B"]
    worker_c["Worker C"]

    na -->|role:service:scheduler cert| scheduler
    na -->|role:service:worker cert| worker_a
    na -->|role:service:worker cert| worker_b
    na -->|role:service:worker cert| worker_c

    scheduler -->|authorized work message| worker_a
    scheduler -->|authorized work message| worker_b
    worker_b -->|forwarded result| scheduler
    worker_c -. revoked identity rejected .-> scheduler
```

Use this shape when workers should accept tasks only from trusted identities.
Enrollment roles and policy constrain who can schedule work, while certificate
revocation removes workers or schedulers that should no longer participate.
