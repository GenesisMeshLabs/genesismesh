# /sdk-ship — Genesis Mesh SDK Release Skill

You are executing the Genesis Mesh SDK release process. This skill drives a
complete SDK release cycle: detect or draft a plan, implement it, enforce all
production rules, run the SDK gate suite, write all required documentation,
commit, tag, push, and create a GitHub release.

Work **fully automatically** — no pauses for confirmation unless a hard stop
fires or a vision violation is detected. Follow every phase in order.

---

## PHASE 0 — Pre-flight

Determine the target SDK directory from context or ask once if ambiguous:

| SDK | Directory |
|-----|-----------|
| TypeScript | `C:\Source\GenesisMeshLabs\sdk-typescript\` |
| Go | `C:\Source\GenesisMeshLabs\sdk-go\` |
| C# | `C:\Source\GenesisMeshLabs\sdk-cs\` |

Run all checks in parallel. Abort with a clear message if any fail.

**TypeScript:**
```sh
cd sdk-typescript
node --version      # must be ≥ 20
npm ci              # must exit 0
```

**Go (when applicable):**
```sh
cd sdk-go
go version          # must be ≥ 1.22
go mod tidy
```

**C# (when applicable):**
```sh
cd sdk-cs
dotnet --version    # must be ≥ 8
dotnet restore
```

**Stop conditions:**
- SDK directory does not exist → halt; the repo must be created first with a
  plan file in `genesismesh/ops/`.
- Runtime version below minimum → halt.
- Dependency install fails → halt and show the error.

---

## PHASE 1 — Load context

Read all of the following in parallel before writing a single line of code:

1. **`C:\Source\GenesisMeshLabs\AGENT.md`** — workspace topology and cross-repo rules.
2. **`sdk-{lang}/AGENT.md`** — the target SDK's layer rule, known NA constraints,
   and coding conventions. This overrides everything else for SDK-specific decisions.
3. **`genesismesh/AGENT.md`** — the protocol rules that apply to all SDKs.
4. **Memory files** — every `.md` file in
   `C:\Users\thaer\.claude\projects\c--Source-GenesisMeshLabs\memory\`.
5. **All existing plan files** — `genesismesh/ops/plan-v*.md` sorted by version,
   to understand release history and what the next increment is.
6. **`genesismesh/CHANGELOG.md`** — entry format and last shipped version.
7. **`genesismesh/docs/development/history.md`** — narrative structure.
8. **`genesismesh/docs/api/trust-http.md`** — the NA HTTP surface the SDK must
   implement. Use this as the authoritative source for route paths, request
   shapes, and response shapes.
9. **`genesismesh/docs/sdk/{lang}.md`** — the public SDK reference doc that must
   be kept in sync with the implementation.

---

## PHASE 2 — Determine the plan

### If an `ops/plan-vX.Y.Z.md` exists with unchecked success criteria:

Load that plan. It is the scope of this release.

### If NO unimplemented plan exists:

Draft a new plan by:

1. Reading all prior plan files to infer the next version.
2. Drafting `genesismesh/ops/plan-v{X.Y.Z}.md` using this template:

```markdown
# Plan v{X.Y.Z} — {Language} SDK

## Context

{One paragraph: which SDK, what NA surface it covers, what this unblocks.}

## Scope

### In scope
- {concrete deliverable: sub-clients, types, auth, tests, smoke test}

### Out of scope
- {explicit exclusion}

## Implementation

### Layer structure
{Files to create and their responsibilities.}

### Sub-clients
{List of domains and the NA routes each wraps.}

### Types
{Key interfaces and where they come from in the NA surface.}

### Tests
{Test structure: unit mocks + live smoke test.}

## Known NA constraints
{From sdk-typescript/AGENT.md "Known constraints" table — apply same constraints.}

## Success Criteria

- [ ] `sdk-{lang}/` builds cleanly
- [ ] All unit tests pass
- [ ] Smoke test passes against live 001-NA (all checks)
- [ ] `genesismesh/docs/sdk/{lang}.md` written or updated
- [ ] sdk-{lang}/README.md written
- [ ] sdk-{lang}/AGENT.md written

## Release Gate

- [ ] Version set to `{X.Y.Z}` in sdk-{lang} package manifest
- [ ] CHANGELOG entry in genesismesh/CHANGELOG.md
- [ ] history.md updated with v{X.Y.Z} entry
- [ ] Tag `v{X.Y.Z}`, push, GitHub release created
```

3. **STOP and present the draft to the user.** Wait for explicit approval before
   continuing to Phase 3.

---

## PHASE 3 — Vision enforcement scans

Run before writing any code. A **hard stop** means: print the exact violating
lines, write nothing, and wait for the user.

### 3A — Layer boundary

The SDK must not import from the Python main repo. Scan the SDK directory for
any path that crosses into `genesismesh/`:

```sh
grep -rn "genesismesh" sdk-{lang}/src/
```

If matches exist: **HARD STOP**.

### 3B — No direct signing in sub-clients

Sub-client files must not contain crypto primitives. Scan for key/sign/crypto
imports in sub-client files (everything except `auth.ts` / `auth.go` / `Auth.cs`):

**TypeScript:**
```sh
grep -n "createPrivateKey\|crypto\.sign\|Ed25519" sdk-typescript/src/ \
  --include="*.ts" | grep -v "auth.ts"
