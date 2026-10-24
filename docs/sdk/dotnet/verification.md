# Offline Verification — .NET SDK

From 0.61.0 the .NET SDK checks the Network Authority's signed records without
calling the NA, with canonical JSON and Ed25519 only. Each `OfflineVerifier`
method is a port of the Python reference and returns its reason codes. The
shared conformance vectors check that they agree on the cases the vectors
cover.

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
revocation. Holding grants (requesting them, holding time tokens, acting
within a grant offline, recording its uses, falling back to break-glass) and
verifying grants in an evidence export need the TypeScript or Rust SDK (see
{doc}`../typescript/grants`).

---

## Conformance vectors

The SDK runs these shared suites from
`tests/GenesisMesh.Sdk.Tests/testdata/conformance/`: `interop` (the verifiers
above), `canonical`, `field_registry`, `admin_auth`, `consensus`, the
canonical form, key history and record time kinds of `audit`, and the
canonical form and signature kinds of `grants`. It skips the kinds of those
two suites it does not implement (packs, exports, anchors, completeness,
envelopes, grant use and issuance), and a test fails when a new kind is
neither run nor listed as skipped. It runs neither the `out_of_band` nor the
`remediation` suite.
