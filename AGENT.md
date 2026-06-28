# AGENT.md

Guidance for AI coding agents and human contributors working inside Genesis Mesh.

## Purpose

Genesis Mesh is a protocol for sovereign communities to establish, delegate,
recognize, and revoke trust across organizational boundaries. The core
primitive is portable trust.

This file is the operational rulebook for working in the codebase. It does
**not** restate the product strategy or roadmap. Public project direction lives
in the documentation site, especially `docs/development/roadmap.md`.

Maintainer planning files live under `ops/`. They explain release intent,
strategy, and roadmap context for maintainers, but `CHANGELOG.md`, GitHub
Releases, and the public docs remain the source of truth for shipped behavior.
Use this file for repository conventions and use the public docs for
project-facing guidance.

---

## Current Repo Layout

This is what exists today. Do not rename or reorganize these modules without
explicit instruction.

```text
genesis_mesh/
  __init__.py
  audit/         audit events, structured logging
  cli/           genesis-mesh CLI entry point and subcommands
  crypto/        Ed25519 keys, signing, verification
  gossip/        peer gossip and CRL propagation
  models/        Pydantic domain models (certificates, revocation, discovery)
  monitoring/    health and telemetry
  na_service/    Network Authority (Flask app, routes, db, migrations)
  node/          node runtime, peer manager, cert manager, discovery client
  routing/       distance-vector routing, envelopes, provenance
  tests/         unit + integration; pytest entry point
  transport/     Noise XX peer transport
  trust/         trust evaluation primitives

docs/            Sphinx documentation source
examples/        agent-network reference applications
infrastructure/  Terraform for Azure deployment
ops/             strategy.md, roadmap.md, go-to-market.md
```

The package name is `genesis_mesh` (underscore). The CLI command is
`genesis-mesh` (hyphen).

---

## Target Direction for New Code

The strategy/roadmap may call for new modules as portable-trust features land.
Do not create empty placeholder modules. Add directories only when the first
real model or service lands in them.

---

## Operator UI Surfaces

The Network Authority home page, Connectome page, and any future
human-readable operator pages are product surfaces, not incidental debug HTML.

When adding a new public route, operator route, CLI-managed operation, or trust
workflow, update the relevant human-facing operator surface unless there is a
clear reason not to expose it.

Operator UI pages must share one visual language: shell width, color tokens,
card styling, table styling, empty states, typography, and footer/help copy.
Do not create visually separate one-off HTML pages for new operator views.

Keep HTTP routes, CLI operations, and documentation links distinct. Do not make
CLI-only operations look like browser-callable endpoints.

---

## Architectural Principles

### 1. Protocol First

The protocol core must remain usable without any specific agent framework, LLM
provider, marketplace, cloud, or enterprise IdP. Cross-cutting application
concerns belong in `examples/` or in dedicated overlay modules, never in core.

### 2. Modular Boundaries — The Layer Rule

Each module has exactly one responsibility. The enforced layer rule is:

```
models/*              = Pydantic entities + pure data helpers only
                        (to_canonical_json, digest, is_fresh, threshold_met)
                        No crypto calls. No multi-step logic. No imports from trust/.

trust/*               = Protocol logic only
                        (create_*, verify_*, assess_*, check_*)
                        No Click imports. No HTTP. No formatting for display.
                        Trust modules may only import from models/ and crypto/.
                        Trust modules must NOT import from other trust modules
                        (trust→trust imports signal a missing abstraction).

cli/*                 = Click parsing + output only
                        One domain per file. Thin wrappers that call trust/*.
                        Multi-step workflow logic goes in workflows/*.
                        No protocol rules inline in command bodies.

na_service/routes/*   = HTTP adaptation only
                        Parse request → dispatch to na_service/services/* ���
                        return response. No domain validation inline.

na_service/services/* = NA application logic
                        Called by routes. May import trust/* and models/*.

workflows/*           = Multi-step orchestration across trust modules
                        Used by CLI commands and integration tests.
```

A file that does more than one of the above must be split before the plan
that introduced it ships.

Avoid mixing:

- crypto and HTTP handlers
- CLI parsing and business logic
- demo behavior and protocol rules
- provider selection and trust validation
- persistence and domain models

### 3. Domain Models Before Transport

Define clean Pydantic models in `models/` (or the new domain modules) first.
HTTP, CLI, and persistence are adapters on top.

### 4. Explicit Trust Decisions

Trust is never implicit. Every decision must be explainable: which issuer,
which sovereign, which policy, expiry, revocation state, trust path, audit
record.

Bad:

```python
if verify_attestation(attestation):
    allow()
```

Good:

```python
decision = trust_engine.evaluate(attestation, context)
if decision.allowed:
    allow(decision)
else:
    deny(decision.reason)
```

