# Code Architecture

How the `genesis_mesh` package is put together, which way its imports may
point, and where a change goes. The layer table below is the one
`genesis_mesh/tests/test_architecture.py` enforces; keep the two in step.
For the protocol's concepts, see {doc}`../concepts/architecture`.

## Package map

**Protocol core** (usable without the Network Authority)

| Package | Holds |
| --- | --- |
| `strict_json.py` | Strict JSON input for signed records and request bodies (refusal reasons shared with every SDK) |
| `models/` | Pydantic records and pure helpers (canonical JSON, digests, freshness); `canonical_registry.py` builds the field registry the SDKs check |
| `crypto/` | Ed25519 keys, signing, admin and node request signatures |
| `trust/` | Protocol logic, `create_*` / `verify_*`: treaties, attestations, agreements, decisions, evidence chains (`evidence_store.py`), out-of-band records, remediation, grants; `context/` is the boundary engine and its gate registry, `consensus/` the consensus proofs |
| `workflows/` | Multi-step orchestration over `trust/` for the CLI and tests: federation, remote proof, trust bundles, audit packs, database migration; `remote.py` makes signed calls to a Network Authority |

**Network Authority** (`na_service/`)

| Module | Holds |
| --- | --- |
| `server.py`, `app_factory.py`, `wsgi.py`, `__init__.py` | Composition root: `NetworkAuthorityService` builds the Flask app, the services and the blueprints from `NASettings` |
| `settings.py` | `NASettings` and `load_settings()`: the Network Authority's environment variables |
| `routes/` | One Flask blueprint per feature: parse, authenticate, rate-limit, call a service |
| `services/` | Application logic per feature (evidence store, out-of-band, remediation, grants, edge, audit packs, boundary policy, key history, agreements) |
| `db.py`, `db_*.py`, `storage/`, `migrations/` | `NADatabase` (one mixin per area), the SQLite and PostgreSQL backends, numbered migrations |
| `auth.py`, `errors.py`, `rate_limit.py`, `key_provider.py` | Request signatures, the error envelope, rate limits, the signing key |
| `operator_console/` | Operator pages, the surface catalog (`surfaces.py`), the OpenAPI document |

**Tools and the rest**

| Package | Holds |
| --- | --- |
| `cli/` | The `genesis-mesh` Click commands, one domain per `*_ops.py`; `ops.py` still holds `na`, `admin`, `join`, `send` and `status` itself and registers the other groups |
| `observability/`, `audit/`, `guard/`, `interop/` | Logging and redaction, the node's audit log, process-level mediation, JOSE/SPIFFE/VC bridges |
| `node/`, `transport/`, `routing/`, `gossip/`, `monitoring/` | The mesh node runtime. **Dormant** ({doc}`decisions/0007-dormant-packages`): no new features, and new work does not build on them without a decision. They are not listed in the public contract, but they still back stable surfaces: the `genesis-mesh join` and `dev up` commands and the image's `SERVICE_ROLE=node`. A change that breaks those is a breaking change. They still change for fixes: 1.5.0 changed `node/` for key succession. Internals: {doc}`module-structure` |

Outside the package: `conformance/` (vector generators, the runner, the
vectors the SDKs copy), `contract/public-surface.json` (the classified public
surface), `scripts/` (release, upgrade rehearsal, smoke), `interop/` (the
four-language scenario), `changelog.d/` and `upgrade.d/` (fragments folded at
release).

## Layers

Lowest first. A module may import its own layer and every layer listed
before it, except routes, which have their own list. Imports under
`if TYPE_CHECKING:` are type-only and not counted.

| Layer | Modules | May import |
| --- | --- | --- |
| foundation | `genesis_mesh` (the package), `strict_json` | foundation |
| models | `models/` | foundation |
| crypto | `crypto/` | models, foundation |
| trust | `trust/` | crypto, models, foundation; not another trust module |
| peripheral | `node/`, `transport/`, `routing/`, `gossip/`, `monitoring/`, `audit/`, `observability/`, `guard/`, `interop/` | trust and every layer before it |
| workflows | `workflows/` | peripheral and every layer before it |
| na_service | the rest of `na_service/` | workflows and every layer before it |
| services | `na_service/services/` | na_service and every layer before it |
| routes | `na_service/routes/` | **only** routes, services, na_service, models, foundation |
| composition | `na_service/server.py`, `app_factory.py`, `wsgi.py`, `__main__.py`, `na_service/__init__.py` | routes and every layer before it |
| cli | `cli/` | every layer |

