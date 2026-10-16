# Genesis Mesh: plan for growth and team scale (all six repositories)

Status: accepted by the Maintainer, 2026-10-16. Decisions: `docs/development/decisions/`. Source: a critic (measurements) and a skeptic
(strategy) per repository against one rubric (nine dimensions, including
regression defences). The quality gate in detail: `ops/quality-gate.md`.

## 1. Verdict

The program built an unusually strong **safety net**: a test-enforced public
contract, deterministic conformance vectors byte-compared across languages, a
live four-language interop run, upgrade rehearsal from 21 versions on two
databases, real-NA end-to-end tests in every SDK, signed reproducible builds,
fail-closed verification. Keep all of it.

What does not scale is **how features plug in and how the repos are
coupled**. Today one person (plus agents) can ship a stage a week; with 3x the
features and 5-10 people, work would collide and regressions would slip:

| Problem | Where | Evidence |
|---|---|---|
| A record kind is hand-wired in many places | core ~14 sites/10 files; Rust ~13 sites in verify.rs + 5-7 files; TS ~26 sites/9 files (tables fail **open**); Go/.NET a 3rd and 4th port | 14-18 core files touched by nearly every feature; 1.2.0's parallel work conflicted exactly there |
| Central lists every feature edits | core server.py/settings.py/surfaces/contract JSON/interop.yml/upgrade.md; gateway app.js/mod.rs/runtime.rs/ci.yml; TS index.ts 11/12 | measured fan-out per feature merge |
| Cross-repo coupling by copying and lockstep | vectors hand-copied into 4 SDKs; same-named branches; one version for everything | 10/14 Rust, 13/21 gateway, 9/9 TS, 7/8 Go CI failures came from another repo; 1.7.0 tag had to be re-pointed; rustls CVE fix waited a day; half of Go/.NET PRs are empty release bumps |
| Unguarded public APIs | all SDKs | breaking changes in patch 1.0.2 everywhere; Rust 4 of 7 minors |
| Tests green when they did not run | Rust (12 live tests), TS (describe.skip + returns), .NET (passes in 4 ms with no NA) | proven |
| Rules on paper only | core layer rules (~50 violations, a 42-module cycle), Rust 12-module cycle, TS cycle | measured |
| One reviewer | all six | 0 approvals on ~200 PRs; feature PRs 5k-23k lines; CODEOWNERS invalid in 3 repos |

No rewrite is needed. Registry and fragment refactors have already worked here
twice (changelog fragments took CHANGELOG conflicts from 5/5 features to 0).

## 2. Fix now (defects the assessment found)

Small PRs, independent of the rest of the plan.

| # | Repo | Fix | Why now |
|---|---|---|---|
| 1 | core | Migration numbering guard: duplicate/gapped numbers fail a test and `migration_files()`; `applied` re-read in the loop | Proven: two branches adding the same number silently skip the second migration on SQLite |
| 2 | sdk-dotnet | `Auth.SerializerOptions.MakeReadOnly()`; obsolete the leaked internals | Proven: any in-process code can re-enable the case-folding attack 1.3.1 closed |
| 3 | sdk-dotnet | Add `net10.0` target and CI; Dependabot for NuGet; NuGet trusted publishing (drop the long-lived key) | .NET 8 support ends 2026-11-10 |
| 4 | sdk-typescript | Package types: `types` first, `.d.cts`; `attw --pack` + `test:package` in CI and publish; remove "Unreleased" from shipped docs | 1.7.0 types misresolve for CJS consumers |
| 5 | sdk-go, sdk-dotnet | 403/409/413 mapped to their own errors (not `ServerError`); unknown model names fail closed | Retry-on-server-error retries permission refusals; a renamed model silently disables the strict check |
| 6 | gateway | Catalog invariant tests: explicit demo operation allow-list by ID, `/admin` => admin, every view key exists; audit/labels from `MatchedPath` (delete the hand lists) | The public demo token's read/verify-only promise is untested; a missed route is silently not audited |
| 7 | gateway | Durable audit: keep demo events out (or a capped table), retention of delivered rows, a schema migration ladder | Store fills -> 503 for all protected clients (droplet: 74 MB/13 days; ~2 weeks if the demo token is abused) |
| 8 | all SDKs, core | Valid CODEOWNERS (teams with write access); fragment-correct PR templates; core interop compares Go/.NET `audit`/`grants` copies; core suite collects on Windows | Ownership can't be enforced today; two vector copies unchecked |

