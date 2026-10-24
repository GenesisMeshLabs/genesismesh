# Rust SDK: offline verification

> **Beta:** a Git dependency, not on crates.io, and not yet part of the
> cross-language interoperability run. Crate: `genesis-mesh-sdk` 1.7.0.

The Rust SDK ({doc}`sdk`) verifies what the Network Authority (NA) signs
without calling it: decisions, evidence exports, single records, the NA's key
history, store anchors and audit packs. These modules need no private key and
no network, and they work without the `client` feature
(`default-features = false`). They port the Python reference with the same
reason codes, and are tested against vectors the Python core produces. They
are separate code from the same project, so a difference from the Python
reference is a bug in one of them.

The SDK verifies what it is given; it fetches only some of it. It has no
client call for the NA key history (`GET /na/key-history`, public), store
anchors (`GET /admin/evidence/anchors`, read tier) or audit packs
(`POST /admin/evidence/audit-pack`, read tier). Fetch those with
`HttpTransport` ({doc}`sdk`), or with the `genesis-mesh` CLI
(`na succession history`, `evidence anchors fetch`, `audit pack`). Evidence
exports come from `evidence_store.export_text` or `export_all` (read tier).

| Module | Verifies |
|---|---|
| `verify` | Decisions, evidence exports, single records, store anchors, join certificates and CRLs |
| `key_history` | The NA's key history: which NA key was valid when |
| `audit_pack` | Audit packs, as `genesis-mesh audit verify` does |
| `canonical` | The signed forms and digests of every record kind |

---

## Decisions

`verify::verify_boundary_decision` checks a decision's signature, expiry,
context and bindings. Before acting on a decision (as `governed_action`
does), judge it as of now:

```rust
use genesis_mesh_sdk::verify::{verify_boundary_decision, VerifyDecisionOptions};
use genesis_mesh_sdk::Value;

fn decision_now(decision: &Value, na_public_key: String, policy: Value) -> bool {
    let check = verify_boundary_decision(
        decision,
        &VerifyDecisionOptions {
            operator_public_keys: vec![na_public_key],
            expected_policies: Some(vec![policy]),
            ..Default::default()
        },
    );
    if !check.accepted {
        eprintln!("not accepted: {}", check.reason);
    }
    check.accepted && check.authorized
}
```

`accepted` says the decision is authentic, unexpired and bound as expected;
`authorized` says it allows the action. To audit an archived decision, set
`at_record_time: true` (1.5.0): it is then judged as of its own
`decision_made_at`, so it still verifies years later. It is off by default,
because a decision about to be acted on must be judged as of now.

---

## Key history

The NA's signing key can change by succession. `GET /na/key-history` returns
the genesis block and the succession records; `key_history::verify_key_history`
checks them from the root public key **you** hold (each succession is signed
by the root key, the new key and the outgoing key) and returns the
`NaKeyHistory`:

```rust
use genesis_mesh_sdk::key_history::{verify_key_history, NaKeyHistory};
use genesis_mesh_sdk::verify::{verify_boundary_decision, VerifyDecisionOptions};
use genesis_mesh_sdk::Value;

fn key_history(view: &Value, root_public_key: &str) -> Option<NaKeyHistory> {
    let successions = view["successions"].as_array().cloned().unwrap_or_default();
    let checked = verify_key_history(&view["genesis"], &successions, Some(root_public_key));
    for failure in &checked.failures {
        eprintln!("{failure:?}");
    }
    checked.history
}

fn decision_archived(decision: &Value, history: NaKeyHistory) -> bool {
    verify_boundary_decision(
        decision,
        &VerifyDecisionOptions {
            at_record_time: true,
            key_history: Some(history),
            ..Default::default()
        },
    )
    .accepted
}
```

With a key history, `VerifyDecisionOptions::key_history`,
`VerifyEvidenceOptions::key_history` and `VerifyRecordOptions::key_history`
accept an NA signature only by the key valid at the record's own time
(`na_key_not_valid_at_time` otherwise), with a 300-second hand-over. Without
one, every key given is valid at every time. The keys the history yields
prove nothing unless you got the root key some other way. See
{doc}`/operations/key-succession`.

### The vouching horizon (1.8.1)

Judged for the present, a record of a key that has ended vouches only until
that key's end, the 300-second hand-over and a grace of at most 24 hours
(`SUCCESSION_VOUCHING_GRACE_SECONDS`); the NA re-issues what is still valid
under the new key. Judged at its own time, a record is unchanged.

- `NaKeyHistory::record_outlives_key` and `keys_vouching_at`, given the
  grace; `NaKeys::vouching_at` for both kinds of keys.
  `key_history::vouching_grace` turns the NA's published
  `vouching_grace_seconds` into the grace (it only shortens).
- `verify_record_for_present(kind, record, options, now, grace)`: with the
  key history, an attestation or a grant of a key past its horizon is
  `outlives_key`. `verify_record` and `genesis-mesh-verify` judge records
  at their own time.
