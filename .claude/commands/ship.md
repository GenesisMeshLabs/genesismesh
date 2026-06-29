# /ship — Genesis Mesh Release Skill

You are executing the Genesis Mesh release process. This skill drives a complete
release cycle: detect or draft a plan, implement it, enforce all production rules,
run the full gate suite, commit, tag, push, and create a GitHub release.

Work **fully automatically** — no pauses for confirmation unless a hard stop fires
or a vision violation is detected. Follow every phase in order.

---

## PHASE 0 — Pre-flight

Run all checks in parallel. Abort with a clear message if any fail.

```
git status --short
git branch --show-current
python --version
pip check
python -m pip_audit -r requirements.txt -r requirements-dev.txt
```

**Stop conditions:**
- Working tree dirty → list the unclean files and ask the user to stash or commit first.
- On `main` or `master` → tell the user to create a feature branch first.
  Branch names follow the `ops/{feature}` convention (e.g. `ops/typescript-sdk`).
- Python < 3.12 → halt.
- `pip check` non-zero → broken dependency metadata; halt.
- `pip_audit` finds CVEs → halt and list them; do not proceed until resolved.

---

## PHASE 1 — Load context

Read all of the following in parallel before writing a single line of code:

1. **AGENT.md** — the operational rulebook for this repo. Contains the enforced
   layer rule, modular boundaries, stable surface definition, and conventions that
   override everything else. Read this first.

2. **Memory files** — every `.md` file in
   `C:\Users\thaer\.claude\projects\c--Source-genesismesh\memory\` — apply the
   rules and conventions they describe throughout the entire run.

3. **All existing plan files** — `ops/plan-v*.md` — sorted by version, to
   understand release history, scope patterns, and what the next logical increment
   is.

4. **Prior version's commit diff** — run `git log --oneline -5` then
   `git diff <last-tag>..HEAD -- genesis_mesh/` to see concrete implementation
   patterns from the most recent release.

5. **CHANGELOG.md** — to understand entry format and confirm the last shipped version.

6. **docs/development/history.md** — to understand the history table structure and
   the "What Is True Today" section format.

7. **docs/stability.md** — to understand which symbols are already declared stable
   and what format new stable additions use.

---

## PHASE 2 — Determine the plan

### If an ops/plan-v*.md exists with unchecked success criteria:

Load that plan. It is the scope of this release.

### If NO unimplemented plan exists:

Draft a new plan by:

1. Reading all prior plan files to infer the next logical version and feature area.
2. Drafting `ops/plan-v{X.Y.Z}.md` using the standard template (see below).
3. **STOP and present the draft to the user.** Wait for explicit approval before
   continuing to Phase 3. This is the one mandatory pause — scope decisions belong
   to the human.

**Plan template:**

```markdown
# Plan v{X.Y.Z} — {Feature Name}

## Context

{One paragraph: why this release exists, what it unblocks, how it fits the
release sequence.}

## Scope

### In scope
- {concrete deliverable}

### Out of scope
- {explicit exclusion}

## Implementation

### {Section heading}

{Specific files, functions, and behaviours to implement.}

## Security notes

{Any signing, key-handling, or boundary constraints specific to this release.}

## Success Criteria

- [ ] {Verifiable criterion}

## Release Gate

- [ ] Version bumped to `{X.Y.Z}`
- [ ] CHANGELOG entry
- [ ] `docs/development/history.md` updated
- [ ] All tests pass
- [ ] Tag `v{X.Y.Z}`, push, GitHub release created
```

---

## PHASE 3 — Vision enforcement scans (run before writing code)

Run these scans now. A **hard stop** means: print the exact violating lines, do
not write a single file, and wait for the user to resolve the issue before
continuing.

### 3A — Layer rule
`trust/` must never import from `na_service/`. Grep:
```
grep -rn "from.*na_service" genesis_mesh/trust/
grep -rn "import.*na_service" genesis_mesh/trust/
```
If any matches: **HARD STOP** — layer boundary violated.

### 3B — Public boundary rule
Private key material must not leave `na_service/`. Grep new/changed files for:
```
grep -rn "na_private_key\|SigningKey\|private_key" genesis_mesh/ \
  --include="*.py" | grep -v "na_service\|tests\|crypto\|conftest"
