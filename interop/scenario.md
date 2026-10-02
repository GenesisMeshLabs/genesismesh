# Cross-language interoperability scenario

This document states what the interoperability scenario proves, and how. It is
the interoperability certificate for Genesis Mesh v0.61: every claim below is
checked on each push by `.github/workflows/interop.yml`.

## What is proven

> A trust agreement negotiated in Python is accepted by the Go, TypeScript and
> C# verifiers; boundary decisions signed by the Python Network Authority are
> verified, with their policy and attestation bindings, by the same three; a
> data access intent signed by the TypeScript SDK is accepted by the Network
> Authority and by the C# SDK; and all four implementations reach the same
> verdict, with the same reason code, on every artifact in the scenario,
> including the tampered and denied ones.

The scenario uses the real implementations, a real Network Authority over HTTP
and records signed at run time with keys generated for the run. Nothing is
replayed from fixed vectors; the shared conformance vectors
(`conformance/vectors/interop.json`) test the same verifiers in isolation and
are checked first.

The scenario fails if any implementation disagrees with another on any
decision, not only when a positive path fails. A verifier that accepted
everything would fail on the tampered agreement; one that rejected everything
would fail on the genuine one.

## The trust scenario

Two sovereigns, **org-a** (a data provider) and **bank-a** (its client), each
hold their own Ed25519 key. A Network Authority (**interop-na**) operates the
boundary between them: it publishes the boundary policy, decides each request
and licenses the data.

1. org-a offers bank-a `transactions.read` and `statements.read`; bank-a
   counters with the same terms; org-a accepts. The agreement carries both
   signatures over the same canonical body, including non-ASCII text
   (`Zürich ✓`) and floats (`0.25`, `1.0`) in its scope, so every
   implementation must reproduce Python's canonical JSON exactly.
2. The NA publishes and activates a signed boundary policy (`bank-read-limits`:
   at most 90 rows; a purpose attribute observed but not enforced), with policy
   enforcement required.
3. The NA decides `transactions.read` under the agreement for 10 rows
   (authorized) and 500 rows (denied by the policy gate), and under a
   membership attestation it issued to bank-a (authorized). Each decision binds
   the policy versions it applied; the attestation decision also binds the
   attestation.
4. The NA, as licensor, signs a data license policy for bank-a: sources
   `db-prod` and `db-archive`, access type `read`, a 10 MB cap per session,
   `pii-raw` data prohibited.
5. bank-a's agent, using the TypeScript SDK with its own key, signs a data
   access intent under the authorized decision (`db-prod`, `read`, 1 MiB) and
   a non-compliant one (an unlicensed source tagged `pii-raw`, `export` access,
   50 MB). Both are submitted to the NA.

## The legs

| Leg | Implementation | Does | A failure means |
| --- | --- | --- | --- |
| NA | Python (`python/na_server.py`) | Runs the real Network Authority application on 127.0.0.1 with fresh keys and a temporary database | The NA does not start |
| 1 | Python (`python/setup.py`) | Negotiates the agreement, publishes the policy, obtains the three decisions and the license policy over HTTP, writes them and tampered copies to `fixtures/`, and records the reference verdicts | The reference implementation cannot produce or verify its own records |
| 2 | Go SDK (`go/verify.go`) | Verifies the agreements, the four decisions (policy and attestation bindings included) and the license policy offline | Go reads a Python record differently: canonical JSON, timestamps, digests or reason codes diverge |
| 3 | TypeScript SDK (`typescript/submit_intent.ts`) | Creates and signs both intents, submits them to the NA's `/data-usage/verify`, checks the NA and the SDK agree, writes `ts_intent.json`, and verifies the Python records offline | The NA rejects a TypeScript-signed record, or TypeScript judges a record differently |
| 4 | C# SDK (`csharp/VerifyIntent`) | Verifies the TypeScript intents against the NA-signed policy offline, and the Python records | A record signed in TypeScript is not verifiable in C#, or C# judges a record differently |
| — | `assert_results.py` | Compares every leg's verdicts with each other and with the scenario's expectations; writes `fixtures/results.json` | Two implementations disagree |

Expected verdicts, identical in every implementation that judges the artifact:

| Artifact | Verdict |
| --- | --- |
| `agreement` | accepted |
| `agreement_tampered` (capability added after signing) | rejected, `invalid_offerer_signature` |
| `boundary_decision` (10 rows) | accepted, authorized |
| `boundary_decision_denied` (500 rows) | accepted (validly signed), not authorized, `unauthorized_policy_gate_failure` |
| `boundary_decision_attestation` | accepted, authorized, attestation binding matches |
| `boundary_decision_tampered` (denial reason edited) | rejected, `invalid_signature` |
| `data_policy` | signature valid |
| `ts_intent` | compliant |
| `ts_intent_denied` | not compliant: `source_not_licensed`, `prohibited_classification`, `access_type_not_permitted`, `volume_cap_exceeded` |

## Running it locally

Requirements: the core installed in a virtual environment (`.venv` is used
when present), Go 1.22+, Node.js 22+, .NET 8, and checkouts of `sdk-go`,
`sdk-typescript` and `sdk-dotnet` next to this repository (or set
`GM_SDK_GO_DIR`, `GM_SDK_TS_DIR`, `GM_SDK_DOTNET_DIR`).

```bash
interop/run_all.sh
```

Expected output ends with:

```text
[GO VERIFIER] agreement: OK  boundary: OK
[TS SDK] intent: submitted  compliant: true
[CSHARP SDK] intent: verified  compliant: true
...
ALL LEGS PASSED
```

## Limits

- The NA runs on SQLite in a single process; the HA and PostgreSQL paths are
  covered by the core's PostgreSQL CI job and the v0.60 HA tests, not here.
- The Rust SDK and the gateway are not legs of this scenario.
- Offline verification checks signatures, expiry and bindings. It does not
  check revocation, which needs the issuer's live revocation state.
