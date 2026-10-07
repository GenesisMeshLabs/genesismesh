# Governed SDK actions

`governedAction` composes evaluation, offline verification, a caller-supplied
callback and signed execution evidence. It does not implement cloud operations.
The NA needs evidence storage enabled, active policies, a privileged operator
for setup and a registered executor key. To run one locally, see
{doc}`../local-network-authority`.

```typescript
import { GenesisMeshClient, ExecutionRecorder, governedAction, seedSigner } from 'genesis-mesh-sdk';

const gm = new GenesisMeshClient({ baseUrl, signer: operatorSigner });
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
description, then rethrows the original exception. If recording that failure
also fails, `GovernedActionError` preserves both errors.

Evaluation context and submitted execution metadata are checked before HTTP
requests. The recorder also checks metadata before signing. These checks reject
obvious secret field names, PEM blocks, token-like strings and oversized metadata;
they cannot identify every possible secret. Supply identifiers, versions and
timestamps only. Do not put credentials in resource identifiers either.

The helper reads the resource head unless `prior_resource` is supplied. An
explicit `null` asserts that there is no history. Identical evidence submissions
are idempotent. Concurrent operations on one resource can conflict; serialize
those operations at the caller. Evidence errors can occur after the callback
has run, so do not automatically rerun the callback on a submission error.

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
