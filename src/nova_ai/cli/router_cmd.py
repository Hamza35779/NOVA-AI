from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from nova_ai.core.types import Message
from nova_ai.engine.router import SmartRouter
from nova_ai.engine.router_config import RouterConfig

console = Console()


@click.group(name="router")
def router_cmd() -> None:
    """Smart Model Router commands."""
    pass


@router_cmd.command(name="status")
def status() -> None:
    """Show current tier config and routing stats."""
    config = RouterConfig()

    console.print("\n[bold]Router Tiers[/bold]")
    tier_table = Table(show_header=True, header_style="bold magenta")
    tier_table.add_column("Tier")
    tier_table.add_column("Model")

    for tier, model in config.tiers.items():
        tier_table.add_row(tier, model)

    console.print(tier_table)


@router_cmd.command(name="test")
@click.argument("query")
def test_query(query: str) -> None:
    """Classifies the query and prints which tier/model would be used."""
    config = RouterConfig()

    router = SmartRouter(engine=None, config=config)  # type: ignore

    messages = [Message(role="user", content=query)]
    tier = router.classify_complexity(messages)
    model = config.tiers.get(tier, config.tiers[config.default_tier])

    console.print(f"[bold green]Query:[/bold green] {query}")
    console.print(f"[bold cyan]Classified Tier:[/bold cyan] {tier}")
    console.print(f"[bold yellow]Assigned Model:[/bold yellow] {model}")