```

If matches: **HARD STOP** — signing belongs in the auth module only.

### 3C — Wire format consistency

Field names in type definitions must be snake_case matching the NA JSON API.
Scan for camelCase field names in type/interface/struct definitions:

**TypeScript:**
```sh
grep -n "readonly [a-z][a-zA-Z]*[A-Z]" sdk-typescript/src/types.ts
```

If matches: **HARD STOP** — use snake_case field names.

---

## PHASE 4 — Implementation

Follow the conventions in the SDK's AGENT.md and the constraints table.

### For every new sub-client

- One file per domain.
- Admin methods call the equivalent of `adminPost(path, params)`.
- Public methods call `publicPost(path, params)` or `publicGet(path)`.
- No signing logic inline.
- No URL construction beyond the route path string.
- Types match `genesismesh/docs/api/trust-http.md` field names exactly.

### For every new type

- snake_case field names.
- Required fields first, then optional with `?` / pointer / nullable.
- No helper methods on types — pure data only.

### For auth / signing

- `canonicalJson` must produce deterministic output matching Python's
  `json.dumps(value, sort_keys=True, separators=(",", ":"))`.
- Ed25519 seed handling: use the language's standard PKCS8 DER or equivalent
  import path. Do not use raw seed import if the runtime does not support it
  reliably (Node.js ≥ 22 requires PKCS8 DER with prefix `302e020100300506032b657004220420`).
- The four admin headers: `X-Admin-Key-Id`, `X-Admin-Signature`,
  `X-Admin-Timestamp`, `X-Admin-Nonce`.
- Signature payload: `canonicalJson({body, key_id, nonce, timestamp})`.

### Tests

Every public method needs:

- Happy-path test (mocked HTTP response → correct return type).
- URL path test (method calls the correct route).
- Admin header test (four `X-Admin-*` headers present on admin methods).
- Error test (NA returns 4xx → SDK throws typed error with correct `.code`).

---

## PHASE 5 — Smoke test

The smoke test is the live integration gate. It must pass against a real `001-NA`
instance before the release can proceed.

Location: `sandbox/sdk-smoke/` (adapt the TypeScript smoke test as a template).

Structure mirrors `sandbox/sdk-smoke/smoke.ts`:

1. Health check — `GET /healthz`
2. Attestation — issue + revoke (role prefix constraint)
3. Agreement — treaty → offer → accept → verify (treaty prerequisite constraint)
4. Boundary — decide → verify
5. Evidence — build → verify (verdict constraint)
6. Attestation policy — save recognition policy
7. Data usage — policy + intent + verify (DataSourceDescriptor constraint)

**Hard stop if any check fails.** Show the error, fix the root cause (wrong
field name, missing prerequisite, invalid enum value), then re-run.

If you discover a new NA constraint not in the SDK's AGENT.md "Known
constraints" table: add it there before continuing.

---

## PHASE 6 — Documentation (mandatory)

### 6A — SDK reference doc: `genesismesh/docs/sdk/{lang}.md`

Create or update. Structure mirrors `genesismesh/docs/sdk/typescript.md`:

- Install
- `{Client}` constructor options table
- Sub-client tables (method, admin y/n, description)
- Per-sub-client constraints
- Raw admin calls
- Error handling table
- Types overview
- Auth implementation notes (signing algorithm, wire format)
- Build and test commands

### 6B — SDK index: `genesismesh/docs/sdk/index.md`

Add the new SDK to the availability table (move from Planned → Available).
Update the toctree to include `{lang}`.

### 6C — SDK-specific README: `sdk-{lang}/README.md`

Quick-start, all 7 sub-client examples (matching the TypeScript README
structure), error handling, admin auth explanation, build commands.

### 6D — SDK-specific AGENT.md: `sdk-{lang}/AGENT.md`

Adapted from `sdk-typescript/AGENT.md`. Update:
- Repo layout for the new language
- Language-specific layer rule
- Language-specific signing implementation notes
- Known constraints table (same constraints, same format)
- Pre-commit / build equivalent for the language
- Coding standards for the language

### 6E — History narrative: `genesismesh/docs/development/history.md`

Add a narrative paragraph following the `**vX.Y.Z — Feature.**` format.
Include: which SDK, what NA surface it covers, the key technical decision
(language runtime + crypto approach), test count, what this opens.

### 6F — CHANGELOG: `genesismesh/CHANGELOG.md`

Add entry above all prior versions. Bullet points: SDK language, package name,
sub-clients covered, test count, smoke test result.

---

## PHASE 7 — Gate suite

Each check must pass before the next runs.

### 7A — Build

**TypeScript:**
```sh
cd sdk-typescript && npm run build
```

**Go:**
```sh
cd sdk-go && go build ./...
```

**C#:**
```sh
cd sdk-cs && dotnet build --configuration Release
```

Fail: **HARD STOP** — show full compiler output.

### 7B — Unit tests

**TypeScript:**
```sh
cd sdk-typescript && node --experimental-vm-modules node_modules/jest/bin/jest.js \
  --config jest.config.cjs
