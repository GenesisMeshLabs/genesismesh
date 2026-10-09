# Governed SDK actions

`governedAction` composes evaluation, offline verification, a caller-supplied
callback and signed execution evidence. It does not implement cloud operations.
The NA needs evidence storage enabled, active policies, a privileged operator
for setup and a registered executor key. To run one locally, see
{doc}`../local-network-authority`. Give the client an evidence outbox so no
signed record is lost when the NA is unreachable after an action.

```typescript
import { FileOutbox, GenesisMeshClient, ExecutionRecorder, governedAction, seedSigner } from 'genesis-mesh-sdk';

const gm = new GenesisMeshClient({
  baseUrl,
  signer: operatorSigner,
  outbox: new FileOutbox('/var/lib/controller/gm-outbox'),
});
const recorder = new ExecutionRecorder({
  executorSovereignId: 'executor',
  signer: seedSigner(executorSeedBase64, 'executor-key'),
});

const result = await governedAction(gm, recorder, {
  attestation_id: attestation.attestation_id,
  requested_capability: 'secret.rotate',
  context: {
    request_parameters: { app_id: 'app-1', lifetime_days: 30 },
    attributes: { owner: 'team-a', secret_store: 'approved-store' },
  },
  resource_id: 'store:example/resource-1',
  resource_action: 'rotate',
  verify: {
    operatorPublicKeys: [trustedNaPublicKey],
    expectedPolicies: [policy],
    expectedAttestation: attestation,
  },
}, async () => ({ execution_parameters: { secret_version: 'version-2' } }));
```

Use a trusted NA public key. `verify` and explicit `expectedPolicies` are
required. An empty policy list explicitly requires an empty policy binding.
An ALLOW under an attestation also requires `expectedAttestation`. Agreement
requests use `agreement` instead of `attestation_id` and check the agreement ID.
The helper supplies a context ID when absent and checks the response against it.
It checks expiry using the current clock, including after the resource-head
lookup. Historical `now` overrides are only available on the standalone verifier.

A verified DENY returns `authorized: false` without invoking the callback or
submitting execution evidence. Invalid, unsigned, expired or mismatched decisions
throw `DecisionVerificationError`. `summarizeDecision` separates observe-mode
failures from enforced failures and lists the applied policies.

A successful callback can return `value` for its caller, independently of the
metadata in `execution_parameters`. Only metadata enters the evidence record.
A callback exception produces failure evidence with a fixed, non-sensitive
description, then rethrows the original exception. If that failure record
cannot be signed or submitted (or, with an outbox, kept), `GovernedActionError`
preserves both errors and the signed record as `evidence` when there is one.

Without an outbox, an evidence submission that fails after the callback has
run throws the submission error, and the signed record is not kept: do not
automatically rerun the callback on such an error.

## Evidence outbox

Since 1.2.0 a client can keep signed evidence in an outbox
(`ClientOptions.outbox`): `governedAction` writes each record there before
submitting it and removes it once the NA admits it. The outbox is storage the
caller supplies. `FileOutbox` keeps one JSON file per record in a directory,
written to a temporary file, synced and renamed into place; it reads the
directory once and then keeps it in memory, so one process uses a directory at
a time. A directory it creates is `0700` and its files `0600` on POSIX; on
Windows, or for a directory that already exists, restrict access to it
yourself. Implement `EvidenceOutbox` (`add`, `update`, `remove`, `list` in the
order added) to keep records in a database instead. The outbox holds signed
metadata, never secret values, but it must be durable and private: a record
lost from it is evidence lost. `MemoryOutbox` keeps nothing across restarts
and is for tests only.

With an outbox, a failed submission never throws. The result's `submission` is
the NA's acknowledgement when it admitted the record; otherwise `queued` is the
outbox entry:

