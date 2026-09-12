"""``nova plugin`` — scaffold new tools/agents/engines (P1-12)."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console


@click.group()
def plugin() -> None:
    """Scaffold NOVA AI plugins."""


@plugin.command("new")
@click.option("--kind", type=click.Choice(["tool", "agent"]), default="tool")
@click.option("--name", required=True, help="Plugin name (e.g. my-weather)")
@click.option("--dest", default="plugins", help="Output directory")
def plugin_new(kind: str, name: str, dest: str) -> None:
    """Scaffold a new plugin with tests."""
    from nova_ai.plugins.sdk import scaffold

    console = Console(stderr=True)
    target = scaffold(kind, name, Path(dest))
    console.print(f"[green]Created {target}[/green] + test stub")
    console.print(f"[dim]Register via pyproject [project.entry-points.\"nova_ai.{kind}s\"][/dim]")


__all__ = ["plugin"]
