# Contributing

Genesis Mesh is under active hardening. Contributions should be small, scoped,
and backed by tests.

## Development Workflow

1. Create a virtual environment.
2. Install dev dependencies from `requirements-dev.txt`.
3. Install the pre-commit hooks once per clone.
4. Make the smallest coherent change.
5. Add or update tests.
6. Commit — pre-commit runs mypy, sphinx, compileall on every commit.
7. Push — pre-commit runs the test suite on every push.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pre-commit install --hook-type pre-commit --hook-type pre-push
```

To run the checks manually without committing:

```powershell
pre-commit run --all-files
pre-commit run --all-files --hook-stage pre-push
```

Or run the individual commands the hooks wrap:

```powershell
python -m pytest genesis_mesh/tests -v
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt -r requirements-dev.txt
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
