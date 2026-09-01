"""Genesis Mesh - Secure decentralized mesh networking with cryptographic trust chains."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("genesis-mesh")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0.56.0"
