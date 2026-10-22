# Rust SDK: pre-issued grants

> **Beta:** a Git dependency, not on crates.io, and not yet part of the
> cross-language interoperability run. Crate: `genesis-mesh-sdk` 1.7.0.

A grant (1.6.0) is an authorisation the Network Authority (NA) signs in
advance, so a device can make a known, bounded kind of change while it cannot
reach the NA. Break-glass records a change and has it judged afterwards; a
grant authorises it beforehand. When the NA issues a grant, it checks that
every policy that applies allows every request the grant permits.

The NA issues grants only with `EVIDENCE_GRANTS=on`, which is **off by
default**; until then every grant route answers `404 grants_disabled`. It
needs `EVIDENCE_OUT_OF_BAND=on`, which needs `EVIDENCE_STORE=on`; both are off
by default too. On the device, `GrantHolder::act` needs a record outbox
(`ClientOptions::with_record_outbox`, see {doc}`governance`;
`RecordOutboxRequired` otherwise). The grant routes are beta; the signed records are
stable. The rules in full, and the limits of offline trust, are in
{doc}`/operations/grants`.

`client.grants` (`GrantClient`) calls the grant routes, and `GrantHolder`
acts within one grant on the device. Of the SDKs, only the TypeScript and
Rust SDKs (and the edge agent, which uses this crate) have grant holders.

---

## Issuing and revoking

`grants.issue` (privileged) names one bearer (a registered executor key), the
capabilities, the basis (`attestation_id` or `agreement`), a validity of at
most 24 hours, a budget (`max_uses`), the uses one time token may anchor
(`max_uses_per_time_token`) and a closed `parameter_envelope`:

```rust
use genesis_mesh_sdk::{json, ExecutionRecorder, GenesisMeshClient, Value};

async fn issue(
    admin: &GenesisMeshClient,
    recorder: &ExecutionRecorder,
    attestation_id: &str,
    valid_until: &str, // RFC 3339, at most 24 hours ahead
) -> genesis_mesh_sdk::Result<Value> {
    admin
        .grants
        .issue(json!({
            "bearer_key_id": recorder.key_id(),
            "capabilities": ["secret.manage"],
            "attestation_id": attestation_id,
            "valid_until": valid_until,
            "max_uses": 3,
            "max_uses_per_time_token": 2,
            "parameter_envelope": {
                "lifetime_days": {"number_range": {
                    "number_type": "integer", "minimum": 1, "maximum": 60}},
            },
        }))
        .await
}
```

Each envelope parameter is `one_of` a set of scalars, `subset_of` a set of
strings, or a `number_range` (`integer` or `number`, inclusive or exclusive
bounds). The NA answers with the signed grant and its first time token, or
refuses naming the first problem (`grants::ISSUANCE_REFUSALS`; for example
`grant_gate_may_deny`, HTTP 422 and so `GenesisMeshError::Validation`, when
a value inside the envelope may be denied). `err.code()` gives the code.

`grants.list`, `grants.get` and `grants.uses` (read) read grants and a
grant's use chain; `grants.revoke` (privileged) revokes one. A use made
before a revocation stands; one at or after it is refused.

---

## Acting within a grant

A `GrantHolder` holds one grant for the device whose `ExecutionRecorder`
signs with the bearer key. Create it from what `issue` returned, then call
`act`:

```rust
use genesis_mesh_sdk::{
    json, ActionError, ActionReport, ExecutionRecorder, GenesisMeshClient, GovernedVerification,
    GrantActionOutcome, GrantFallback, GrantHolder, GrantRequest, Value,
};

fn hold(
    issued: &Value,
    recorder: ExecutionRecorder,
    na_public_key: String,
) -> genesis_mesh_sdk::Result<GrantHolder> {
    GrantHolder::from_issued(issued, recorder, vec![na_public_key])
}

async fn rotate(
    gm: &GenesisMeshClient,
    holder: &mut GrantHolder,
    na_public_key: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let verify = GovernedVerification {
        operator_public_keys: vec![na_public_key],
        ..Default::default()
    };
    let request = GrantRequest::new("secret.manage", json!({"lifetime_days": 30}))
        .on("kv:site-7/api-key", "rotate")
        .with_fallback(GrantFallback::new("the credential must rotate now", verify));
    match holder
        .act(gm, request, |_authority| async move {
            Ok::<_, ActionError>(ActionReport::<()> {
                execution_parameters: Some(json!({"version_id": "v9"})),
                ..ActionReport::default()
            })
        })
        .await?
    {
        GrantActionOutcome::Used(used) => eprintln!("use {}", used.record["use_sequence"]),
        GrantActionOutcome::FellBack { unusable, .. } => eprintln!("fell back: {}", unusable.code),
    }
    // Persist the holder after every use: `holder.state()`, `GrantHolder::restore`.
    Ok(())
}
```

`GrantHolder::new` (or `from_issued`) checks that the grant and its time
token verify under the NA keys and name this recorder's key as the bearer.
`act` then checks each use offline, in the NA's order: the bearer key's
resource prefix (`set_resource_prefix`), the capability, the envelope
(`grants::envelope_problem`: closed, numbers compared exactly, `true` is not
`1`), revocation (the feed the holder last read), the validity, the budget,
and the uses allowed per time token. It then runs the action, signs a use
chained to the previous one and citing the time token, keeps it in the record
outbox and submits it.

- A request the grant does not cover (`grant_use_out_of_scope`,
  `grant_capability_mismatch`, `grant_envelope_mismatch`), a grant not valid
  yet, and secret material in the parameters are refused before anything runs
  (`GrantRefused`, or `OutOfBandRecord` with `grant_use_secret_material`).
- Metadata the secret guard refuses after the action ran is left out of the
  use and named in `dropped`; a failed action is recorded as a use with
  outcome `failure` (`ActionFailed`).
- Keep `holder.state()` (`GrantHolderState`, serde-serializable) durably and
  rebuild the holder with `GrantHolder::restore`. A holder that forgets its
  uses signs a second use at a position it already used, which the NA
  refuses.

---

## Reconnecting and the fallback

On reconnecting, `holder.sync(&gm)` reads and verifies the revocation feed,
uploads the record outbox (the grant's uses one at a time in chain order,
before observations) and asks for a new time token naming the head of the
holder's chain. A use the NA refuses for good is a dead letter
(`GRANT_USE_PERMANENT_REFUSALS`); the NA keeps it as a quarantine entry and it
still takes its place in the chain. An earlier use not uploaded yet
(`grant_use_chain_gap`) and a use dated ahead of the NA's clock
(`grant_use_in_future`) are retried.

When the grant has ended, its budget or time token is spent, it is revoked or
its bearer key is retired, `act` falls back with the request's
`GrantFallback` to `governed_action_with_break_glass` with the grant's
capability: the NA's decision when it answers (a DENY does not run the
action), break-glass when it does not. Without a fallback the request is
refused (`GrantRefused` with the reason). A grant on an agreement needs
`GrantFallback::evaluate`.

---

## Verifying grants

`verify::verify_evidence_events`, `verify::verify_record` and
`audit_pack::verify_audit_pack` check the grant entry kinds (`grant`,
`grant_execution`, `grant_revocation`) and time tokens: each signature, the
store's grant rules (`grant_use_chain_break`, `grant_missing`,
`grant_bearer_mismatch`, `grant_use_out_of_scope` and others), the use rules
with the NA's codes (`grants::use_problem`), and the revocation feed
(`verify::verify_revocation_feed`). Turn grants on only once every verifier
that reads your exports, packs and feed runs 1.6 or later: a 1.5 verifier
refuses the new kinds. See {doc}`verification`.
