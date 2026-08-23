"""CLI command group for Canvas artifacts."""

from __future__ import annotations

import webbrowser

import click
from rich.console import Console
from rich.table import Table

from nova_ai.tools.canvas_tool import CanvasTool, _get_canvas_dir

console = Console()


@click.group(name="canvas")
def canvas_group() -> None:
    """Manage interactive Canvas visual artifacts."""
    pass


@canvas_group.command(name="list")
def list_canvas() -> None:
    """List all saved Canvas artifacts."""
    canvas_dir = _get_canvas_dir()
    files = sorted(
        canvas_dir.glob("canvas_*.html"), key=lambda p: p.stat().st_mtime, reverse=True
    )

    if not files:
        console.print("[dim]No Canvas artifacts created yet.[/dim]")
        return

    table = Table(
        title="NOVA AI Canvas Artifacts", show_header=True, header_style="bold cyan"
    )
    table.add_column("Artifact ID", style="magenta")
    table.add_column("File Path", style="dim")
    table.add_column("Modified", style="green")

    for f in files:
        artifact_id = f.stem.replace("canvas_", "")
        mtime = f.stat().st_mtime
        import datetime

        dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(artifact_id, str(f), dt_str)

    console.print(table)


@canvas_group.command(name="open")
@click.argument("artifact_id")
def open_canvas(artifact_id: str) -> None:
    """Open a Canvas artifact in your default browser."""
    canvas_dir = _get_canvas_dir()
    target = canvas_dir / f"canvas_{artifact_id}.html"
    if not target.exists():
        console.print(f"[red]Error: Canvas artifact '{artifact_id}' not found.[/red]")
        return

    console.print(f"[green]Opening {target.name}...[/green]")
    webbrowser.open(target.as_uri())


@canvas_group.command(name="render")
@click.argument("title")
@click.argument("html_content")
@click.option(
    "--open",
    "auto_open",
    is_flag=True,
    default=True,
    help="Automatically launch browser.",
)
def render_canvas(title: str, html_content: str, auto_open: bool) -> None:
    """Render a custom HTML/SVG snippet into a Canvas artifact."""
    tool = CanvasTool()
    res = tool.execute(title=title, html_body=html_content, auto_open=auto_open)
    if res.success:
        console.print(f"[bold green]✓[/bold green] {res.content}")
    else:
        console.print(f"[red]{res.content}[/red]")
