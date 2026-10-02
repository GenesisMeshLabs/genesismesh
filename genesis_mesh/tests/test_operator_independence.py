"""Runtime code depends on no Genesis Core service, key or identity.

docs/operators/exit-and-fork.md promises that an operator can leave or fork
without Genesis Core's approval. That holds only while the code has no
built-in endpoint, key or sovereign identity of Genesis Core or a managing
partner; this test fails if one appears.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]

# External URLs runtime code may contain, and why.
ALLOWED_URLS = {
    "https://www.w3.org/2018/credentials/v1": "W3C VC context (interop bridge)",
    "https://w3id.org/security/suites/ed25519-2020/v1": "W3C VC context (interop bridge)",
    "https://vault.azure.net": "Azure Key Vault resource for the operator's own vault",
    "https://docs.genesismesh.org/": "documentation link in the operator console; a link, never fetched",
}
URL = re.compile(r"""https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s"'<>)]*""")
FORBIDDEN = re.compile(r"genesismesh\.org|connectorzzz|genesis[-_ ]core", re.IGNORECASE)
# Names of Genesis Core or a partner may appear in CLI help text and in the
# documentation link; anywhere else in code they would be a built-in authority.
# A base64 Ed25519 public key literal (44 chars ending in "=").
KEY_LITERAL = re.compile(r"""["'][A-Za-z0-9+/]{43}=["']""")


def _runtime_files():
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE).parts
        if rel[0] == "tests" or "__pycache__" in rel:
            continue
        yield path


def _code_lines(path: Path):
    """Lines outside docstrings and comments, with their numbers."""
    in_doc = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        quotes = stripped.count('"""') + stripped.count("'''")
        if in_doc or (quotes and stripped[:3] in ('"""', "'''")):
            if quotes % 2 == 1:
                in_doc = not in_doc
            continue
        if stripped.startswith("#"):
            continue
        yield number, line


def test_no_external_service_endpoints_in_runtime_code():
    found = []
    for path in _runtime_files():
        for number, line in _code_lines(path):
            for url in URL.findall(line):
                if not any(url.startswith(allowed) for allowed in ALLOWED_URLS):
                    found.append(f"{path.relative_to(PACKAGE)}:{number}: {url}")
    assert not found, "external endpoint in runtime code:\n" + "\n".join(found)


def test_no_genesis_core_or_partner_identity_in_runtime_code():
    found = [f"{path.relative_to(PACKAGE)}:{number}: {line.strip()}"
             for path in _runtime_files() for number, line in _code_lines(path)
             if KEY_LITERAL.search(line)
             or (FORBIDDEN.search(line) and "help=" not in line and "docs.genesismesh.org/" not in line)]
    assert not found, "built-in authority in runtime code:\n" + "\n".join(found)
