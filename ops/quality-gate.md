# Track 0: the quality gate (all six repositories)

Goal: no PR can merge a regression that a test could have caught, and the few
that slip through are caught on the live hosts before the next step. Encoded in
rulesets, CI and templates, not in anyone's memory. Lands before any refactor.

## 1. Merge queue (GitHub)
- Enable the merge queue on `main` in each repo (ruleset rule
  `merge_queue`: merge method merge, build concurrency 5, group size 1 at
  first, all required checks).
- Every workflow that provides a required check also triggers on
  `merge_group:` (and keeps `pull_request:`). Path filters must not skip a
  required check on `merge_group` (use a "changes" job that always reports).
- Auto-merge (`gh pr merge --auto`) then enqueues; the queue re-tests the PR on
  top of main plus anything ahead of it, and ejects it on failure.

## 2. Required checks = everything protective
- One summary job per workflow family that always runs and fails if any member
  failed (e.g. core "Upgrade rehearsals" over the matrix, "Interop", "Edge
  scenarios"), so the ruleset lists stable names.
- Required in every repo: unit tests on all supported platforms, the live
  end-to-end run against a real NA (the SDKs' "SDK against core" and
  "Live contract"), the changelog check, the architecture check (ratchet),
  the API-compat check, CodeQL (ruleset code_scanning: high_or_higher), the
  dependency audit.
- Skipped is not green: live tests fail when CI expects them to run
  (`GM_E2E_REQUIRED=1`), vector compares fail for suites in the manifest.

## 3. Every fix carries a regression test
- PR template: "Bug fix: the test that fails without this change is ___".
- CI check "regression test": a PR whose title is `fix:` / `fix(...)` and
  touches source files must touch a test file, unless labelled
  `no-test-needed` (label only by the Maintainer; the check reports why).
- Reviewers (and review agents) run the new test against the parent commit.

## 4. One-way ratchets (fail CI if they get worse)
- Coverage on critical modules (core trust/, models/, services/evidence*;
  SDK verifiers; edge decision): measured per PR (pytest-cov, cargo-llvm-cov,
  c8, go test -cover, coverlet); the floor rises when coverage rises.
- Public API compatibility: core contract tests (existing);
  cargo-semver-checks; @microsoft/api-extractor report; golang.org/x/exp
  apidiff; Microsoft.CodeAnalysis.PublicApiAnalyzers. Breaking changes need
  a `breaking` label and a changelog "Upgrading" entry.
- Architecture rules: an allowlist of today's violations that may only shrink.

## 5. Deeper tests where a bug is a security bug
- Property-based tests (hypothesis, proptest, fast-check) and fuzz targets
  (cargo-fuzz / atheris) for canonical JSON, strict JSON, signature
  verification, envelope/record parsing: in CI as short runs, longer weekly.
- Scheduled mutation testing (mutmut / cargo-mutants / stryker) on the
  verifiers and the edge decision module; surviving mutants become issues.

## 6. After every merge (the Maintainer's standing rule)
- The agent runs the live smoke after auto-merged changes land, before the
  next step: sandbox smoke apps, the live run against the droplet (with
  temporary smoke keys), Azure public checks.
- Nightly scheduled live smoke against the droplet from CI (read-mostly, its
  own keys), alerting on failure.
- Main red = revert first, investigate after.

## 7. Releases in stages
- Release candidates (`vX.Y.Z-rc.N`) when a release changes migrations or
  signed formats; the droplet takes the release first; Azure follows after
  the droplet's live smoke passes.

## 8. Flaky tests
- A failed-then-passed run opens a "flaky" issue automatically; flaky tests
  are quarantined with an owner and a date, never silently retried.

## Rollout
One PR per repo on branch `chore/quality-gate` (flagged: workflows and
rulesets → the Maintainer merges). Order: merge_group triggers and summary
jobs first, then the merge-queue ruleset, then the PR template and
regression-test check, then the ratchets (coverage/API/architecture) with
their baselines, then fuzz/property/mutation jobs.
