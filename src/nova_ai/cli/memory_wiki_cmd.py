"""CLI command group for Memory Wiki."""

from __future__ import annotations

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from nova_ai.memory.wiki import MemoryWiki

console = Console()


@click.group(name="memory-wiki")
def memory_wiki_group() -> None:
    """Manage structured Memory Wiki knowledge base."""
    pass


@memory_wiki_group.command(name="list")
def list_topics() -> None:
    """List all available Memory Wiki topics."""
    wiki = MemoryWiki()
    topics = wiki.list_topics()

    table = Table(
        title="Memory Wiki Topics", show_header=True, header_style="bold magenta"
    )
    table.add_column("Topic Name", style="cyan")
    table.add_column("File", style="dim")

    for t in topics:
        table.add_row(t, f"{t}.md")

    console.print(table)


@memory_wiki_group.command(name="show")
@click.argument("topic", default="profile")
def show_topic(topic: str) -> None:
    """Display the contents of a Memory Wiki topic."""
    wiki = MemoryWiki()
    content = wiki.read_topic(topic)
    console.print(
        Panel(
            Markdown(content),
            title=f"[bold cyan]Memory Wiki: {topic}[/bold cyan]",
            border_style="purple",
        )
    )


@memory_wiki_group.command(name="add")
@click.argument("topic")
@click.argument("content")
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Overwrite the topic rather than appending.",
)
def add_entry(topic: str, content: str, replace: bool) -> None:
    """Add or append an entry to a Memory Wiki topic."""
    wiki = MemoryWiki()
    mode = "replace" if replace else "append"
    msg = wiki.write_topic(topic, content, mode=mode)
    console.print(f"[green]{msg}[/green]")


@memory_wiki_group.command(name="search")
@click.argument("query")
def search_wiki(query: str) -> None:
    """Search across all Memory Wiki topics."""
    wiki = MemoryWiki()
    results = wiki.search(query)

    if not results:
        console.print(f"[yellow]No matches found for '{query}'.[/yellow]")
        return

    console.print(f"\n[bold]Search results for '{query}':[/bold]\n")
    for r in results:
        console.print(
            f"[bold cyan]Topic: {r['topic']}[/bold cyan] ({len(r['matches'])} matches)"
        )
        for m in r["matches"]:
            console.print(f"  [dim]L{m['line']}:[/dim] {m['text']}")
        console.print()
