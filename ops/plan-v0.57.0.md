# v0.57.0 Plan -- Cross-Language Interoperability Proof

## Positioning

v0.56 proved that a second implementation passes the conformance suite.
That is a necessary condition for calling Genesis Mesh a protocol.
It is not sufficient.

A protocol is interoperable when implementations can exchange records with
each other in a live, end-to-end scenario.  The conformance suite tests
each implementation in isolation against fixed vectors.  It does not test
that a record produced by the Python implementation at runtime is accepted
by the Go verifier, and that a record signed by a TypeScript client is
verifiable by the C# client.

v0.57 constructs the interoperability proof: a CI-enforced test matrix that
runs a cross-language scenario end-to-end.  The scenario covers the complete
authorization path: agreement negotiation (Python), boundary decision (Python),
agreement verification (Go verifier), boundary decision verification (Go),
TypeScript intent submission (TS SDK), C# intent verification (C# SDK).

This is not a synthetic test.  It uses the actual implementations, actual
network calls, and actual signed records.  The scenario fails if any
implementation disagrees with another on any protocol decision.

v0.57 should prove:

> A trust agreement produced by the Python Network Authority is independently
> verifiable by the Go verifier; a boundary decision produced by Python is
> verifiable in Go; a data access intent submitted by the TypeScript SDK is
> verifiable by the C# SDK; all four implementations agree on all protocol
> decisions in the cross-language scenario.

## Design

### Interoperability scenario: `interop/`

```
interop/
  README.md
  scenario.md              -- narrative description of the full scenario
  run_all.sh               -- orchestration script (starts NA, runs all legs)
  python/
    setup.py               -- create agreement + boundary decision, write to fixtures/
  go/
    verify.go              -- read fixtures/, verify with Go verifier, exit 0/1
  typescript/
    submit_intent.ts       -- read fixtures/, submit data intent via TS SDK
  csharp/
    VerifyIntent/Program.cs -- read fixtures/ + TS output, verify via C# SDK
  fixtures/                -- written by python/setup.py, read by other legs
    agreement.json
    boundary_decision.json
    data_policy.json
```

### The scenario (four legs)

**Leg 1 (Python)** -- `interop/python/setup.py`

1. Start a local Network Authority
2. Create two sovereigns (org-a, bank-a) with real Ed25519 keys
3. Negotiate a full agreement (offer → counter → accept → cosign)
4. Issue a boundary decision for `transactions.read`
5. Create a `DataLicensePolicy`
6. Write all signed artifacts to `interop/fixtures/`

**Leg 2 (Go)** -- `interop/go/verify.go`

1. Read `fixtures/agreement.json`, `fixtures/boundary_decision.json`
2. Verify agreement with Go verifier using public keys from fixtures
3. Verify boundary decision with Go verifier
4. Assert both return `valid=true`
5. Print: `[GO VERIFIER] agreement: OK  boundary: OK`
6. Exit 0 if both OK, exit 1 if any fail

**Leg 3 (TypeScript)** -- `interop/typescript/submit_intent.ts`

1. Read `fixtures/data_policy.json` and public keys
2. Create a `DataAccessIntent` for `db-prod` source using TS SDK
3. Submit to local NA
4. Assert `compliant=true`
5. Write `fixtures/ts_intent.json`
6. Print: `[TS SDK] intent: submitted  compliant: true`

**Leg 4 (C#)** -- `interop/csharp/VerifyIntent/Program.cs`

1. Read `fixtures/ts_intent.json` and `fixtures/data_policy.json`
2. Verify intent against policy using C# SDK
3. Assert `compliant=true`
4. Print: `[CSHARP SDK] intent: verified  compliant: true`
5. Exit 0 if OK

### CI matrix: `.github/workflows/interop.yml`

```yaml
name: Interoperability
on: [push, pull_request]
jobs:
  interop:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
      - name: Set up Go 1.22
        uses: actions/setup-go@v5
      - name: Set up Node 20
        uses: actions/setup-node@v4
      - name: Set up .NET 8
        uses: actions/setup-dotnet@v4

      - name: Install Python deps
        run: pip install -e ".[dev]"

      - name: Leg 1 -- Python setup
        run: python interop/python/setup.py

      - name: Leg 2 -- Go verification
        run: cd interop/go && go run verify.go

      - name: Leg 3 -- TypeScript intent
        run: cd interop/typescript && npm ci && npx ts-node submit_intent.ts

      - name: Leg 4 -- C# verification
        run: cd interop/csharp/VerifyIntent && dotnet run

      - name: Assert all legs passed
        run: cat interop/fixtures/results.json | python -c "
import json, sys
r = json.load(sys.stdin)
assert all(r[k] for k in r), f'Interop failure: {r}'
print('ALL LEGS PASSED')
"
```

### `interop/scenario.md`

Human-readable narrative that describes:
- The trust scenario being tested
- What each leg does and why
- What a failure in each leg means
- How to run the scenario locally

This document is the interoperability certificate: it states precisely
what has been proven about cross-language agreement.

### Interoperability badge in README

```markdown
![Interoperability](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/interop.yml/badge.svg)
```

## Success Criteria

- [ ] `interop/` directory with all four legs
- [ ] Leg 1 (Python) produces all fixtures
- [ ] Leg 2 (Go) verifies agreement + boundary decision: exit 0
- [ ] Leg 3 (TypeScript) submits + verifies data intent: exit 0
- [ ] Leg 4 (C#) verifies TypeScript-produced intent: exit 0
- [ ] `.github/workflows/interop.yml` runs all four legs in sequence
- [ ] CI passes on `main` branch
- [ ] `interop/scenario.md` narrative documents the full scenario
- [ ] Interoperability badge added to README

## Release Gate

- [ ] Package metadata bumped to `0.56.0`
- [ ] CHANGELOG entry (cross-language interoperability proof)
- [ ] history.md updated with v0.57.0 entry
- [ ] All prior Python tests continue to pass
- [ ] All SDK tests continue to pass
- [ ] Go verifier conformance: 100% pass rate
- [ ] Interop CI workflow: all four legs green
