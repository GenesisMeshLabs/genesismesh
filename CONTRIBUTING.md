# Contributing

Thank you for considering a contribution to Genesis Mesh.

The contributor guide lives in the documentation site:

- `docs/development/contributing.md`
- `docs/development/testing.md`
- `docs/development/security-policy.md`

Before opening a pull request, run:

```powershell
python -m pytest genesis_mesh/tests -v
python -m sphinx -b html -W docs docs/pages
```
