# v0.17.8 Plan - API Error Contract Hardening

## Positioning

v0.17.8 is an adoption-readiness patch. It does not add a protocol primitive.
It removes another onboarding failure: API clients and operators should see
one safe, predictable error contract instead of route-specific JSON shapes or
Python tracebacks.

The release should prove this statement:

> Network Authority API failures are centralized, typed, safe to expose, and
> consistent across operator, node, discovery, treaty, attestation, and public
> surfaces.

## Scope

### In Scope

- [x] Add shared API exception classes for common HTTP failures.
- [x] Add one shared JSON error envelope with code, message, details, and
  request ID.
- [x] Add Flask-level exception handlers for typed API errors, framework HTTP
  errors, Pydantic validation errors, and unexpected exceptions.
- [x] Add request ID propagation through `X-Request-ID`.
- [x] Convert Network Authority route-level JSON error returns to typed
  business exceptions.
- [x] Sanitize unexpected server failures so stack traces, secrets, tokens,
  private keys, file paths, and internals are not exposed to API clients.
- [x] Keep CLI clients compatible with the new API error envelope.
- [x] Add API contract tests for 400, 401, 404, 409, 422, 429, 500, response
  shape consistency, request IDs, and leak prevention.
- [x] Update generated OpenAPI metadata and API reference documentation.

### Out Of Scope

- Protocol changes.
- New trust primitives.
- Browser request builders or try-it API execution.
- External operator adoption proof.

## Release Gate

Do not tag v0.17.8 until:

- [x] Full Python test suite passes.
- [x] Pre-commit passes.
- [x] Sphinx docs build passes with warnings treated as errors.
- [x] API error contract tests cover the shared envelope and leak prevention.
- [x] Network Authority route tests pass after conversion to the shared
  envelope.
- [x] Changelog and version metadata are updated.