- `vouching::na_record_refusal`: the reference's verdict on an attestation,
  treaty, revocation feed or grant, pinned by the shared `vouching` suite.
- `GrantHolder` takes the key history (`impl Into<NaKeys>`): the grant is
  judged now, and revocation feeds are ordered by their signer's key, then
  by `sequence`. `GrantHolder::with_vouching_grace` shortens its grace.

---

## Evidence exports and records

`verify::parse_export_lines` reads a JSON Lines export, and
`verify::verify_evidence_events` checks the store chain, envelopes, every
signature, the decision and resource chains, retention checkpoints and every
later entry kind (observations, break-glass, judgements, quarantine,
remediation records, reviews, key successions, archives and grants):

```rust
use genesis_mesh_sdk::verify::{parse_export_lines, verify_evidence_events, VerifyEvidenceOptions};
use genesis_mesh_sdk::Value;

fn export(text: &str, na_public_key: String, executor_keys: Vec<Value>) -> genesis_mesh_sdk::Result<bool> {
    let events = parse_export_lines(text)?;
    let result = verify_evidence_events(
        &events,
        &VerifyEvidenceOptions::new(vec![na_public_key], executor_keys),
    );
    for failure in &result.failures {
        eprintln!("{} at {:?}: {}", failure.reason, failure.store_sequence, failure.detail);
    }
    Ok(result.verified)
}
```

`executor_keys` is the list `GET /admin/evidence/executor-keys` returns
(`evidence_store.list_executor_keys`); retired keys still verify old records,
and an observer key verifies observations only. `VerifyEvidenceOptions::new`
is for a contiguous export; set `contiguous: false` for a filtered history,
`checkpoint` for chains whose early records retention removed, and `prior`
for a pack's cited records. Verifying the Python export gives the same result
as the NA's `GET /admin/evidence/verify`.

`verify::verify_record(kind, record, options)` verifies one record as an
export verifies it, with the same reason codes: any entry kind, a policy or
an attestation.

### Store anchors

`verify::parse_anchors` reads the anchors you keep outside the NA,
`verify::verify_store_anchors` checks their signatures, chain and positions,
and `verify::check_events_against_anchors` ties an export to the anchors held
at both ends. Without anchors you hold, an export proves the integrity of what
it contains, not that nothing was removed. See
{doc}`/operations/evidence-anchors`.

---

## Audit packs

`audit_pack::verify_audit_pack` checks an audit pack as
`genesis-mesh audit verify` does. It takes each pack file's path (with `/`)
and bytes, the root key and the anchors you hold:

```rust
use std::collections::BTreeMap;
use std::path::Path;

use genesis_mesh_sdk::audit_pack::{verify_audit_pack, VerifyPackOptions};
use genesis_mesh_sdk::Value;

fn read_pack(root: &Path, dir: &Path, files: &mut BTreeMap<String, Vec<u8>>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            read_pack(root, &path, files)?;
        } else {
            let name: Vec<String> = path.strip_prefix(root).unwrap().components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned()).collect();
            files.insert(name.join("/"), std::fs::read(&path)?);
        }
    }
    Ok(())
}

fn pack(dir: &Path, root_public_key: &str, held_anchors: Vec<Value>) -> std::io::Result<bool> {
    let mut files = BTreeMap::new();
    read_pack(dir, dir, &mut files)?;
    let result = verify_audit_pack(&files, &VerifyPackOptions::new(root_public_key, Some(held_anchors)));
    for failure in &result.failures {
        eprintln!("{}: {:?}", failure.reason, failure.file);
    }
    Ok(result.verified)
}
```

Without held anchors the result warns `no_held_anchors`. `render_report`
renders the pack's `report.md` byte for byte, `differences_from_pack_checks`
compares the result with the pack's own `checks.json`, and `parse_changes`
with `check_completeness` compare the pack with a change log kept outside
Genesis Mesh. See {doc}`/operations/audit-packs`.

---

## The `genesis-mesh-verify` binary

`genesis-mesh-verify` (from 1.5.0) is a static Linux binary built from these
modules, released from the `sdk-rust` repository with checksums and Sigstore
bundles, and reproducible from source. An auditor runs it on their own
machines:

```sh
genesis-mesh-verify pack pack-2026 --anchor root.pub --known-anchors /audit/anchors
genesis-mesh-verify export export.jsonl --key-history key-history.json --root-key root.pub \
    --executor-keys executor-keys.json --known-anchors /audit/anchors --json
genesis-mesh-verify record decision decision.json --key-history key-history.json --root-key root.pub
genesis-mesh-verify key-history key-history.json --root-key root.pub
```

Exit codes: 0 verified, 1 not verified, 2 usage error, 3 an input could not
be read. See {doc}`/operations/independent-verification`.