```
If matches exist outside those paths: **HARD STOP** — private key crossed module boundary.

### 3C — Sovereign-first rule
No hardcoded sovereign IDs in implementation code. Grep new files for patterns like
`sovereign_id\s*=\s*["']` with literal string values that are not read from
`genesis_block`, config, or request input.
If matches: **HARD STOP** — hardcoded sovereign identity detected.

---

## PHASE 4 — Implementation

Follow the conventions in AGENT.md and the memory files loaded in Phase 1.
For every new file or changed file, also enforce:

### Route files (na_service/routes/)

Every route blueprint **must** have:

- Module docstring describing the routes in the file
- `logger = logging.getLogger(__name__)` at module level
- `create_*_blueprint(service)` factory with a one-line docstring
- `_rate_key(prefix: str) -> str` helper: `f"{prefix}:{request.remote_addr or 'unknown'}"`
- **Admin routes** (`/admin/...`):
  - `service.rate_limiter.allow(_rate_key("admin"), 30, 60)` before any logic
  - `service._verify_admin_request(data)` check
  - `service.db.add_audit_event("event_name", {...})` after every successful signing op
- **Public verify/prove routes**:
  - `service.rate_limiter.allow(_rate_key("{route_key}"), 60, 60)` before any logic
  - `service.db.add_audit_event("event_name", {...})` after every verification
- **No `str(exc)` in API error responses** — exceptions go to `logger.warning()` only;
  clients receive a descriptive message and stable `code` string
- **NA never signs a caller-provided pre-built model** — the NA constructs the
  canonical artifact from declared intent parameters, then signs it

### Model exports

Every model type used by new routes must be added to `genesis_mesh/models/__init__.py`
and its `__all__` list.

### Stable surface

If this release adds new stable CLI commands or Python API symbols (i.e. they are
intended to be stable after this release), add them to `docs/stability.md` with
the version they stabilize in, following the existing format in that file.

### Tests

Every new route must have at least:
- A test that the happy-path POST returns the expected status code (201 or 200)
- A test that a key field exists in the response body
- A test that the verification route validates a correctly built artifact
- Both suites must pass with `-W error::DeprecationWarning` — no deprecation warnings allowed

Place tests in `genesis_mesh/tests/test_na_{feature}.py` following existing conventions.

---

## PHASE 5 — Signing-call review

After writing code, scan every file you wrote for calls to `sign_model`,
`signing_key`, or any function whose name starts with `sign_` or `build_` that
calls a signing primitive internally.

For each such call, verify:
- The NA constructs the model from intent parameters declared in the request body
- The NA does NOT accept a pre-built model from the caller and sign it blindly
- If this invariant is violated: **HARD STOP** — describe the exact call and how
  to fix it before continuing.

---

## PHASE 6 — Gate suite (hard stops, run in order)

Each check must pass before the next runs. Never commit if any check fails.

### 6A — Unit tests (with deprecation-warning enforcement)
```
python -m pytest genesis_mesh/tests -q --tb=short -W error::DeprecationWarning -m "not integration"
```
Pass: all tests pass, zero warnings promoted to errors.
Fail: **HARD STOP** — show the full failing output (do not truncate with `tail`).

### 6B — Integration tests
```
python -m pytest genesis_mesh/tests/integration -v --tb=short -W error::DeprecationWarning -m integration
```
Pass: all integration tests pass.
Fail: **HARD STOP** — show the full failing output.

### 6C — Sphinx documentation build
```
python -m sphinx -W -b html docs docs/_build/html -q
```
Pass: exits 0, no warnings.
Fail: **HARD STOP** — show the warnings and fix them.

### 6D — mypy type check
```
python -m mypy genesis_mesh --ignore-missing-imports --no-error-summary 2>&1 | grep "error:"
```
Pass: zero `error:` lines.
Fail: **HARD STOP** — show all errors and fix them.

### 6E — Compile check
```
python -m compileall genesis_mesh -q
```
Pass: exits 0.
Fail: **HARD STOP** — syntax error in compiled bytecode.

### 6F — Dependency CVE scan
```
python -m pip_audit -r requirements.txt -r requirements-dev.txt
```
Pass: zero vulnerabilities.
Fail: **HARD STOP** — list CVEs; do not ship until resolved or explicitly acknowledged.

### 6G — Plan success criteria
Read `ops/plan-v{X.Y.Z}.md`. Every checkbox under "Success Criteria" and
"Release Gate" must be checked or checkable right now. If any is not,
implement what is missing, then re-run 6A–6F.
Mark all checkboxes as `[x]` once satisfied.

### 6H — CHANGELOG
`CHANGELOG.md` must contain an entry for `v{X.Y.Z}` above all prior versions.
If missing: write it following the format of prior entries (added/changed/fixed
sections, bullet points). Do NOT create a separate release-notes file.

### 6I — History
`docs/development/history.md` has four places to update when a version changes.
Update ALL FOUR:

1. **Phase table row** — e.g. `| J | v0.38.0 – v0.52.1 | ...` → update the
   upper bound to the new version.
2. **"What Is True Today" heading** — `As of v0.52.1:` → `As of v{X.Y.Z}:`.
3. **"not yet true" heading** — `As of v0.52.1, the following are *not* yet true:`
   → `As of v{X.Y.Z}, ...`.
4. **Test count sentence** — e.g. `1,088 tests pass.` → update the number with
   comma formatting (e.g. `1,134 tests pass.`). Run `python -m pytest --co -q`
   to get the exact count.

### 6J — SECURITY.md Supported Versions
Open `SECURITY.md` and check the Supported Versions table. If the new version
changes the supported minor or major version, update the table so that `{X.Y}.x`
shows `✅ Yes` and prior minors are marked accordingly. A patch release typically
does not change this table; a minor or major release does.

---

## PHASE 7 — Version bump

Edit `pyproject.toml`: set `version = "{X.Y.Z}"`.

---

## PHASE 8 — Commit

Stage only the files changed as part of this release (be explicit, never
`git add -A`).

**Commit message format:**

Choose the type based on what the release does:
- `feat({scope}):` — new feature or capability
- `fix({scope}):` — bug fix or security patch
- `chore({scope}):` — maintenance, cleanup, tooling (no new user-facing feature)
- `docs({scope}):` — documentation only

The scope is the primary area changed (e.g. `api`, `cli`, `conformance`, `security`,
`sdk`, `repo`). The title ends with `— v{X.Y.Z}` or `(v{X.Y.Z})` matching prior
style. The body lists 3–5 bullet points covering what actually changed.

```
git commit -m "$(cat <<'EOF'
{type}({scope}): {description} — v{X.Y.Z}

- {key change 1}
- {key change 2}
- {key change 3}

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Then tag:
```
git tag v{X.Y.Z}
```

---

## PHASE 9 — Push

```
git push origin HEAD
git push origin v{X.Y.Z}
```

The pre-push hook will run `pip-audit`, `cli-smoke`, and `pytest`. Wait for it to
complete before proceeding. If the hook fails: **HARD STOP** — do not create the
GitHub release until the push succeeds clean.

---

## PHASE 10 — GitHub release

```
gh release create v{X.Y.Z} \
  --title "v{X.Y.Z} — {Feature Name}" \
  --notes "$(cat <<'EOF'
## What's new

{3–5 bullet points summarising the release scope}

## Upgrade

\`\`\`bash
pip install genesis-mesh=={X.Y.Z}
\`\`\`

Full changelog: [CHANGELOG.md](CHANGELOG.md)
EOF
)"
```

Creating the release triggers `publish-pypi.yml` automatically. After ~2 minutes,
verify the package is live:
```
pip index versions genesis-mesh 2>/dev/null | head -3
```
Pass: `v{X.Y.Z}` appears in the version list.
Fail: check the Actions tab on GitHub for the publish workflow run.

---

## PHASE 11 — Memory update

Review the implementation just shipped. Identify any decisions, patterns, or
constraints that were **non-obvious** — things that would trip up a future
contributor who hadn't read the plan or this session. Write them as feedback or
project memory entries following the format in
`C:\Users\thaer\.claude\projects\c--Source-genesismesh\memory\`.

Update `MEMORY.md` with a pointer to any new memory file written.

---

## Summary output

After Phase 11, print a single summary block:

```
v{X.Y.Z} shipped.

Files changed: {count}
Tests: {N} passed ({unit} unit + {integration} integration)
Tag: v{X.Y.Z} pushed
GitHub release: {URL}
PyPI: verified / pending (check Actions)
Memory: {file written, or "none"}

Non-obvious decisions:
- {one per line}
```

Nothing else. The user can read the diff.

---

## Hard-stop escalation protocol

When any hard stop fires:

1. Print: `HARD STOP — {rule name}`
2. Print the exact violating lines or output (not a summary, not truncated).
3. State what must be fixed before `/ship` can continue.
4. Wait. Do not attempt a workaround. Do not continue automatically.
