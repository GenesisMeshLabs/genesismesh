# Offline Verification — .NET SDK

From 0.61.0 the .NET SDK checks the Network Authority's signed records without
calling the NA, with canonical JSON and Ed25519 only. Each `OfflineVerifier`
method is a port of the Python reference and returns its reason codes. The
shared conformance vectors check that they agree on the cases the vectors
cover.

From 1.9.0 it also verifies the NA's other signed records, an evidence export
(every entry kind of the store), the store anchors an auditor holds, and audit
packs with their completeness check (see the sections below).

Two rules apply to every method on this page:

- **Pass the JSON text as received** (`string`). Signatures cover the
  canonical form of exactly what was signed. Deserializing a record into a
  typed model and serializing it again can drop fields or change number
  literals, and a valid signature then fails.
- **Acceptance means the artifact verified, not that it is allowed.** A
  boundary decision that verifies and denies has `Accepted` true and
  `Authorized` false. Act only when both are true.

Revocation is not checked offline. Supply the public keys you trust from a
source you hold, not from the record itself.

A method throws when it cannot read its input: `StrictJsonException` (a
`JsonException`) for text that is not JSON or that parsers read differently,
and `FormatException` for a timestamp the check needs that does not parse. A
record that is read and refused comes back as a result with a reason.

---

## Boundary decisions

```csharp
var d = OfflineVerifier.VerifyBoundaryDecision(decisionJson, new DecisionVerifyOptions
{
    OperatorPublicKeys  = new[] { naPublicKey },
    ExpectedPolicies    = new[] { policyJson },   // optional: the decision must bind exactly these versions
    ExpectedAttestation = attestationJson,        // optional
});
if (!d.Accepted)
    throw new InvalidOperationException($"decision {d.DecisionId} refused: {d.Reason}");
if (!d.Authorized)
    throw new InvalidOperationException($"decision {d.DecisionId} denies: {d.Reason}");
```

| `DecisionVerifyOptions` property | Meaning |
|---|---|
| `OperatorPublicKeys` | The NA keys that may sign decisions |
| `KeyHistory` | Instead of `OperatorPublicKeys`, the NA's verified key history (1.5.0, below) |
| `Now` | The verification time (default now). Set it only for a historical audit |
| `AtRecordTime` | Judge the decision as of its own `decision_made_at` (1.5.0) |
| `FreshnessProofIssuerKeys` | When set, an embedded freshness proof must verify under these keys |
| `ExpectedPolicies` | Signed `BoundaryPolicy` JSON; when not null, the decision's policy binding must equal it |
| `ExpectedPolicyIds` | Policy IDs an ALLOW must rest on, at any version the NA signed, each with an enforce-mode gate evaluated (1.10.0); a DENY is reported as it is |
| `ExpectedAttestation` | Signed `MembershipAttestation` JSON; when set, the attestation binding must match it |

**Refused** (`Accepted` false), in the order checked: `missing_signature`,
`decision_expired`, `invalid_signature`, `unknown_field`,
`non_canonical_form`, `na_key_not_valid_at_time`, `decision_outlives_key`,
`freshness_proof_invalid_signature`, `freshness_proof_expired`,
`policy_binding_missing`, `policy_binding_mismatch`,
`attestation_binding_missing`, `attestation_binding_mismatch`.

**Verified** (`Accepted` true): `authorized` when the decision allows;
otherwise a denial reason with `Authorized` false:
`unauthorized_attestation_basis`, `unauthorized_policy_resolution_failed`,
`unauthorized_policy_gate_failure`, `unauthorized_capability_out_of_scope`,
`unauthorized_outside_validity_window`, `unauthorized_insufficient_freshness`
or `unauthorized_gate_failure`.

`unknown_field` means the record carries a signed field this SDK version does
not know: upgrade the SDK. `non_canonical_form` means it was signed over a
form the reference does not write (1.2.0).

---

## Agreements

```csharp
var a = OfflineVerifier.VerifyAgreement(agreementJson, new[] { offererKey }, new[] { responderKey });
// a.Accepted, a.Reason ("accepted", "invalid_offerer_signature", ...), a.AgreementId
```

An optional fourth argument is the expected `graph_digest`; `null` (the
default) skips that check. Reasons, in order: `accepted`,
`missing_offerer_signature`, `invalid_offerer_signature`,
`missing_responder_signature`, `invalid_responder_signature`,
`graph_digest_mismatch`, `unknown_field`, `non_canonical_form`.

