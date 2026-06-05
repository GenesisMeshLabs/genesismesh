"""Command-line interface tools for Genesis Mesh."""

__all__ = ["cli"]


def __getattr__(name: str):
    """Load Click entry points lazily to keep ``python -m`` execution quiet."""
    if name == "cli":
        from .main import cli

        return cli
    raise AttributeError(name)
