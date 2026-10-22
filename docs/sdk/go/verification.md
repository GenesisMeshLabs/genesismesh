# Offline Verification — Go SDK

From 0.61.0 the Go SDK checks the Network Authority's signed records without
calling the NA, with canonical JSON and Ed25519 only. Each function is a port
of the Python reference and returns its reason codes. The shared conformance
vectors check that they agree on the cases the vectors cover.

Two rules apply to every function on this page:

- **Pass the JSON as received** (`[]byte`). Signatures cover the canonical
  form of exactly what was signed. Decoding a record into a Go struct and
  encoding it again can drop fields or change number literals (`1.0` becomes
  `1`), and a valid signature then fails.
- **Acceptance means the artifact verified, not that it is allowed.** A
  boundary decision that verifies and denies has `Accepted` true and
  `Authorized` false. Act only when both are true.

Revocation is not checked offline. Supply the public keys you trust from a
source you hold, not from the record itself.

An error return means the input could not be read at all: not JSON, not a JSON
object, JSON that parsers read differently (`*StrictJSONError`), or a
timestamp the check needs that does not parse. A record that is read and
refused comes back as a result with a reason.

---

## Boundary decisions

```go
d, err := genesismesh.VerifyBoundaryDecision(decisionJSON, genesismesh.DecisionVerifyOptions{
	OperatorPublicKeys:  []string{naPublicKey},
	ExpectedPolicies:    [][]byte{policyJSON}, // optional: the decision must bind exactly these versions
	ExpectedAttestation: attestationJSON,      // optional
})
if err != nil {
	return err // not JSON, or not a JSON object
}
if !d.Accepted {
	return fmt.Errorf("decision %s refused: %s", d.DecisionID, d.Reason)
}
if !d.Authorized {
	return fmt.Errorf("decision %s denies: %s", d.DecisionID, d.Reason)
}
```

| `DecisionVerifyOptions` field | Meaning |
|---|---|
| `OperatorPublicKeys` | The NA keys that may sign decisions |
| `KeyHistory` | Instead of `OperatorPublicKeys`, the NA's verified key history (1.5.0, below) |
| `Now` | The verification time (zero: now). Set it only for a historical audit |
| `AtRecordTime` | Judge the decision as of its own `decision_made_at` (1.5.0) |
| `FreshnessProofIssuerKeys` | When set, an embedded freshness proof must verify under these keys |
| `ExpectedPolicies` | Signed `BoundaryPolicy` JSON; when not nil, the decision's policy binding must equal it |
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

```go
a, err := genesismesh.VerifyAgreement(agreementJSON, []string{offererKey}, []string{responderKey}, "")
if err != nil {
	return err
}
// a.Accepted, a.Reason ("accepted", "invalid_offerer_signature", ...), a.AgreementID
```

The last argument is the expected `graph_digest`; `""` skips that check.
Reasons, in order: `accepted`, `missing_offerer_signature`,
`invalid_offerer_signature`, `missing_responder_signature`,
`invalid_responder_signature`, `graph_digest_mismatch`, `unknown_field`,
`non_canonical_form`.

---

## Data license policies and access intents

```go
ok, err := genesismesh.VerifyDataLicensePolicySignature(licensePolicyJSON, []string{licensorKey})
if err != nil {
	return err
}
v, err := genesismesh.VerifyDataAccessIntent(intentJSON, licensePolicyJSON, []string{agentKey}, time.Time{})
if err != nil {
	return err
}
// ok: the licensor signed the policy
// v.Valid; otherwise v.ViolationReason (the first) and v.Violations (all of them)
```

`VerifyDataLicensePolicySignature` is true when the licensor signed the
policy and every signed field is known and in canonical form.

`VerifyDataAccessIntent` checks the agent's signature on the intent, then the
intent against the policy at the given time (zero: now). Violation types:
`intent_exceeds_license` (a missing or invalid signature, an unknown field or
a non-canonical form), then `intent_expired`, `policy_expired`,
`source_not_licensed`, `prohibited_classification`,
`access_type_not_permitted` and `volume_cap_exceeded`.

---

## Digests and canonical form

| Function | Returns |
|---|---|
| `CanonicalJSON(raw)` | The canonical form of a JSON text, as the reference writes it |
| `PolicyDigest(policyJSON)` | `BoundaryPolicy.digest()` |
| `AttestationDigest(attestationJSON)` | `MembershipAttestation.digest()` |
| `PolicySetDigest(refs)` | The digest of an ordered list of policy versions |
| `UnknownFields(model, recordJSON)` | The signed fields of a record that this SDK's field registry does not list |
| `CheckStrictJSON(raw)` | A `*StrictJSONError` for JSON that parsers read differently: `invalid_json`, `duplicate_key`, `non_finite_number`, `integer_out_of_range`, `negative_zero`, `lone_surrogate` |

