# Example: Distributed Compute Cluster

This example shows Genesis Mesh as a trust layer for distributed workers. The
goal is not to replace a scheduler; it is to ensure that schedulers and workers
are known, authorized, routeable, and revocable.

```{mermaid}
flowchart LR
    na["Network Authority"]
    scheduler["Scheduler\nrole:scheduler"]
    worker_a["Worker A\nrole:worker"]
    worker_b["Worker B\nrole:worker"]
    worker_c["Worker C\nrole:worker"]

    na -->|cert| scheduler
    na -->|cert| worker_a
    na -->|cert| worker_b
    na -->|cert| worker_c

    scheduler -->|authorized work message| worker_a
    scheduler -->|authorized work message| worker_b
    worker_b -->|result| scheduler
    worker_c -. revoked identity rejected .-> scheduler
```

## Deployment Steps

1. Create roles for schedulers and workers in policy.
2. Issue scheduler invites separately from worker invites.
3. Enroll each node and start the persistent runtime.
4. Allow workers to accept tasks only from authorized scheduler identities.
5. Monitor certificate expiry and renewal failures as operational signals.

## Certificates Issued

| Node | Role |
|---|---|
| Scheduler | `role:scheduler` |
| Worker A | `role:worker` |
| Worker B | `role:worker` |
| Worker C | `role:worker` |

## Routes Established

Workers do not need to be directly connected to every scheduler. Route
announcements let authenticated peers learn reachability through trusted next
hops.

## Revocation Drill

If Worker C behaves incorrectly:

1. Revoke Worker C's certificate.
2. Publish the updated CRL.
3. Schedulers reject messages and handshakes from Worker C.
4. Routes from Worker C are ignored or withdrawn.
5. Re-enroll only after deciding whether the old key is safe to reuse.