---

## Data license policies and access intents

```csharp
bool signedByLicensor = OfflineVerifier.VerifyDataLicensePolicySignature(licensePolicyJson, new[] { licensorKey });
var v = OfflineVerifier.VerifyDataAccessIntent(intentJson, licensePolicyJson, new[] { agentKey });
// v.Valid; otherwise v.ViolationReason (the first) and v.Violations (all of them)
```

`VerifyDataLicensePolicySignature` is true when the licensor signed the
policy and every signed field is known and in canonical form.

`VerifyDataAccessIntent` checks the agent's signature on the intent, then the
intent against the policy at the given time (default now). Violation types:
`intent_exceeds_license` (a missing or invalid signature, an unknown field or
a non-canonical form), then `intent_expired`, `policy_expired`,
`source_not_licensed`, `prohibited_classification`,
`access_type_not_permitted` and `volume_cap_exceeded`.

---

## Digests and canonical form

| Method | Returns |
|---|---|
| `Canonical.FromJson(json)` | The canonical form of a JSON text, as the reference writes it |
| `OfflineVerifier.PolicyDigest(policyJson)` | `BoundaryPolicy.digest()` |
| `OfflineVerifier.AttestationDigest(attestationJson)` | `MembershipAttestation.digest()` |
| `OfflineVerifier.PolicySetDigest(...)` | The digest of an ordered list of policy versions |
| `StrictFields.UnknownFields(model, recordJson)` | The signed fields of a record that this SDK's field registry does not list |
| `StrictJson.Check(json)` | Throws `StrictJsonException` for JSON that parsers read differently; its `Reason` is `invalid_json`, `duplicate_key`, `non_finite_number`, `integer_out_of_range`, `negative_zero` or `lone_surrogate` |

---

## NA key history (1.5.0)

A Network Authority can move to a new signing key: a key succession, signed by
its offline root key and by the outgoing key. With the NA's key history, a
record must carry the signature of the key valid at the record's own time: a
decision's `decision_made_at`, an agreement's `agreed_terms.valid_from`
(`NAKeyHistory.RecordTimeFields` lists the field of each NA-signed record).
Without a history nothing changes: a list of keys is valid at every time.

```csharp
var body = await http.GetStringAsync(baseUrl + "/na/key-history");   // public route
var h = OfflineVerifier.VerifyKeyHistoryResponse(body, rootPublicKey); // root key held out of band
if (!h.Verified)
    throw new InvalidOperationException($"key history refused at record {h.KeySequence}: {h.Reason}");

d = OfflineVerifier.VerifyBoundaryDecision(decisionJson, new DecisionVerifyOptions
{
    KeyHistory   = h.History,   // instead of OperatorPublicKeys
    AtRecordTime = true,        // optional: an archived decision, judged as of decision_made_at
});

a = OfflineVerifier.VerifyAgreementWithKeyHistory(agreementJson, h.History!,
    NAKeyHistory.ValidAlways(new[] { responderKey }));
```

The response's own keys prove nothing: the history is rebuilt from the root
public key you pass, which you hold out of band.
`OfflineVerifier.VerifyKeyHistory(genesisJson, successionsJson, rootPublicKey)`
takes the genesis block and the succession records directly.

- **Refusal reasons**, in the reference order: for the genesis block
  `genesis_invalid`, `genesis_root_mismatch`, `unknown_field`,
  `non_canonical_form`, `genesis_invalid_signature`; for each succession
  `payload_invalid`, `unknown_field` or `invalid_signature`,
  `non_canonical_form`, then the `succession_*` reasons (such as
  `succession_chain_break`, `succession_key_reused`,
  `succession_invalid_root_signature`). `KeySequence` is the refused record's
  position (1 for the genesis block); nothing after it is accepted.
- **Hand-over.** A succeeded key is still accepted for records dated up to
  `NAKeyHistory.SuccessionHandover` (300 seconds) after the next key takes
  effect.
- **Decisions.** A decision may not stay valid more than
  `NAKeyHistory.MaxDecisionLifetime` (300 seconds) past the end of the key
  that signed it (`decision_outlives_key`). Signed by a key of the history
  that was not valid at `decision_made_at`: `na_key_not_valid_at_time`.
