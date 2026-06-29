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
python --version        # must be 3.12+
pip check               # must exit 0
git branch --show-current   # must NOT be main or master
```

If the working tree is dirty: **STOP** — list the unclean files and ask the user
to stash or commit them before running `/ship`.

If on `main` or `master`: **STOP** — tell the user to create a feature branch first.

---

## PHASE 1 — Load context

Read all of the following in parallel before writing a single line of code:

1. **Memory files** — Read every `.md` file in
   `C:\Users\thaer\.claude\projects\c--Source-genesismesh\memory\` and apply the
   rules and conventions they describe throughout the entire run.

2. **All existing plan files** — `ops/plan-v*.md` — to understand the release
   history, version numbering, scope pattern, and what the next logical increment
   is. Sort by version to determine the sequence.

3. **Prior version's commit diff** — run `git log --oneline -5` then
   `git diff <last-tag>..HEAD -- genesis_mesh/` to see concrete implementation
   patterns from the most recent release.

4. **CHANGELOG.md** — to understand entry format and confirm the last shipped version.

5. **docs/development/history.md** — to understand the history table format.

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

Follow the conventions loaded from memory (Phase 1). For every new file or
changed file, also enforce:

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

### Tests

Every new route must have at least:
- A test that the happy-path POST returns the expected status code (201 or 200)
- A test that a key field exists in the response body
- A test that the verification route validates a correctly built artifact

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

### 6A — Full test suite
```
python -m pytest -q --tb=short 2>&1 | tail -5
```
Pass: `N passed` with 0 failed and 0 errors.
Fail: **HARD STOP** — show the failing test output and wait for a fix.

### 6B — Sphinx documentation build
```
python -m sphinx -W -b html docs docs/_build/html -q 2>&1
```
Pass: exits 0, no warnings.
Fail: **HARD STOP** — show the warnings and fix them.

### 6C — mypy type check
```
python -m mypy genesis_mesh --ignore-missing-imports --no-error-summary 2>&1 | grep "error:"
```
Pass: zero `error:` lines.
Fail: **HARD STOP** — show all errors and fix them.

### 6D — Plan success criteria
Read `ops/plan-v{X.Y.Z}.md`. Every checkbox under "Success Criteria" and
"Release Gate" must be checked or checkable right now. If any is not,
implement what is missing, then re-run 6A–6C.
Mark all checkboxes as `[x]` once satisfied.

### 6E — CHANGELOG
`CHANGELOG.md` must contain an entry for `v{X.Y.Z}` above all prior versions.
If missing: write it following the format of prior entries (added/changed/fixed
sections, bullet points). Do NOT create a separate release-notes file.

### 6F — History
`docs/development/history.md` must show the new version in the history table
with the correct phase range and test count. Update it if needed.

---

## PHASE 7 — Version bump

Edit `pyproject.toml`: set `version = "{X.Y.Z}"`.

---

## PHASE 8 — Commit

Stage only the files changed as part of this release (be explicit, never
`git add -A`). Commit with a message that follows the project style seen in
`git log --oneline`:

```
git commit -m "$(cat <<'EOF'
chore(release): prepare v{X.Y.Z} ({Feature Name})

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Then tag:
```
git tag v{X.Y.Z}
```

---

## PHASE 9 — Push and GitHub release

```
git push origin HEAD
git push origin v{X.Y.Z}
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

---

## PHASE 10 — Memory update

Review the implementation just shipped. Identify any decisions, patterns, or
constraints that were **non-obvious** — things that would trip up a future
contributor who hadn't read the plan or this session. Write them as feedback or
project memory entries following the format in
`C:\Users\thaer\.claude\projects\c--Source-genesismesh\memory\`.

Update `MEMORY.md` with a pointer to any new memory file written.

---

## Summary output

After Phase 10, print a single summary block:

```
v{X.Y.Z} shipped.

Files changed: {count}
Tests: {N} passed
Tag: v{X.Y.Z} pushed
GitHub release: {URL}
Memory: {file written, or "none"}

Non-obvious decisions:
- {one per line}
```

Nothing else. The user can read the diff.

---

## Hard-stop escalation protocol

When any hard stop fires:

1. Print: `HARD STOP — {rule name}`
2. Print the exact violating lines or output (not a summary).
3. State what must be fixed before `/ship` can continue.
4. Wait. Do not attempt a workaround. Do not continue automatically.