## 3. Track 0: the quality gate (before any refactor)

Goal: no PR can merge a regression a test could catch; what slips through is
caught live before the next step. Details in `ops/quality-gate.md`.

1. **Merge queue** on every `main`; every workflow also runs on `merge_group`.
2. **Required checks = everything protective**, via summary jobs with stable
   names (e.g. "Upgrade rehearsals", "Edge scenarios"; no toolchain versions in
   names).
3. **Skipped is not green**: `GM_E2E_REQUIRED=1` in CI; zero-match filters
   fail; the core provides a stable "disposable NA with features" test entry
   point (ends constructor sniffing in SDK harnesses).
4. **Every fix carries a regression test**: PR template line + a CI check on
   `fix:` PRs (override only by a Maintainer label).
5. **One-way ratchets**: coverage floors per critical module; public-API
   compatibility (core contract tests, cargo-semver-checks, api-extractor,
   apidiff, .NET package validation) with a `breaking` label; architecture
   rules with an allowlist that may only shrink.
6. **Deeper tests** on parsers and verifiers: property tests and short fuzz
   runs in CI, longer weekly; scheduled mutation testing.
7. **After merges**: the agent runs the live smoke (sandbox apps, droplet,
   Azure) before the next step; a nightly scheduled live smoke; main red =
   revert first.
8. **Staged releases**: droplet first, Azure after its smoke passes; release
   candidates when migrations or signed formats change.
9. **Flaky tests** open an issue and are quarantined with an owner.

Delivered as one reusable-workflow source (an org `.github` repository) plus a
small PR per repo.

## 4. Track 1: shared conventions (all six repositories)

1. **A versioned contract bundle from the core**, pinned by every consumer:
   vectors, field and kind registry (with per-kind metadata: model, id field,
   signer role, time field, envelope map), error codes, and a **route
   manifest** (stable operation IDs, access tier, stability level, query
   parameters, request/response JSON Schemas, example bodies). One
   `sync` script per repo; CI checks the pinned bundle, not core `main`.
   Replaces hand copies, the `cmp` lines, same-named-branch pairing, the
   gateway's scraping of the core's Python, and the field-name bug class.
2. **Release model**: component versions with `major.minor <= core`; patch
   releases without a core tag; no empty releases; the core publishes a
   generated compatibility table (latest released SDK tags x core bundle,
   nightly). Rust's verifier and edge agent get their own tag streams.
3. **Capability tiers instead of feature parity**: verifier-only / thin
   client (Go, .NET), governed client (TS, Rust), edge (Rust); a generated
   capability matrix in the core docs; no more ports of the governed lifecycle
   without a named user.
4. **Repo hygiene from one template**: CODEOWNERS by area (validated in CI),
   PR template, CONTRIBUTING, `docs/architecture.md` with "where a change
   goes" recipes, `docs/adr/` for durable decisions (replacing "Decision N"
   in long plans), per-feature plan files, fragments for upgrade/history/phase
   docs (as `changelog.d`), one source for shared scripts, one source for SDK
   guides (core links instead of copies).
5. **Fail closed on unknown kinds/models** in every port (exhaustive tables,
   registry-literal tests); generated tables wherever a port mirrors the core.
6. **PR shape**: stages land as stacked PRs under ~1.5k non-generated lines;
   generated files marked `linguist-generated`.

Not standardised on purpose: API shape per language (Go `ctx/error`, .NET
`Async`/DI, Rust traits), internal layering per repo, test frameworks and
lint sets per ecosystem, coverage targets per repo, feature parity, and the
same-named-branch mechanism (replaced, not spread).

## 5. Track 2: structural changes per repository

Each lands as a short PR stack behind the Track 0 gate, alongside feature work.