Two more rules:

- **No trust module imports another.** A trust module is `trust/<name>.py`
  or a package `trust/<name>/`; a trust→trust import signals a missing
  abstraction (the `trust` package itself may re-export).
- **Route files make no database calls.** A route calls a service method;
  `<anything>.db` in `na_service/routes/` is a database call.

The violations of 2026-10-16 are allowlisted in the test (25 layer edges,
27 trust→trust edges, 114 database calls in 14 route files). The test fails
on a new violation and on an allowlisted one that is gone, so the lists only
shrink. The one import cycle between `cli` and `na_service` is
`operator_console/rendering.py` reading the Click tree for the
`/cli-reference` page; it stays allowlisted until the CLI reference is generated.

## Request flow

```{mermaid}
flowchart LR
    client["client / SDK"] --> route["routes/&lt;feature&gt;.py<br/>auth, rate limit, strict JSON body"]
    route --> service["services/&lt;feature&gt;.py<br/>NA rules"]
    service --> trust["trust/*<br/>verify, sign"]
    service --> db["db_*.py mixins<br/>SQLite / PostgreSQL"]
    service --> evidence["services/evidence_store.py<br/>append evidence"]
    trust --> models["models/*"]
    route --> errors["errors.py<br/>error envelope"]
```

1. `app_factory.build_app(NASettings)` (used by `genesis-mesh na start` and
   `wsgi.py`) or `server.create_app()` builds `NetworkAuthorityService`,
   which constructs the services and registers every blueprint.
2. A route checks the rate limit and the caller (`auth.py`: admin or node
   request signatures), reads the body with `errors.request_json_object()`
   (which parses with `strict_json`) and validates it into a model.
3. The route calls one service method. The service applies the NA's rules,
   verifies and signs through `trust/*`, reads and writes through
   `service.db`, records audit events and appends evidence.
4. A refusal raises an `ApiError` subclass with a stable code; `errors.py`
   renders the envelope with the request ID.

The CLI parses options in `cli/*` and calls `trust/*` offline or a workflow;
calls to a Network Authority go through `workflows/remote.py`. The SDKs read
the same records and refuse the same input: the conformance vectors pin both
sides.

## Where a change goes

Each recipe lists the files to touch and the test that fails when one is
missed. Where no test catches a miss, it says so; review checks those.
Every user-visible change also adds a `changelog.d/<version>/` fragment, and
an operator step an `upgrade.d/<version>/` fragment.

### An HTTP route

- `na_service/routes/<feature>.py`: the blueprint; a new file is registered
  in `routes/__init__.py` and `server.py` (`_register_blueprints`).
- `na_service/services/<feature>.py`: the logic, exported from
  `services/__init__.py` and constructed in `server.py`.
- `operator_console/surfaces.py`: the route's surface entry.
- `contract/public-surface.json` (route, level, new error codes), then
  `python scripts/render_public_contract.py`.
- Docs: `docs/api/trust-http.md` or `docs/reference/network-authority-api.md`,
  and `docs/stability.md` for a new surface.

Fails when missed: `test_na_public.py::test_surface_catalog_lists_every_registered_route`,
`test_public_contract.py` (`test_every_http_route_is_classified_with_its_methods`,
`test_every_error_code_is_listed`, `test_rendered_contract_page_is_current`),
`test_architecture.py` (a route importing `trust`/`crypto` or calling
`.db`). Docs: no test.

### A setting

- `na_service/settings.py`: the `NASettings` field and its parsing in
  `load_settings()`.
- `na_service/app_factory.py` (`build_app` passes it), `server.py`
  (`create_app`, `NetworkAuthorityService.__init__`: parameter, docstring,
  validation).
- `docs/reference/configuration.md`.

