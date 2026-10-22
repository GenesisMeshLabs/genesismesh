"""The layer rules of AGENTS.md, enforced with a ratchet (docs/development/architecture.md).

Every import between ``genesis_mesh`` modules is read from the source (module
and function level; imports under ``if TYPE_CHECKING:`` are type-only and not
counted) and checked against the layer table below. The violations that
existed when the rules were first enforced are listed in the allowlists at
the end of this file. A test fails when

* an import breaks a rule and is not allowlisted (a new violation: fix it), or
* an allowlisted import no longer exists (remove it from the allowlist).

So the allowlists only shrink. Do not add to them: move the code instead
(docs/development/architecture.md says where a change goes).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from functools import cache
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent

#: The layer table, lowest first. A module may import modules of its own layer
#: and of the layers above it in this list, except where ``MAY_IMPORT`` says
#: otherwise. A module belongs to the longest name it equals or starts with
#: (``name.``); ``EXACT`` names match only themselves.
LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("foundation", ("genesis_mesh.strict_json",)),
    ("models", ("genesis_mesh.models",)),
    ("crypto", ("genesis_mesh.crypto",)),
    ("trust", ("genesis_mesh.trust",)),
    # The node runtime and the packages around it. The node runtime is dormant
    # (decision 0007); audit, guard, interop and observability are live.
    ("peripheral", tuple(f"genesis_mesh.{name}" for name in (
        "audit", "gossip", "guard", "interop", "monitoring", "node", "observability", "routing", "transport",
    ))),
    ("workflows", ("genesis_mesh.workflows",)),
    # Network Authority infrastructure: db*, auth, errors, settings, rate
    # limits, storage, key provider, operator console.
    ("na_service", ("genesis_mesh.na_service",)),
    ("services", ("genesis_mesh.na_service.services",)),
    ("routes", ("genesis_mesh.na_service.routes",)),
    # The composition root: builds the NA from everything below it.
    ("composition", (
        "genesis_mesh.na_service.server",
        "genesis_mesh.na_service.app_factory",
        "genesis_mesh.na_service.wsgi",
        "genesis_mesh.na_service.__main__",
    )),
    ("cli", ("genesis_mesh.cli",)),
)
EXACT = {"genesis_mesh": "foundation", "genesis_mesh.na_service": "composition"}
ORDER = [name for name, _ in LAYERS]
#: Routes adapt HTTP to services: they do not reach protocol logic (trust,
#: crypto) or workflows directly.
MAY_IMPORT = {"routes": {"foundation", "models", "na_service", "services", "routes"}}

ROUTES_DIR = PACKAGE / "na_service" / "routes"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@cache
def _modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.relative_to(PACKAGE).parts[0] != "tests"
    }


def _resolve(name: str) -> str:
    """The module an imported name lives in (``a.b.c`` -> ``a.b`` when ``c`` is not a module)."""
    modules = _modules()
    while name and name not in modules:
        name = name.rpartition(".")[0]
    return name


def _type_checking_only(tree: ast.AST) -> set[int]:
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            for child in node.body:
                skipped.update(id(n) for n in ast.walk(child))
    return skipped


@cache
def _imports() -> tuple[tuple[str, str, int], ...]:
    """Every (importer, imported module, line) inside the package."""
    found: list[tuple[str, str, int]] = []
    for module, path in _modules().items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skipped = _type_checking_only(tree)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for node in ast.walk(tree):
            if id(node) in skipped or not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                if node.level:
                    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                    source = ".".join(base + ([node.module] if node.module else []))
                else:
                    source = node.module or ""
                targets = [f"{source}.{alias.name}" for alias in node.names]
            for target in targets:
                if target == "genesis_mesh" or target.startswith("genesis_mesh."):
                    imported = _resolve(target)
                    if imported and imported != module:
                        found.append((module, imported, node.lineno))
    return tuple(found)


def layer_of(module: str) -> str | None:
    if module in EXACT:
        return EXACT[module]
    best: tuple[int, str] | None = None
    for layer, names in LAYERS:
        for name in names:
            if (module == name or module.startswith(name + ".")) and (best is None or len(name) > best[0]):
                best = (len(name), layer)
    return best[1] if best else None


def _allowed(importer: str, imported: str) -> bool:
    if importer in MAY_IMPORT:
        return imported in MAY_IMPORT[importer]
    return ORDER.index(imported) <= ORDER.index(importer)


def _where(importer: str, imported: str) -> str:
    lines = sorted({line for a, b, line in _imports() if (a, b) == (importer, imported)})
    path = _modules()[importer].relative_to(ROOT).as_posix()
    return f"{path}:{','.join(map(str, lines))}"


def _ratchet(found: set[tuple[str, str]], allowed: frozenset[tuple[str, str]], rule: str) -> None:
    new = sorted(found - allowed)
    gone = sorted(allowed - found)
    message = []
    if new:
        message.append(f"{rule}: new violations (move the code; docs/development/architecture.md says where):")
        message += [f"  {a} -> {b}  ({_where(a, b)})" for a, b in new]
    if gone:
        message.append(f"{rule}: fixed, so remove these lines from the allowlist in {Path(__file__).name}:")
        message += [f"  {a.removeprefix('genesis_mesh.')} {b.removeprefix('genesis_mesh.')}" for a, b in gone]
    assert not message, "\n".join(message)


def test_every_module_has_a_layer():
    unplaced = sorted(module for module in _modules() if layer_of(module) is None)
    assert not unplaced, (
        f"modules outside the layer table: {unplaced}; add them to LAYERS in "
        f"{Path(__file__).name} and to the table in docs/development/architecture.md"
    )


def test_imports_follow_the_layer_table():
    found = {
        (importer, imported)
        for importer, imported, _ in _imports()
        if not _allowed(layer_of(importer) or "", layer_of(imported) or "")
    }
    _ratchet(found, LAYER_ALLOWLIST, "layer rule")


def test_trust_modules_do_not_import_each_other():
    """A trust module imports models and crypto, not another trust module.

    A trust module is ``trust/<name>.py`` or the package ``trust/<name>/``;
    the ``trust`` package itself may re-export its modules.
    """
    def unit(module: str) -> str:
        return ".".join(module.split(".")[:3])

    found = {
        (importer, imported)
        for importer, imported, _ in _imports()
        if layer_of(importer) == layer_of(imported) == "trust"
        and importer != "genesis_mesh.trust"
        and unit(importer) != unit(imported)
    }
    _ratchet(found, TRUST_ALLOWLIST, "trust module rule")


def test_route_files_do_not_reach_the_database():
    """Routes call services; ``<anything>.db`` in a route file is a database call.

    A new route file has none; an allowlisted file keeps its count or lowers it
    (then lower the count here too).
    """
    counts: dict[str, int] = {}
    for path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "db")
        if count:
            counts[path.name] = count
    problems = [
        f"  {name}: {count} database calls, allowlisted {ROUTE_DB_ALLOWLIST.get(name, 0)}"
        for name, count in sorted(counts.items())
        if count > ROUTE_DB_ALLOWLIST.get(name, 0)
    ]
    if problems:
        problems.insert(0, "route files reach service.db: add a service method and call it instead")
    lowered = [
        f"  {name!r}: {counts.get(name, 0)},"
        for name, allowed in sorted(ROUTE_DB_ALLOWLIST.items())
        if counts.get(name, 0) < allowed
    ]
    if lowered:
        problems.append(f"fewer database calls in routes: lower ROUTE_DB_ALLOWLIST in {Path(__file__).name} to")
        problems += lowered
    assert not problems, "\n".join(problems)


def test_the_rules_see_the_import_graph():
    """The checks above are not vacuous: they read known edges and known rules."""
    edges = {(a, b) for a, b, _ in _imports()}
    assert ("genesis_mesh.trust.agreement", "genesis_mesh.models.agreement") in edges
    assert ("genesis_mesh.cli.support", "genesis_mesh.workflows.remote") in edges
    assert layer_of("genesis_mesh.na_service.routes.grants") == "routes"
    assert layer_of("genesis_mesh.na_service.services.grants") == "services"
    assert layer_of("genesis_mesh.na_service.db") == "na_service"
    assert layer_of("genesis_mesh.na_service") == "composition"
    assert not _allowed("models", "trust") and not _allowed("trust", "na_service")
    assert not _allowed("workflows", "cli") and not _allowed("routes", "trust")
    assert _allowed("services", "trust") and _allowed("routes", "services")


def _iter_pairs(text: str) -> Iterator[tuple[str, str]]:
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        importer, imported = line.split()
        yield f"genesis_mesh.{importer}", f"genesis_mesh.{imported}"


# ---------------------------------------------------------------------------
# Allowlists: the violations of 2026-10-16. They may only shrink.
# One "importer imported" pair per line, without the genesis_mesh. prefix;
# '#' starts a comment.
# ---------------------------------------------------------------------------

LAYER_ALLOWLIST = frozenset(_iter_pairs("""
models.canonical_registry             crypto
# The NA's /cli-reference page walks the live Click tree. Every NA entry point
# (genesis-mesh-na, wsgi, `genesis-mesh na start`, create_app) is itself
# imported by the CLI, so no composition root outside the cycle can inject
# the tree; it closes the only cli <-> na_service import cycle (15 modules).
na_service.operator_console.rendering cli.main
na_service.routes.agreement           trust.agreement
na_service.routes.attestations        trust
na_service.routes.boundary            trust.agreement
na_service.routes.boundary            trust.context.decisions
na_service.routes.boundary            trust.context.engine
na_service.routes.boundary_policy     trust.agreement
na_service.routes.boundary_policy     trust.context
na_service.routes.consensus           trust.consensus
na_service.routes.consensus           trust.justification
na_service.routes.data_usage          trust.data_usage
na_service.routes.disclosure          trust.agreement
na_service.routes.disclosure          trust.selective_disclosure
na_service.routes.discovery           crypto
na_service.routes.edge                crypto.node_auth
na_service.routes.evidence            trust.decision
na_service.routes.evidence            trust.evidence
na_service.routes.public              trust.evidence
na_service.routes.treaties            trust
na_service.routes.treaties            trust.treaty_lifecycle
node.__main__                         cli.node_cmd
workflows.db_migration                na_service.db
workflows.db_migration                na_service.services.evidence_store
workflows.proof                       na_service.db
"""))

TRUST_ALLOWLIST = frozenset(_iter_pairs("""
trust.agreement                       trust.decision
trust.agreement                       trust.evidence
trust.context.engine                  trust.justification
trust.context.gates                   trust.freshness
trust.decision                        trust.connectome
trust.delegation                      trust.agreement
trust.delegation                      trust.decision
trust.delegation                      trust.evidence
trust.evidence                        trust.decision
trust.evidence_store                  trust.grants
trust.evidence_store                  trust.remediation
trust.grants                          trust.context.attestation_basis
trust.grants                          trust.context.gates
trust.grants                          trust.context.policy
trust.grants                          trust.context.registry
trust.grants                          trust.evidence_store
trust.grants                          trust.out_of_band
trust.mediation                       trust.context.decisions
trust.mediation                       trust.invocation_token
trust.out_of_band                     trust.context.engine
trust.out_of_band                     trust.evidence_store
trust.out_of_band                     trust.grants
trust.out_of_band                     trust.remediation
trust.remediation                     trust.evidence_store
trust.remediation                     trust.out_of_band
trust.supply_chain                    trust.treaty
trust.treaty                          trust.attestation
"""))

ROUTE_DB_ALLOWLIST: dict[str, int] = {
    "admin.py": 14,
    "agreement.py": 9,
    "attestations.py": 13,
    "boundary.py": 4,
    "boundary_policy.py": 7,
    "consensus.py": 3,
    "data_usage.py": 5,
    "disclosure.py": 3,
    "discovery.py": 6,
    "enrollment.py": 16,
    "evidence.py": 3,
    "health.py": 5,
    "public.py": 2,
    "treaties.py": 19,
}
