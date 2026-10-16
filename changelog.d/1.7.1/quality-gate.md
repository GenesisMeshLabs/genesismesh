### Changed

- **Contributor checks are stricter.** Pull requests merge through a merge
  queue that re-runs the checks on top of `main`. A pull request titled
  `fix: ...` that changes source files must change a test (the "Regression
  test" check; the Maintainer's label `no-test-needed` waives it). Tests that
  need PostgreSQL or nginx fail instead of skipping when `GM_E2E_REQUIRED=1`,
  as in the CI job that provides them. The interoperability check now also
  compares the Go and .NET SDKs' copies of the audit and grants conformance
  vectors, and fails when no Go conformance test matches its filter.