---

## NA key history (1.5.0)

A Network Authority can move to a new signing key: a key succession, signed by
its offline root key and by the outgoing key. With the NA's key history, a
record must carry the signature of the key valid at the record's own time: a
decision's `decision_made_at`, an agreement's `agreed_terms.valid_from`
(`NARecordTimeFields` lists the field of each NA-signed record). Without a
history nothing changes: a list of keys is valid at every time.

```go
resp, err := http.Get(baseURL + "/na/key-history") // public route
if err != nil {
	return err
}
defer resp.Body.Close()
body, err := io.ReadAll(resp.Body)
if err != nil {
	return err
}
h, err := genesismesh.VerifyKeyHistoryResponse(body, rootPublicKey) // root key held out of band
if err != nil {
	return err
}
if !h.Verified {
	return fmt.Errorf("key history refused at record %d: %s", h.KeySequence, h.Reason)
}

d, err = genesismesh.VerifyBoundaryDecision(decisionJSON, genesismesh.DecisionVerifyOptions{
	KeyHistory:   h.History, // instead of OperatorPublicKeys
	AtRecordTime: true,      // optional: an archived decision, judged as of decision_made_at
})
if err != nil {
	return err
}

a, err = genesismesh.VerifyAgreementWithKeyHistory(agreementJSON, h.History,
	genesismesh.NAKeysValidAlways([]string{responderKey}), "", time.Time{})
if err != nil {
	return err
}
```

The response's own keys prove nothing: the history is rebuilt from the root
public key you pass, which you hold out of band. `VerifyKeyHistory(genesisJSON,
successionsJSON, rootPublicKey)` takes the genesis block and the succession
records directly.

- **Refusal reasons**, in the reference order: for the genesis block
  `genesis_invalid`, `genesis_root_mismatch`, `unknown_field`,
  `non_canonical_form`, `genesis_invalid_signature`; for each succession
  `payload_invalid`, `unknown_field` or `invalid_signature`,
  `non_canonical_form`, then the `succession_*` reasons (such as
  `succession_chain_break`, `succession_key_reused`,
  `succession_invalid_root_signature`). `KeySequence` is the refused record's
  position (1 for the genesis block); nothing after it is accepted.
- **Hand-over.** A succeeded key is still accepted for records dated up to
  `SuccessionHandover` (300 seconds) after the next key takes effect.
- **Decisions.** A decision may not stay valid more than
  `MaxDecisionLifetime` (300 seconds) past the end of the key that signed it
  (`decision_outlives_key`). Signed by a key of the history that was not
  valid at `decision_made_at`: `na_key_not_valid_at_time`.
- **Agreements.** `VerifyAgreementWithKeyHistory` takes one history per party;
  use `NAKeysValidAlways` for a party whose history you do not hold. An
  agreement a succeeded key signed stops vouching when that key's hand-over
  ends.

Audit packs and archives are not verified by this SDK: use the core's
`genesis-mesh audit verify` or the Rust SDK's `genesis-mesh-verify`
({doc}`/operations/independent-verification`).

---

## Pre-issued grants (1.6.0): signature only

From 1.6.0 the NA can issue a `CapabilityGrant` before the bearer acts, so the
bearer can act within it while the NA is unreachable. Grants are off unless
the NA runs with `EVIDENCE_GRANTS=on`. `VerifyCapabilityGrant` checks that a
grant is the NA's: signed by the key of its key history valid at the grant's
`issued_at`, with every signed field known and in canonical form.

```go
g, err := genesismesh.VerifyCapabilityGrant(grantJSON, h.History) // or NAKeysValidAlways([]string{naPublicKey})
if err != nil {
	return err
}
// g.Valid, g.GrantID; otherwise g.Reason
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

The SDK runs these shared suites from `genesismesh/testdata/conformance/`:
`interop` (the verifiers above), `canonical`, `field_registry`,
`admin_auth`, `consensus`, the canonical form, key history and record time
kinds of `audit`, and the canonical form and signature kinds of `grants`. It
skips the kinds of those two suites it does not implement (packs, exports,
anchors, completeness, envelopes, grant use and issuance), and a test fails
when a new kind is neither run nor listed as skipped. It runs neither the
`out_of_band` nor the `remediation` suite.
