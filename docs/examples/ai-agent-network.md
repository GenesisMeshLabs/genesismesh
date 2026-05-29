# Example: AI Agent Network

This example shows Genesis Mesh as a trust fabric for internal AI agents that
must prove identity before exchanging tasks or data.

```{mermaid}
flowchart TB
    na["Network Authority"]
    supervisor["Supervisor Agent\nrole:supervisor"]
    finance["Finance Agent\nrole:finance"]
    crm["CRM Agent\nrole:crm"]
    support["Support Agent\nrole:support"]

    na -->|invite + cert| supervisor
    na -->|invite + cert| finance
    na -->|invite + cert| crm
    na -->|invite + cert| support

    supervisor <-->|Noise XX + routes| finance
    supervisor <-->|Noise XX + routes| crm
    supervisor <-->|Noise XX + routes| support
```

## Deployment Steps

1. Create a signed genesis block for the agent network.
2. Start the Network Authority with operator keys and durable state.
3. Issue one invite per agent role.
4. Enroll each agent node with its invite token.
5. Start persistent node runtimes so agents can authenticate peers and exchange
   routes.

## Certificates Issued

The Network Authority issues short-lived join certificates:

| Agent | Role | Validity |
|---|---|---|
| Supervisor | `role:supervisor` | Operator-defined |
| Finance | `role:finance` | Operator-defined |
| CRM | `role:crm` | Operator-defined |
| Support | `role:support` | Operator-defined |

Roles come from invite tokens, not client-supplied claims.

## Routes Established

After Noise XX handshakes, agents announce reachable peers. The supervisor can
route to individual agents, and agents can communicate through authenticated
next hops when topology allows it.

## Revocation Drill

If the CRM agent is compromised:

1. Revoke the CRM certificate with `/admin/revoke`.
2. Publish the updated signed CRL.
3. Peers reject new handshakes from the revoked certificate.
4. Existing routes from the revoked identity are withdrawn or ignored.
5. Re-enroll only after issuing a new invite and reviewing the key-compromise
   reason.
