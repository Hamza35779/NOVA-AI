from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from nova_ai.tools.screen_capture import ScreenCaptureTool

console = Console()


@click.group(name="screen")
def screen_group() -> None:
    """Screen perception and OCR tools."""
    pass


@screen_group.command(name="capture")
@click.option(
    "--region",
    type=click.Choice(["full", "active_window"]),
    default="active_window",
    help="Region to capture.",
)
@click.option(
    "--output", type=click.Path(), default=None, help="Save screenshot to PATH."
)
def capture(region: str, output: str | None) -> None:
    """One-shot screenshot + OCR."""
    tool = ScreenCaptureTool()

    with console.status(f"Capturing {region}..."):
        result = tool.execute(region=region, extract_text=True)

    if not result.success:
        console.print(f"[red]Error:[/red] {result.error}")
        return

    data = result.data
    if data is None:
        console.print("[red]No data returned from tool[/red]")
        return

    text = data.get("text", "")

    if output:
        console.print(
            f"[yellow]Note:[/yellow] Saved screenshot to {output} (Not fully implemented but saving logic goes here)"
        )

    console.print(Panel(text, title="OCR Extracted Text", border_style="green"))


@screen_group.command(name="ask")
@click.argument("query")
@click.option("--model", default="default", help="Model to use.")
@click.option("--engine", default="default", help="Engine to use.")
def ask(query: str, model: str, engine: str) -> None:
    """Captures screen, adds OCR text as context, runs agent query."""
    tool = ScreenCaptureTool()

    with console.status("Capturing screen for context..."):
        result = tool.execute(region="active_window", extract_text=True)

    if not result.success:
        console.print(f"[red]Failed to capture screen:[/red] {result.error}")
        return

    data = result.data
    if data is None:
        console.print("[red]No data returned from tool[/red]")
        return

    screen_text = data.get("text", "")
    context = f"Screen contents OCR:\n{screen_text}\n\nUser Question: {query}"

    # Placeholder for running agent query
    console.print(
        f"[cyan]Agent Context prepared. Querying engine '{engine}' with model '{model}'...[/cyan]"
    )
    console.print(Panel(context, title="Prompt to Agent", border_style="blue"))
