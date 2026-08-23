"""CLI command group for managing app integrations, software connectors, and MCP servers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nova_ai.core.paths import get_config_dir

console = Console()

# Catalog of supported applications & software integrations
APP_CATALOG = {
    "Communication & Messaging": [
        {
            "id": "whatsapp",
            "name": "WhatsApp",
            "desc": "Send/receive WhatsApp messages via local Baileys Web QR bridge",
            "status": "Built-in",
        },
        {
            "id": "telegram",
            "name": "Telegram",
            "desc": "Telegram Bot API integration for group & direct messaging",
            "status": "Built-in",
        },
        {
            "id": "slack",
            "name": "Slack",
            "desc": "Slack bot & webhook integration for workspaces",
            "status": "Built-in",
        },
        {
            "id": "discord",
            "name": "Discord",
            "desc": "Discord bot integration for servers and DMs",
            "status": "Built-in",
        },
        {
            "id": "gmail",
            "name": "Gmail & Email (SMTP)",
            "desc": "Google Workspace & standard SMTP/IMAP email dispatch",
            "status": "Built-in",
        },
        {
            "id": "imessage",
            "name": "iMessage & SMS",
            "desc": "Native macOS Messages CLI bridge",
            "status": "Skill Available",
        },
        {
            "id": "msteams",
            "name": "Microsoft Teams",
            "desc": "Teams webhook and graph communication",
            "status": "Extension",
        },
    ],
    "Notes & Productivity": [
        {
            "id": "notion",
            "name": "Notion",
            "desc": "Read/write Notion databases, pages, and wikis",
            "status": "Skill Available",
        },
        {
            "id": "obsidian",
            "name": "Obsidian",
            "desc": "Access and edit local Markdown vault notes",
            "status": "Skill Available",
        },
        {
            "id": "apple_notes",
            "name": "Apple Notes",
            "desc": "Query and create Apple Notes on macOS",
            "status": "Skill Available",
        },
        {
            "id": "apple_reminders",
            "name": "Apple Reminders",
            "desc": "Manage Apple Reminders & lists",
            "status": "Skill Available",
        },
        {
            "id": "trello",
            "name": "Trello",
            "desc": "Manage boards, lists, and task cards",
            "status": "Skill Available",
        },
        {
            "id": "memory_wiki",
            "name": "Active Memory Wiki",
            "desc": "Persistent structured Markdown knowledge store",
            "status": "Active",
        },
    ],
    "Developer & Code Tools": [
        {
            "id": "github",
            "name": "GitHub",
            "desc": "Issues, PRs, workflow logs, and repo management",
            "status": "Skill Available",
        },
        {
            "id": "shell",
            "name": "Terminal & Shell",
            "desc": "Execute bash, PowerShell, and system commands safely",
            "status": "Built-in",
        },
        {
            "id": "python_debugpy",
            "name": "Python Debugger",
            "desc": "Inspect breakpoints and stack traces",
            "status": "Skill Available",
        },
        {
            "id": "docker",
            "name": "Docker Sandbox",
            "desc": "Run code in isolated container sandboxes",
            "status": "Built-in",
        },
    ],
    "Browser & Desktop Perception": [
        {
            "id": "screen_capture",
            "name": "Screen & OCR Perception",
            "desc": "Capture screen/active window with live OCR",
            "status": "Active",
        },
        {
            "id": "web_readability",
            "name": "Web Readability Extractor",
            "desc": "Extract clean markdown articles & tables from URLs",
            "status": "Active",
        },
        {
            "id": "playwright",
            "name": "Playwright Headless Browser",
            "desc": "Automate web browsing and page interactions",
            "status": "Built-in",
        },
        {
            "id": "canvas",
            "name": "Interactive Canvas",
            "desc": "Render dynamic HTML/Chart.js/Mermaid artifacts",
            "status": "Active",
        },
    ],
    "Media & Smart Devices": [
        {
            "id": "spotify",
            "name": "Spotify Player",
            "desc": "Search, play, and control Spotify music",
            "status": "Skill Available",
        },
        {
            "id": "sonos",
            "name": "Sonos Speakers",
            "desc": "Discover and control local Sonos audio",
            "status": "Skill Available",
        },
        {
            "id": "openhue",
            "name": "Philips Hue Lights",
            "desc": "Control smart lights and room scenes",
            "status": "Skill Available",
        },
        {
            "id": "onepassword",
            "name": "1Password CLI",
            "desc": "Retrieve credentials and secrets safely",
            "status": "Skill Available",
        },
    ],
}


def _get_integrations_file() -> Path:
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "integrations.json"


def _load_user_integrations() -> Dict[str, Any]:
    f = _get_integrations_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_user_integrations(data: Dict[str, Any]) -> None:
    f = _get_integrations_file()
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _truncate_at_word(text: str, max_len: int = 50) -> str:
    """Truncate to max_len without cutting mid-word."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    cutoff = text[:max_len]
    # Back up to the last space so words stay intact; guarantee progress.
    space_pos = cutoff.rfind(" ")
    if space_pos > 0:
        cutoff = cutoff[:space_pos]
    return f"{cutoff}..."


@click.group(name="integrations")
def integrations_group() -> None:
    """Manage app integrations, software connectors, and MCP servers (like Claude Desktop)."""
    pass