- **Agreements.** `VerifyAgreementWithKeyHistory` takes one history per
  party; use `NAKeyHistory.ValidAlways` for a party whose history you do not
  hold. An optional `now` is the time the keys must still be accepted: an
  agreement a succeeded key signed stops vouching when that key's hand-over
  ends.
- **The vouching horizon (1.8.1).** Judged for the present, a record of a
  key that has ended vouches only until that key's end, the hand-over and a
  grace of at most 24 hours (`NAKeyHistory.SuccessionVouchingGrace`):
  `RecordOutlivesKey`, `KeysVouchingAt` and `WithVouchingGrace` on
  `NAKeyHistory`, `VerifyCapabilityGrant(grant, history, now)`
  (`outlives_key`) and `NARecordRefusal` for attestations, treaties,
  revocation feeds and grants. `VerifyKeyHistoryResponse` takes the NA's
  `vouching_grace_seconds` only to shorten the grace. See
  {doc}`/operations/key-succession`.

Audit packs and archives are not verified by this SDK: use the core's
`genesis-mesh audit verify` or the Rust SDK's `genesis-mesh-verify`
({doc}`/operations/independent-verification`).

---

## Pre-issued grants (1.6.0): signature only

From 1.6.0 the NA can issue a `CapabilityGrant` before the bearer acts, so the
bearer can act within it while the NA is unreachable. Grants are off unless
the NA runs with `EVIDENCE_GRANTS=on`. `OfflineVerifier.VerifyCapabilityGrant`
checks that a grant is the NA's: signed by the key of its key history valid
at the grant's `issued_at`, with every signed field known and in canonical
form.

```csharp
var g = OfflineVerifier.VerifyCapabilityGrant(grantJson, h.History!); // or NAKeyHistory.ValidAlways(new[] { naPublicKey })
// g.Valid, g.GrantId; otherwise g.Reason
```

Reasons, in order: `missing_signature`, `invalid_signature`, `unknown_field`,
`non_canonical_form`, `na_key_not_valid_at_time`; `accepted` when valid.

It does not check the grant's validity window, budget, parameter envelope or
revocation. From 1.9.0 the grants' rules, the NA's grant routes and a holder
that acts within a grant are in {doc}`grants`, and an export verifies grants,
their uses and revocations (below). From 1.9.0 a grant must also be one the
reference's model takes (`malformed` otherwise): a validity of at most 24
hours, starting within 24 hours of its issue.

---

## Other signed records (1.9.0)

```csharp
bool decided = OfflineVerifier.VerifyDecisionSignature(decisionJson, new[] { naPublicKey });
bool published = OfflineVerifier.VerifyPolicySignature(policyJson, history);
bool issued = OfflineVerifier.VerifyAttestationSignature(attestationJson, history, DateTimeOffset.UtcNow);
bool recognised = OfflineVerifier.VerifyTreatySignature(treatyJson, history);
bool revoking = OfflineVerifier.VerifyRevocationFeedSignature(feedJson, history);
```

Each checks a signature over the record as received, by the NA's keys or by
the key of its history valid at the record's time. A record must have no field
this SDK does not know and be in canonical form: its timestamps as the
reference writes them, and every field the reference always writes. With a
time to judge at, an attestation, a treaty or a revocation feed must still
vouch then.

---

## Evidence exports (1.9.0)

An export, or a resource's history, verifies offline, without trusting the NA:

```csharp
var events = new List<EvidenceEvent>();
await foreach (var e in admin.EvidenceStore.ExportAll()) events.Add(e);
var result = OfflineVerifier.VerifyEvidenceEvents(events, new EvidenceVerifyOptions
{
    KeyHistory = await admin.NA.VerifiedKeyHistory(rootPublicKey),  // or NAPublicKeys = [naKey]
    ExecutorKeys = await admin.EvidenceStore.ListExecutorKeys(),    // retired keys included
});
// result.Verified, result.Failures: StoreSequence, Reason, Detail
```

It is a port of the reference's `verify_evidence_events`, with its reason
codes. It checks:

- each envelope, its digests and the store chain;
- every signature: the NA's under the key valid at the record's time, and
  each executor's or observer's under a registered key with the role its kind
  needs;
- each execution record against its decision, and the decision, resource and
  observation chains;
- judgements, quarantine entries, remediation and review records, grant uses
  and revocations, key successions and archive records, each against what the
  run holds.

A bad entry is a failure, never an exception. For an export that starts after
a retention, pass `Checkpoint`, the NA-signed retention checkpoint as
received. For a range of an audit pack, pass its cited entries as `Prior`.

