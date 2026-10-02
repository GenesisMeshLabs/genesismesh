# Interoperability scenario

A live, end-to-end scenario in which the Python Network Authority, the Go SDK,
the TypeScript SDK and the C# SDK exchange signed records and must agree on
every protocol decision. See [scenario.md](scenario.md) for what it proves and
what each leg does.

```bash
interop/run_all.sh
```

| Path | Contents |
| --- | --- |
| `run_all.sh` | Starts the NA, runs the four legs in order, compares the results |
| `python/na_server.py` | Local Network Authority (fresh keys, temporary SQLite) |
| `python/setup.py` | Leg 1: agreement, boundary policy and decisions, license policy |
| `go/verify.go` | Leg 2: Go verifier |
| `typescript/submit_intent.ts` | Leg 3: TypeScript intent creation and submission |
| `csharp/VerifyIntent/` | Leg 4: C# verifier |
| `assert_results.py` | Fails if any two implementations disagree |
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