@integrations_group.command(name="list")
@click.option("--category", default=None, help="Filter by category name.")
@click.option(
    "--enabled-only",
    is_flag=True,
    default=False,
    help="Show only enabled integrations.",
)
@click.option(
    "--disabled-only",
    is_flag=True,
    default=False,
    help="Show only disabled integrations.",
)
def list_integrations(
    category: Optional[str], enabled_only: bool, disabled_only: bool
) -> None:
    """Browse all available application and software integrations."""
    user_config = _load_user_integrations()

    console.print(
        "\n[bold purple]NOVA AI — Application & Software Integrations[/bold purple]"
    )
    console.print(
        "[dim]Connect your favorite apps and tools for autonomous agent workflows.[/dim]\n"
    )

    for cat_name, apps in APP_CATALOG.items():
        if category and category.lower() not in cat_name.lower():
            continue

        table = Table(
            title=cat_name,
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
        )
        table.add_column("App ID", style="magenta", width=18)
        table.add_column("Application", style="bold white", width=24)
        table.add_column("Description", style="dim")
        table.add_column("State", style="green", width=16)

        shown_any = False
        for app in apps:
            app_id = app["id"]
            enabled = user_config.get(app_id, {}).get("enabled", False)
            if enabled_only and not enabled:
                continue
            if disabled_only and enabled:
                continue
            state_label = (
                "[bold green]● Enabled[/bold green]"
                if enabled
                else f"[dim]{app['status']}[/dim]"
            )
            table.add_row(app_id, app["name"], app["desc"], state_label)
            shown_any = True

        if not shown_any:
            continue

        console.print(table)
        console.print()


def _find_app(app_id: str) -> Optional[Dict[str, Any]]:
    """Look up an app by ID across all categories."""
    for apps in APP_CATALOG.values():
        for app in apps:
            if app["id"] == app_id:
                return app
    return None


@integrations_group.command(name="enable")
@click.argument("app_id")
def enable_integration(app_id: str) -> None:
    """Enable and configure an application integration."""
    app_id = app_id.lower().replace("-", "_")
    app_meta = _find_app(app_id)

    if not app_meta:
        console.print(
            f"[red]Error: Unknown application ID '{app_id}'. Run 'nova integrations list' to see all.[/red]"
        )
        return

    data = _load_user_integrations()
    data[app_id] = {"enabled": True, "name": app_meta["name"]}
    _save_user_integrations(data)

    console.print(
        f"[bold green]✓ Enabled integration with {app_meta['name']}![/bold green]"
    )
    console.print(
        f"[cyan]Tip:[/cyan] You can now ask Nova to interact directly with {app_meta['name']}."
    )


@integrations_group.command(name="disable")
@click.argument("app_id")
def disable_integration(app_id: str) -> None:
    """Disable an application integration."""
    app_id = app_id.lower().replace("-", "_")
    data = _load_user_integrations()
    if app_id in data:
        data[app_id]["enabled"] = False
        _save_user_integrations(data)
        console.print(f"[yellow]Disabled integration '{app_id}'.[/yellow]")
    else:
        console.print(f"[dim]Integration '{app_id}' was not enabled.[/dim]")


@integrations_group.command(name="setup")
def interactive_setup() -> None:
    """Interactive wizard to pick the apps and softwares you want to integrate with."""
    console.print(
        Panel(
            "[bold cyan]NOVA AI Integration Setup Wizard[/bold cyan]\nSelect which softwares you want Nova to interact with.",
            border_style="purple",
        )
    )

    data = _load_user_integrations()
    selected_count = 0

    for cat_name, apps in APP_CATALOG.items():
        console.print(f"\n[bold magenta]=== {cat_name} ===[/bold magenta]")
        for app in apps:
            app_id = app["id"]
            current_state = data.get(app_id, {}).get("enabled", False)
            default_prompt = "Y" if current_state else "n"

            resp = click.prompt(
                f"Integrate with {app['name']} ({_truncate_at_word(app['desc'], 50)})?",
                default=default_prompt,
                type=str,
            )
            if resp.lower() in ("y", "yes"):
                data[app_id] = {"enabled": True, "name": app["name"]}
                selected_count += 1
            else:
                if app_id in data:
                    data[app_id]["enabled"] = False

    _save_user_integrations(data)
    console.print(
        f"\n[bold green]✓ Setup complete! {selected_count} integrations configured and ready.[/bold green]"
    )


@integrations_group.command(name="status")
def status_report() -> None:
    """Show summary of currently active integrations."""
    user_config = _load_user_integrations()
    enabled = {k: v for k, v in user_config.items() if v.get("enabled")}

    if not enabled:
        console.print(
            "[dim]No integrations currently enabled. Run 'nova integrations setup' to configure.[/dim]"
        )
        return

    console.print(f"\n[bold green]Active Integrations: {len(enabled)}[/bold green]\n")
    for app_id, info in sorted(enabled.items()):
        name = info.get("name", app_id)
        console.print(f"  [green]●[/green] {name} ([cyan]{app_id}[/cyan])")

    total_available = sum(len(apps) for apps in APP_CATALOG.values())
    console.print(f"\n[dim]{len(enabled)}/{total_available} integrations active[/dim]")


__all__ = ["integrations_group"]