Return structured `TrustDecision` objects, not raw booleans.

### 5. Security-Sensitive Code Must Be Boring

Crypto, signing, verification, revocation, and identity code stays simple and
explicit. Do not be clever. Do not add hidden fallbacks. Do not silently
ignore invalid signatures, expired credentials, missing issuers, or failed
revocation checks. Security failures fail closed.

---

## Development Environment

**This is a Windows project.** The primary development environment is
Windows 11 with PowerShell. CI runs on Linux. Code must work on both.

- Use `pathlib.Path`, not POSIX-only paths
- Don't assume `python3.12` exists as a binary name — pre-commit cannot pin to
  it on Windows
- PowerShell syntax differs from bash: `$null` not `/dev/null`, `$env:VAR` not
  `$VAR`, backtick for line continuation, no `&&` pipeline chaining in
  Windows PowerShell 5.1
- Tests must pass on both platforms

---

## Pre-commit Gates

Every commit runs:

- `mypy genesis_mesh --ignore-missing-imports`
- `python -m compileall genesis_mesh -q`
- `python -m sphinx -b html -W docs docs/pages` (warnings are errors)
- standard whitespace, EOF, YAML, TOML, merge-conflict checks

Every `git push` additionally runs:

- `python -m pytest genesis_mesh/tests -q`

Install once per clone:

```bash
pip install -r requirements-dev.txt
pre-commit install --hook-type pre-commit --hook-type pre-push
```

**Never bypass hooks** (`--no-verify`, `--no-gpg-sign`) unless explicitly
asked. If a hook fails, fix the underlying issue.

---

## Secret Handling

- Real secrets live in `.env` (gitignored). Never commit `.env`.
- `.env.example` documents *shape only* — placeholders, never real values.
- Private keys, invite tokens, NA operator keys, and trust material must
  never be logged or written to test fixtures.
- Pre-commit's large-file and added-files checks are not a substitute for
  attention. Inspect what you stage.

---

## Portable Trust Implementation Scope

Portable-trust changes should support trust between separately administered
sovereigns:

**Prioritize:**

- `Sovereign` / trust-domain model
- `MembershipAttestation` model with role and status claims
- attestation signing, verification, expiry, revocation
- local recognition policy on the accepting sovereign
- trust evaluation between two sovereigns
- negative-path tests for every primitive

**Do not prioritize unless the roadmap explicitly brings it into scope:**

- billing, settlement, tokens
- marketplaces, reputation scoring
- semantic registries, complex governance UI
- broad agent framework features
- recognition treaties
- cross-sovereign revocation propagation
- Connectome visualization

When adding code, the question is always: *which release goal does this
support?* If unclear, do not add it.

---

## Coding Standards

### Python

- Modern Python (3.12+). Type hints on all public surfaces.
- Pydantic models for protocol payloads; dataclasses for internal state.
- Small functions, explicit return types, pure functions for verification.
- Dependency injection for services; settings passed in, not read from env at
  call sites.

Avoid:

- global mutable state
- hidden network calls inside domain logic
- broad `except Exception` (catch the specific error, fail closed)
- magic strings spread across modules
- circular imports — if two modules import each other, the boundary is wrong

### Imports

Absolute imports inside the package:

```python
from genesis_mesh.models.discovery import AgentDescriptor
from genesis_mesh.crypto.signing import verify_signature
```

### Configuration

Central settings loader. Do not scatter `os.environ.get(...)` calls through
domain code.

### Errors

Domain-specific exceptions. Useful to operators, no sensitive data leakage.

```python
InvalidSignatureError
ExpiredAttestationError
RevokedCredentialError
UnknownIssuerError
UnrecognizedSovereignError
TrustPolicyDeniedError
```

---

## Testing Requirements

Every trust primitive ships with tests in all of these categories:

**Unit** — signing, verification, expiry, revocation checks, policy
evaluation, serialization round-trip.

**Integration** — Network Authority enrollment, sovereign-to-sovereign trust
evaluation, attestation issue/verify flows, capability execution with trust
checks.

**End-to-end** — the full founding-demo motion from roadmap.md:

```text
Genesis Core endorses a member.
AI Research recognizes Genesis Core.
The member is accepted through portable trust.
Genesis Core revokes the member.
AI Research stops accepting the member.
```

**Negative paths** — required for every trust feature:

- invalid signature
- unknown issuer
- expired attestation
- revoked attestation
- unrecognized sovereign
- stale revocation state
- malformed payload
- replayed event
- missing required claim

Trust code is not complete until failure paths are tested.

### Test Naming

Describe the behavior, not the function under test:

```python
def test_accepts_member_attestation_from_recognized_sovereign(): ...
def test_rejects_attestation_after_issuer_revocation(): ...
def test_rejects_attestation_from_unknown_issuer(): ...
```

---

