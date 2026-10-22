# Interoperability scenario

A live, end-to-end scenario in which the Python Network Authority, the Go SDK,
the TypeScript SDK and the C# SDK exchange signed records. Every implementation
that judges an artifact must reach the same verdict. See
[scenario.md](scenario.md) for what it proves and what each leg does.

```bash
interop/run_all.sh
```

Requirements: bash, Python 3.12 or later with this repository installed
(`pip install -e .`), Go 1.22 or later, Node.js 22 or later (the TypeScript leg
uses `--experimental-strip-types`), the .NET 8 SDK, and checkouts of `sdk-go`,
`sdk-typescript` and `sdk-dotnet`. The script uses `.venv/bin/python` when it
exists and `python3` otherwise. On Windows, run it from Git Bash and set
`PYTHON` to your interpreter.

`interop/run_all.sh --published 1.7.0` runs every leg from the released
packages instead: the core from PyPI (in a fresh virtual environment), the
TypeScript SDK from npm, the C# SDK from NuGet and the Go SDK from the Go module
proxy, all at that version. `GM_PUBLISHED_CORE=source` keeps the core from this
checkout. The "Published artifacts" workflow runs this form.

## Who judges what

The artifacts are an agreement, boundary decisions, a data license policy and
data access intents. Treaties, revocation feeds, trust evidence, grants and
audit packs are not part of this run; they have their own conformance vector
suites in `conformance/vectors/`, which each SDK runs in part.

| Artifact | Judged by |
| --- | --- |
| `agreement`, `agreement_tampered` | Python, Go, TypeScript, C# |
| `boundary_decision`, `boundary_decision_denied`, `boundary_decision_attestation`, `boundary_decision_tampered` | Python, Go, TypeScript, C# |
| `data_policy` | Python, Go, TypeScript, C# |
| `ts_intent`, `ts_intent_denied` | Python (the NA's verdict on submission), TypeScript, C# |

`assert_results.py` requires every artifact to be judged by at least two
implementations, and every verdict to match the expected one. The Rust SDK,
`genesis-mesh-verify` and the gateway are not legs of this run. The
Interoperability workflow checks out the Rust SDK only to compare its copies
of the conformance vectors; the Rust SDK runs those vectors in its own CI.

| Path | Contents |
| --- | --- |
| `run_all.sh` | Starts the NA, runs the four legs in order, compares the results |
| `python/na_server.py` | Local Network Authority (fresh keys, temporary SQLite) |
| `python/setup.py` | Leg 1: agreement, boundary policy and decisions, license policy |
| `go/verify.go` | Leg 2: Go verifier |
| `typescript/submit_intent.ts` | Leg 3: TypeScript intent creation and submission |
| `csharp/VerifyIntent/` | Leg 4: C# verifier |
| `assert_results.py` | Fails if any two implementations disagree, or an artifact has fewer than two judges |
| `fixtures/` | Written at run time (not committed); `results.json` is the summary |

SDK checkouts default to siblings of this repository. Point at others with
`GM_SDK_GO_DIR`, `GM_SDK_TS_DIR` and `GM_SDK_DOTNET_DIR`; choose toolchains with
`PYTHON`, `GO`, `NODE`, `NPM` and `DOTNET`.

## Notes for implementers

- **TypeScript:** read signed records with the SDK's `parseJson`, not
  `JSON.parse`. A signed float such as `1.0` becomes the number `1` under
  `JSON.parse`, and the canonical form (and so the signature check) no longer
  matches the one Python signed.
- **C# and Go** verify from the JSON text, so no special parsing is needed.
- `fixtures/na.json` holds the run's throwaway operator key. It is never
  committed or uploaded.