---

## Store anchors (1.9.0)

The store chain is hashed, not signed: whoever can write the NA's database can
remove entries and rebuild the links. A store anchor is the NA's signed
statement of the store's head, and anchors form their own chain. An auditor
keeps copies of the anchors (`EvidenceStore.AllAnchors()`) out of the
operator's reach and checks an export against them:

```csharp
var anchors = OfflineVerifier.ParseAnchors(heldAnchorsJson);  // the copies you hold
var chain = OfflineVerifier.VerifyStoreAnchors(anchors, new AnchorVerifyOptions { KeyHistory = history });
var run = OfflineVerifier.VerifyEvidenceEvents(events, options);
OfflineVerifier.CheckEventsAgainstAnchors(events, anchors, run);
// run.Anchors: how many anchors matched, where the anchored part of the run ends.
```

`VerifyStoreAnchors` checks each signature, the sovereign, the anchor chain
and heads that only move forward. `CheckEventsAgainstAnchors` ties the run to
the anchors at its start and its end, and checks each anchor inside it against
its entry (`anchor_mismatch`).

---

## Audit packs (1.9.0)

An audit pack is one range of the evidence store between two anchors, with
everything its records cite, the NA's key history and a manifest the NA signs
(protocol 1.5.0). An auditor verifies it offline, with no network and no
private key, from what they hold themselves: the root public key and their
copies of the anchors.

```csharp
var pack = await admin.EvidenceStore.AuditPack();                  // read tier
var files = OfflineVerifier.AuditPackFiles(pack);                    // or ReadAuditPackDirectory("pack/")
var result = OfflineVerifier.VerifyAuditPack(files, new VerifyAuditPackOptions
{
    RootPublicKey = rootPublicKey,   // held out of band
    HeldAnchors = heldAnchors,       // your copies; null checks the pack's integrity only (no_held_anchors)
    Changes = changes,               // optional: the completeness check against an outside log
    Period = (from, until),          // optional: a period the pack must cover
});
// result.Verified; result.Failures and result.Warnings, each with its file, entry and reason
```

- **The manifest first:** every file of the format listed with its digest and
  nothing else, in the NA's canonical form, signed as received by the NA key
  valid at its `created_at`. A pack whose manifest fails is not checked
  further.
- **Keys:** NA keys come only from the key history, verified from the root
  key. Executor and observer keys come from the registry records the NA signed
  (`RegistryKeys`), or from `ExecutorKeys` you supply.
- **The range:** tied to the anchors you hold; each cited entry checked
  against a pack verified before or an anchor you hold; the entries verified
  as an export, with the entries they cite; policies, attestations, treaties,
  feeds and a grant's agreement each checked as received.
- **The report:** `report.md` must be the report the pack's own files render
  to (`RenderReport`, `report_mismatch`).
- `EvidenceStore.RecordArchive` records that a pack was written to immutable
  storage (privileged tier); `VerifyArchiveRecord` checks the NA's record of
  it.

### Completeness against an outside log

A pack's records can be checked against a log kept outside Genesis Mesh, such
as a cloud audit log or a ticketing export: every change made in the period
should have its record.

```csharp
var changes = OfflineVerifier.ParseChanges(File.ReadAllText("changes.csv"), csv: true);
var report = OfflineVerifier.CheckCompleteness(changes, rangeEntries, citedEntries, new CompletenessOptions
{
    From = periodStart,
    To = periodEnd,                      // Tolerance: 300 seconds by default
});
// report.UnmatchedChanges: changes in the period the store does not record
```

`ParseChanges` reads CSV (a header row naming `source`, `source_event_id`,
`resource_id`, `action`, `changed_at`, `actor`) as Python's `csv` module reads
it, or JSON. `CheckCompleteness` matches a change naming a source event to the
record of that event, and the rest per resource and action, for the most pairs
and then the least total distance within the tolerance.

---

## Conformance vectors

The SDK runs these shared suites from
`tests/GenesisMesh.Sdk.Tests/testdata/conformance/`: `interop` (the verifiers
above), `canonical`, `field_registry`, `admin_auth`, `consensus` and
`vouching`. From 1.9.0 it also runs every vector of `audit` and
`remediation`, and those of `grants` and `out_of_band` but the kinds only an
NA can check (grant issuance; time bounds and policy history). A test fails
when a new kind is neither run nor listed as not run.