**Core (Python)**
- Settings declared once (spec table -> `NASettings`, generated docs).
- Route metadata declared once (decorator -> surfaces, contract routes,
  OpenAPI with schemas, rate class, auth, the route manifest); blueprints
  auto-registered.
- `EntryKindSpec` registry + domain events from the evidence store; kinds
  migrate one per PR; the registry feeds the bundle's kind metadata.
- Typed registries for error codes and audit events.
- Switch lifecycle (format level instead of chained `EVIDENCE_*` booleans;
  removable at a major) and an upgrade support window.
- Decide the dormant packages (gossip, routing, transport, monitoring, node).
- Later: composition root with per-feature modules (after settings and kinds).

**sdk-rust**
- Cut the 4 cycle edges; layer test. `KindSpec` table (then generated).
- One deliberate breaking window: `#[non_exhaustive]`, a `Signer` trait
  (platform key stores), then semver-checks keeps it honest.
- Extract the offline crate (`genesis-mesh-trust`) the verifier depends on
  alone; the gateway can later reuse it.
- Edge agent: `lib.rs` + modules around `decision.rs`, a local-API route
  table, a database migration ladder before it leaves beta.

**gateway**
- Read the core's route manifest instead of scraping; generic table-driven
  forwarding test; split `tests/production.rs`.
- Console: view registry, shared helpers, `@ts-check`; one static-asset
  handler; `node --test`.
- `AuthorityClient`, thinner `execute`, `Services::build`, all settings in
  `Config`, policy hot reload.

**sdk-typescript**
- Exhaustive kind tables now (proven to turn a miss into a compile error);
  `KindSpec` later. Split `types.ts`, `evidence_store.ts`, `index.ts`.
- 2.0 shape: subpath exports (`./verify` isomorphic, `./node`, client).

**sdk-go, sdk-dotnet**
- Generic signed call + `Evaluate`, so the governed flow is reachable.
- Request contract check (then typed requests from the core schemas).
- Decide v2 / 2.0 outside lockstep while adoption is zero (Go: typed
  requests, deprecated fields removed; .NET: `Async` names, cancellation,
  `init` models, internals hidden, DI).

## 6. Decisions (accepted 2026-10-16)

Recorded in `docs/development/decisions/`:

1. 0001 Release model: a pinned contract bundle, not lockstep.
2. 0002 SDK capability tiers; Go and .NET as verifier plus thin client, one
   2.0 each outside lockstep.
3. 0003 Verification engine: independent ports driven by generated tables; a
   WebAssembly spike later.
4. 0004 Forward compatibility for unknown record kinds.
5. 0005 Feature-switch lifecycle and an upgrade support window.
6. 0006 Review: automatic Copilot review and review agents, no required
   human approval; auto-merge except flagged paths.
7. 0007 Dormant core packages are internal.

## 7. Order and measures

| Phase | Content | Done when |
|---|---|---|
| A (now) | Section 2 fixes; Track 0 items 1-4 and 7 in all repos | merge queue on in 6 repos; every required check stable; no skipped-as-green; the 8 fixes merged and live-smoked |
| B | Track 0 ratchets (API, architecture, coverage); Track 1 items 4-6; ADRs 1-7 decided | API diff and layer checks required in all repos; CODEOWNERS valid everywhere |
| C | Contract bundle v1 (vectors + kind metadata + error codes) and the release model | SDK CI checks a pinned bundle; no CI failure caused by another repo for a full release |
| D | Route manifest with schemas; gateway reads it; SDK route/request contract tests | gateway has no scraping; Go/.NET request contract checked |
| E | Track 2 per repo, one PR stack at a time | a new record kind = 1 spec + 1 validator per port; a new route = 1 decorated function; feature PRs under ~10 files with at most 2 shared |

Targets to measure at the end: files touched per feature (core today 14-18
shared -> at most 2); CI failures caused by other repos (today the majority ->
0); PR size (today 5k-23k -> under 1.5k non-generated); breaking changes
shipped outside a declared window (today several -> 0); tests skipped as
green (today proven in 3 repos -> 0).
