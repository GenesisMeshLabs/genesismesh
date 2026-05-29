"""Sphinx configuration for Genesis Mesh documentation."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

project = "Genesis Mesh"
author = "Genesis Mesh contributors"
copyright = "2026, Genesis Mesh contributors"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.mermaid",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
master_doc = "index"

html_theme = "furo"
html_title = "Genesis Mesh"
html_static_path: list[str] = []
exclude_patterns = [
    "_build",
    "pages",
    "plan.md",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]

autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = True
mermaid_version = "11.4.1"
