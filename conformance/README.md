# Genesis Mesh Conformance Suite

Deterministic reference vectors for the Genesis Mesh protocol (v0.51.0+).

## Quick start

```bash
# Run all suites against the installed Python implementation
python conformance/runner.py

# Run one suite
python conformance/runner.py ibct

# Via pytest
pytest genesis_mesh/tests/test_conformance.py -v
```

## For alternative implementations

Load any `conformance/vectors/*.json` file.  For each vector:

1. Construct the objects described in `input` using the fixed key seeds.
2. Execute the relevant protocol operation.
3. Assert that your output matches every field in `expected`.

See [CONFORMANCE.md](CONFORMANCE.md) for the complete specification.