Fails when missed: nothing. A missed pass-through silently keeps the
default, so add a test that builds the app from the variable and observes
the NA, as
`test_local_governed_na.py::test_build_app_trusts_exactly_the_configured_proxies`
does.

### A database migration

- `na_service/migrations/NNN_<name>.sql`, numbered next after the highest,
  and `NNN_<name>.postgres.sql` when PostgreSQL needs other SQL.
- The `db_<area>.py` mixin (a new one joins `NADatabase`'s bases in
  `db.py`).
- `scripts/upgrade_rehearsal.py` when the rehearsal must exercise the new
  table; `upgrade.d/<version>/<name>.md` for the operator.

Fails when missed: `test_migration_numbering.py` (duplicate, gapped or
unnumbered files fail at load), the PostgreSQL job (dialect differences),
"Upgrade rehearsals" (an upgrade from every supported version).

### An evidence record kind

About 14 registration points today (a kind registry is planned in
`ops/plan-architecture.md`, Track 2):

- `models/evidence_store.py` (`EntryKind`) and the kind's model;
  `models/canonical_registry.py` (signed models, `OMIT_WHEN_NONE`);
  `models/key_succession.py` (`NA_RECORD_TIME_FIELDS`).
- `trust/evidence_store.py` (kind tables and the verifier's branch).
- `na_service/services/evidence_store.py` (retention),
  `services/audit_pack.py`, `workflows/audit_pack.py`.
- A migration when the entry-kind constraint changes (both dialects).
- `scripts/export_reference_corpus.py`; the conformance generator, then
  `python conformance/generate_vectors.py field_registry`.
- `contract/public-surface.json`, `docs/schemas/gm.evidence.event.v1.json`,
  `docs/reference/evidence-event-schema.md`; the SDK verifiers.

Fails when missed: `test_canonical_registry.py`
(`test_the_committed_registry_matches_the_models`,
`test_entry_kinds_are_the_models`), `test_conformance.py`,
`test_public_contract.py::test_every_signed_model_is_classified`. A missed
retention or audit-pack table is not caught by a dedicated test.

### A gate type

- A class implementing `ConfiguredGateType` and its entry in
  `BUILTIN_GATE_TYPES` (`trust/context/registry.py`); docs and tests.

Fails when missed: a policy naming a gate type that is not installed is
refused (`unknown_gate_type`), so the gate's own tests fail. This is the
seam to copy.

### A CLI command

- `cli/<domain>_ops.py`; a new top-level group is added in
  `cli/ops.py` (`register_operational_commands`) or `cli/main.py`.
- `contract/public-surface.json` (`cli_commands`), then
  `python scripts/render_public_contract.py`; `docs/reference/cli.md`.
- Logic beyond parsing goes in `workflows/` (never imported back by
  `workflows/`).

Fails when missed: `test_public_contract.py::test_every_cli_command_is_classified`
and `test_rendered_contract_page_is_current`; `test_architecture.py`
(`workflows` importing `cli`). `cli.md`: no test.

### A conformance suite

- A generator (`conformance/generate_vectors.py` or
  `conformance/<suite>_vectors.py`) and `conformance/vectors/<suite>.json`.
- A runner in `conformance/runner.py` (`SUITE_RUNNERS`);
  `conformance/CONFORMANCE.md`.
- `cmp` lines in `.github/workflows/interop.yml` and the copies and
  harnesses in the SDKs.

Fails when missed: `test_conformance.py` (a registered suite with no file
or a failing vector). A vector file with no runner is not run: register it.

### An error code

- The code at the raise site (`raise ConflictError(..., code="...")`), or a
  new `Literal` type added to `public_contract_support.error_codes()`.
- `contract/public-surface.json` (`error_codes`), the rendered contract
  page, and the route's docs.

Fails when missed: `test_public_contract.py::test_every_error_code_is_listed`.
A code built at run time escapes the scan: write it as a literal.

## Node runtime internals

The dormant mesh node runtime's internals (control plane, runtime dispatch,
transport connections) are on their own page.

```{toctree}
:maxdepth: 1

module-structure
```
