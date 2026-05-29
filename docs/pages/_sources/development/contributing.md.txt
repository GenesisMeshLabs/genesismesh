# Contributing

Genesis Mesh is under active hardening. Contributions should be small, scoped,
and backed by tests.

## Development Workflow

1. Create a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Make the smallest coherent change.
4. Add or update tests.
5. Run the test suite.
6. Run type checking and dependency audit.
7. Build the documentation with warnings as errors.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest genesis_mesh/tests -v
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt
python -m sphinx -b html -W docs docs/pages
```

## Code Standards

- Keep security-sensitive behavior explicit.
- Prefer existing module boundaries over new abstractions.
- Use canonical JSON for signed payloads.
- Preserve docstrings on modules, classes, and functions.
- Do not commit generated keys, local databases, or docs build output.

## Pull Request Expectations

A good pull request explains:

- what changed
- why it changed
- how it was tested
- what security assumptions are involved
- whether follow-up work remains