| Result | Meaning |
|---|---|
| `submission` (`recorded`, `duplicate`) | The NA holds the record; it is no longer in the outbox. |
| `queued.state: 'pending'` | Not admitted yet: the NA was unreachable, timed out, or answered `5xx`, `429`, or any refusal a later attempt can overcome (an executor key not registered yet, a gap behind a record not admitted yet, a disabled store, a proxy's error page). `flushPending` retries it. |
| `queued.state: 'dead_letter'` | Refused for good: the NA's `evidence_malformed`, `invalid_evidence`, `evidence_invalid_signature`, a decision denied, mismatched or out of its window, a chain mismatch or `evidence_conflict`, or the SDK's `evidence_secret_material`; or a record it chains from was refused (`evidence_predecessor_dead_lettered`). `queued.last_error` holds the status and code. Kept in the outbox, never dropped. |

`gm.evidenceStore.flushPending()` submits pending records in the order they were
added. Run it at startup and on a timer. A record waits while one it chains
from is pending. A failed record is retried after 5 s, doubling up to 15
minutes; `{ ignoreBackoff: true }` retries at once. A transient error ends the
run. The result lists the records admitted, still pending and newly
dead-lettered.

A governed action on a resource with pending records chains from the newest of
them, not from the NA's head, and submits them first, oldest first and despite
their backoff, since the NA has just answered the evaluation (up to 100; older
ones wait for `flushPending`). Passing `prior_resource` overrides this. Records
signed outside `governedAction` go through the same path with
`gm.evidenceStore.enqueue(evidence)`, which also resubmits a record already in
the outbox.

With an outbox, two errors mean the action ran; neither should make the caller
run it again:

- `MetadataRefusedError` (`governed_action_metadata_refused`): the secret
  guard refused metadata the callback reported. The outcome is recorded with
  the accepted parameters; the refused ones are dropped and named in
  `outcome_detail` (`[secret guard dropped: client_secret]`) and in `dropped`.
  The error carries `value`, `evidence` and `submission` or `queued`; `cause`
  is the guard's `SecretMaterialError`. Without an outbox, the guard refuses
  the metadata before anything is signed and throws `SecretMaterialError`, as
  before 1.2.0.
- `EvidenceNotKeptError` (`governed_action_evidence_unkept`): the evidence
  could not be signed or the outbox failed. It carries `value` and the signed
  `evidence` when there is one: pass it to `enqueue` once the outbox works
  (resubmission is idempotent).

An action fails and its failure record cannot be submitted: with an outbox the
record is kept pending and the action's error is rethrown.

The outbox protects what happens after the record is signed. A crash during
the action itself leaves no record of its outcome; reconcile the resource (see
below) after a crash.

Evaluation context and submitted execution metadata are checked before HTTP
requests. The recorder also checks metadata before signing. These checks reject
obvious secret field names, PEM blocks, token-like strings and oversized metadata;
they cannot identify every possible secret. Supply identifiers, versions and
timestamps only. Do not put credentials in resource identifiers either.

The helper reads the resource head (with an outbox, the newest pending record,
else the NA's) unless `prior_resource` is supplied. An explicit `null` asserts
that there is no history. Identical evidence submissions are idempotent.
Concurrent operations on one resource can conflict; serialize them at the
caller. Two controllers with separate outboxes that both change one resource
while the NA is away fork its chain: the record that loses is dead-lettered
with `evidence_conflict` when it is flushed. Have one controller own each
resource.

## Reconciliation

`gm.evidenceStore.resourceStates()` returns the latest recorded state and retains
the last successful metadata when a later action fails. Pass it with an observed
inventory to `reconcileResources` to identify `unmanaged`, `drifted`, `missing`,
`present_after_revoke` and `in_sync` resources. No scanning or remediation is
performed by the SDK.

Missing inventory entries only mean missing resources when `completeInventory`
is true. `scopePrefix` limits these inferred missing-resource findings. Supply
`versionKey` when versions use a field other than `secret_version`. Resources
with no successful records remaining after retention cannot have their full
state reconstructed from checkpoint digests alone.
