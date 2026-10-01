# High availability (v0.60)

From v0.60 a Network Authority (NA) can run as several instances on one
PostgreSQL database (see {doc}`/operations/high-availability`). Usually a load balancer sits in front; the SDK then
needs only `baseUrl` pointing at it. Without a load balancer, give the SDK
every instance and it fails over itself.

```typescript
import { GenesisMeshClient, isRetryableConflict } from 'genesis-mesh-sdk';

const gm = new GenesisMeshClient({
  baseUrls: ['https://na-a.example', 'https://na-b.example'],
  signer: operatorSigner,
  retry: { attempts: 2, baseDelayMs: 200 },
});
```

## Failover rules

Requests go to one instance at a time.

- **Idempotent requests** (every GET, public verification and evidence
  submission) move to the next instance on a transport failure or
  502/503/504, then use `retry` with backoff.
- **Non-idempotent requests** (evaluate, issue, publish, revoke) move to the
  next instance only when the connection could not be made (refused,
  unresolvable, unreachable), because the request never reached the NA. After
  any other failure they are **not replayed**: a request that may have run
  must not run twice. The error reaches the caller, and the next request
  starts at another instance.
- The client stays on the instance that last answered.

`NetworkError.connectFailed` says whether a failure happened before the
request was sent.

## Readiness

```typescript
const r = await gm.health.readiness();
// { ready, status, instance, ha_mode, rate_limiter,
//   database: { backend, writable, schema_version, expected_schema_version, error? },
//   signing_key: { key_id, provider, fingerprint } }

for (const e of await gm.health.endpoints()) {
  console.log(e.base_url, e.reachable, e.ready, e.readiness?.signing_key.fingerprint);
}
```

`readiness()` returns a not-ready NA as `ready: false` with the failing checks
instead of throwing. `endpoints()` probes every configured instance directly.
It is meant for monitoring and for spotting an instance with a different key:
every instance of one NA reports the same fingerprint. `liveness()` and
`health()` wrap `/healthz` and `/health`.

## Conflicts between instances

Some operations are decided by the database across instances. The request
that loses a race gets `409` and changed nothing, so it can be retried:

| Code | Meaning |
|---|---|
| `boundary_policy_activation_conflict` | another version of the policy was activated at the same moment |
| `boundary_policy_version_conflict` | concurrent publishes of one policy kept taking the next version |
| `crl_publish_contention` | concurrent revocations kept taking the next CRL sequence |
| `retention_in_progress` | evidence retention is already running on another instance |

```typescript
try {
  await gm.policy.activate(policyId, version);
} catch (err) {
  if (isRetryableConflict(err)) await gm.policy.activate(policyId, version);
  else throw err;
}
```

Evidence submission is already safe to retry: an identical record returns
`status: 'duplicate'`.

## Testing against a cluster

In the `sdk-typescript` repository, `npm run test:e2e` also runs `tests/e2e-ha.test.ts` when
`GM_E2E_HA_DATABASE_URL` names an empty PostgreSQL database (C collation)
and nginx is installed. It starts two NA instances behind nginx with the
core's cluster harness. It kills one mid-run, then checks that a secret's
lifecycle continues through the load balancer and through `baseUrls`
failover, with one unbroken, verified history.
