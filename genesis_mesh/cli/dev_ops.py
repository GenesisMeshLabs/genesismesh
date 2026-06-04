"""Local developer workflow commands for the Genesis Mesh CLI."""

from __future__ import annotations

import runpy
import shutil
from pathlib import Path

import click

from .config import PROJECT_CONFIG


@click.group()
def dev() -> None:
    """Run local developer workflows."""


@dev.command("up")
def dev_up() -> None:
    """Run the in-process local smoke workflow."""
    workflow_path = Path(__file__).resolve().parents[2] / "examples" / "test_workflow.py"
    if not workflow_path.exists():
        raise click.ClickException(f"Smoke workflow not found at {workflow_path}")
    smoke_main = runpy.run_path(str(workflow_path))["main"]
    smoke_main()


@dev.command("down")
def dev_down() -> None:
    """Remove local development artifacts created by `genesis-mesh init`."""
    locked_paths: list[str] = []
    generated_paths = [Path(".genesis-mesh"), Path(PROJECT_CONFIG)]
    generated_paths.extend(Path.cwd().glob(".node*"))

    for path in generated_paths:
        if path.exists():
            display_path = path
            if path.is_absolute():
                try:
                    display_path = path.relative_to(Path.cwd())
                except ValueError:
                    display_path = path
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                click.echo(f"Removed {display_path}")
            except PermissionError as exc:
                locked_paths.append(str(display_path))
                click.echo(f"Could not remove {display_path}: {exc}", err=True)

    if locked_paths:
        raise click.ClickException(
            "Some generated files are locked. Stop any running `genesis-mesh na start` "
            "or node runtime processes, then run `genesis-mesh dev down` again."
        )
