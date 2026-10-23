"""The test tree collects where POSIX-only names are missing (1.8.0).

The HA cluster helper used ``signal.SIGKILL`` as a default argument, which
is evaluated at import; Windows has no SIGKILL, so ``pytest genesis_mesh/tests``
stopped at collection there.
"""

from __future__ import annotations

import importlib
import signal
import sys

MODULE = "genesis_mesh.tests.integration.ha_cluster"


def test_ha_cluster_helper_imports_without_sigkill(monkeypatch):
    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)
    assert module.HACluster.kill.__defaults__ == (None,)