```

**Go:**
```sh
cd sdk-go && go test ./... -v
```

**C#:**
```sh
cd sdk-cs && dotnet test --verbosity normal
```

Fail: **HARD STOP** — show failing test output.

### 7C — Smoke test (live NA required)

```sh
cd sandbox/sdk-smoke && npm run smoke    # TypeScript reference
# or equivalent for the new SDK language
```

All checks must pass. Fail: **HARD STOP**.

### 7D — Plan success criteria

All checkboxes in `genesismesh/ops/plan-vX.Y.Z.md` must be `[x]`. Mark them.

### 7E — No staged secrets

```sh
git diff --cached -- "*.key" "*.pem" "*.env" "*private*" "*secret*"
```

No output. Fail: **HARD STOP**.

---

## PHASE 8 — Version bump

Update the version in the SDK package manifest to `X.Y.Z`:

| Language | File | Field |
|----------|------|-------|
| TypeScript | `sdk-typescript/package.json` | `"version"` |
| Go | `sdk-go/go.mod` | module path tag (set via git tag) |
| C# | `sdk-cs/{Project}.csproj` | `<Version>` |

---

## PHASE 9 — Commit

Stage files explicitly — never `git add -A`.

**TypeScript example:**
```sh
git add sdk-typescript/src/ sdk-typescript/tests/ sdk-typescript/package.json sdk-typescript/README.md \
        sdk-typescript/AGENT.md genesismesh/docs/sdk/ genesismesh/docs/index.md \
        genesismesh/CHANGELOG.md genesismesh/docs/development/history.md \
        genesismesh/ops/plan-vX.Y.Z.md
```

Commit from `genesismesh/` (the git root):

```sh
git commit -m "$(cat <<'EOF'
feat(sdk): ship {Language} SDK vX.Y.Z (Phase {K})

- {N} sub-clients covering all 7 Trust API domains
- {N} unit tests (mocked HTTP)
- Smoke test: {N}/{N} checks pass against live 001-NA
- auth: {key technical decision}
- types: snake_case field names matching NA JSON API

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Then tag:
```sh
git tag vX.Y.Z
```

---

## PHASE 10 — Push

```sh
git push origin main
git push origin vX.Y.Z
```

The pre-push hook runs `pip-audit`, `cli-smoke`, and `pytest`. Wait for it.
If the hook fails: **HARD STOP** — do not create the GitHub release.

---

## PHASE 11 — GitHub release

```sh
gh release create vX.Y.Z \
  --title "vX.Y.Z — {Language} SDK" \
  --notes "$(cat <<'EOF'
## {Language} SDK — `{package-name}`

{1-2 sentence summary: what the SDK is, what NA surface it covers.}

### Sub-clients

`agreement` · `attestation` · `boundary` · `consensus` · `dataUsage` · `disclosure` · `evidence`

### Quality

- **{N} unit tests** — all pass
- **Smoke test** — {N}/{N} checks pass against live 001-NA

### Install

\`\`\`{sh}
{install command}
\`\`\`

### Next

- v{X+1}.Y.0 — {Next SDK language} SDK
EOF
)"
```

---

## PHASE 12 — Memory update

Review decisions made during this release that are non-obvious or that
future contributors would not derive from reading the code.

Update `C:\Users\thaer\.claude\projects\c--Source-GenesisMeshLabs\memory\`
following the memory format (feedback, project, or reference type).
Update `MEMORY.md` index if a new file is written.

---

## Summary output

```
vX.Y.Z shipped — {Language} SDK.

Files changed: {count}
Tests: {N} unit + {N} smoke checks
Tag: vX.Y.Z pushed
GitHub release: {URL}
Docs: {list of doc files written/updated}
Memory: {file written, or "none"}

Non-obvious decisions:
- {one per line}
```

---

## Hard-stop escalation protocol

1. Print: `HARD STOP — {rule name}`
2. Print the exact violating lines or output (not a summary).
3. State what must be fixed before `/sdk-ship` can continue.
4. Wait. Do not attempt a workaround. Do not continue automatically.