## CLI Design

CLI commands are thin wrappers around services:

```text
CLI -> service -> domain model -> store
```

Never put protocol logic inline in a CLI command body.

Expected portable-trust CLI surface should stay thin and service-backed:

```bash
genesis-mesh sovereign create
genesis-mesh sovereign show
genesis-mesh attest issue
genesis-mesh attest verify
genesis-mesh recognize add
genesis-mesh recognize list
genesis-mesh revoke credential
genesis-mesh trust explain
```

Every CLI action that changes trust state produces clear operator output and
an audit event.

---

## API and Transport

HTTP routes in `na_service/routes/` are adapters. They parse, dispatch to a
service, return a response. They do not contain protocol logic.

```python
@app.post("/attest")
def attest():
    command = IssueAttestationCommand.from_payload(request.json)
    result = attestation_service.issue(command)
    return result.to_response()
```

---

## Audit and Provenance

Trust-changing actions produce structured audit events:

- sovereign created
- member attested
- role delegated
- attestation revoked
- recognition policy added or removed
- treaty signed or revoked (v0.10+)
- trust decision evaluated
- capability execution allowed or denied

Each event includes type, issuer, subject, sovereign, timestamp, reason, trust
path when relevant. Never logs private keys, raw secrets, invite tokens, or
confidential payloads.

---

## Persistence

Storage lives behind interfaces. Business logic does not depend on a
particular backend:

```python
class AttestationStore(Protocol):
    def save(self, attestation: MembershipAttestation) -> None: ...
    def get(self, attestation_id: str) -> MembershipAttestation | None: ...
```

File, SQLite, and remote implementations are separate adapters.

---

## Capability Layer Rules

Capabilities are overlays on trust. Never bypass trust evaluation when
selecting a provider. A provider is selected only after node identity,
provider certificate, capability registration, trust status, revocation
state, and policy constraints are checked.

Capability demos in `examples/` must not redefine the core protocol.

---

## Agent Layer Rules

Agents in `examples/agent-network/` are demonstrators, not architecture. Agent
code must not define core trust rules. Agent examples should demonstrate
trust-aware discovery, provenance, failover after revocation, and capability
execution under policy — nothing more.

---

## Documentation Standards

Every major feature ships with:

- short explanation
- why it exists
- threat or failure case it addresses
- CLI example
- test command
- expected output

Avoid vague claims like *enterprise-grade*, *production-ready*, or *secure by
default* unless implementation and tests justify them.

Docs are Sphinx-based; warnings are errors (`-W`). Cross-reference syntax
must be correct or the pre-commit hook blocks the commit.

---

## Security Review Checklist

Before merging trust-related code:

- Are signatures verified?
- Are issuers checked?
- Are expiry dates checked?
- Are revocations checked?
- Is stale state handled?
- Are private keys protected?
- Are secrets excluded from logs?
- Are trust decisions auditable?
- Are negative tests present?
- Does the system fail closed?

---

## Definition of Done

A change is done only when:

- code is modular and types are clear
- unit, integration, and negative-path tests cover the behavior
- documentation is updated and Sphinx builds without warnings
- CLI or API behavior is understandable from output alone
- audit behavior is considered for trust-changing actions
- security-sensitive paths fail closed
- `pre-commit run --all-files` passes
- `pre-commit run --all-files --hook-stage pre-push` passes (full pytest)
- no unrelated roadmap scope was added in the same change

---

## Agent Behavior Rules

When acting as an AI coding agent in this repository:

1. Read this file and the linked strategy/roadmap docs before making changes.
2. Identify which release milestone the change supports.
3. Keep changes small and reviewable. Prefer two focused PRs over one mixed PR.
4. Preserve protocol boundaries. Do not mix demo code with core protocol code.
5. Add or update tests for every behavior change, including negative paths.
6. Prefer explicit Pydantic models over unstructured dictionaries on the wire.
7. Prefer services over inline logic in CLI commands and HTTP routes.
8. Do not introduce new runtime dependencies unless justified.
9. Do not add marketplace, token, billing, or reputation features before
   portable trust works.
10. Never weaken signature, revocation, or trust checks to make a demo pass.
11. Never skip pre-commit hooks. If a hook fails, fix the underlying issue.
12. If a shortcut is needed, mark it clearly as temporary and isolate it from
    core logic.
13. Confirm before destructive operations (force-push, branch deletion, schema
    drops, mass file moves). Approval once does not generalize.

---

## Current Strategic Focus

The next correct move is portable trust, not more capability demos:

```text
Sovereign A issues a membership attestation.
Sovereign B recognizes Sovereign A.
A member trusted by A is evaluated by B.
A revocation from A changes B's trust decision.
```

That is the proof Genesis Mesh is becoming a protocol for sovereign trust,
not just a network of connected nodes.
