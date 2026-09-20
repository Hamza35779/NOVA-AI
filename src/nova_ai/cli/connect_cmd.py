"""``nova connect`` -- manage data source connections."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


def _list_sources(registry: object) -> None:
    """Print a Rich table of registered connectors and their sync status."""
    console = Console()
    items = registry.items()  # type: ignore[attr-defined]

    if not items:
        console.print("[yellow]No connectors registered.[/yellow]")
        return

    table = Table(title="Connected Sources")
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")

    for key, connector_cls in items:
        # Try to instantiate with no args to check status (best-effort)
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            auth_type = getattr(connector_cls, "auth_type", "unknown")
        except Exception:  # noqa: BLE001
            status = "unknown"
            auth_type = getattr(connector_cls, "auth_type", "unknown")

        table.add_row(key, auth_type, status)

    console.print(table)


def _disconnect_source(registry: object, source: str) -> None:
    """Find and disconnect a registered source connector."""
    console = Console()

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    try:
        instance = connector_cls()
        instance.disconnect()
        console.print(f"[green]Disconnected {source}.[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to disconnect {source}: {exc}[/red]")


def _sync_sources(registry: object, source: str = "") -> None:
    """Sync one (or all) connected sources into the shared KnowledgeStore."""
    console = Console()

    from nova_ai.connectors.pipeline import IngestionPipeline
    from nova_ai.connectors.store import KnowledgeStore
    from nova_ai.connectors.sync_engine import SyncEngine

    # Aliases so tests can patch _connect_cmd.<Name> with create=True
    # (function-local imports aren't patchable by string target).
    _sync_engine_cls = SyncEngine
    _store_cls = KnowledgeStore
    _pipeline_cls = IngestionPipeline

    names = [source] if source else list(registry.keys())  # type: ignore[attr-defined]

    if source and not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        return

    store = _store_cls()
    engine = _sync_engine_cls(_pipeline_cls(store))

    any_connected = False
    for name in names:
        connector_cls = registry.get(name)  # type: ignore[attr-defined]
        try:
            instance = connector_cls()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed to create {name}: {exc}[/red]")
            continue

        try:
            connected = instance.is_connected()
        except Exception:  # noqa: BLE001
            connected = False
        if not connected:
            console.print(f"[yellow]{name}: not connected — run `nova connect {name}`.[/yellow]")
            continue

        try:
            count = engine.sync(instance)
            console.print(f"[green]{name}: synced {count} item(s).[/green]")
            any_connected = True
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{name}: sync failed: {exc}[/red]")

    if not names:
        console.print("[yellow]No connectors registered.[/yellow]")
    elif not any_connected and registry.items():  # type: ignore[attr-defined]
        console.print("[dim]Tip: connect a source first with `nova connect <source>`.[/dim]")


def _connect_opencode_wizard(
    yes: bool = False, model: str = "", local_only: bool = False
) -> None:
    """Interactive ``nova connect opencode`` flow.

    Mirrors the data-source options (API keys, Ollama): one guided place to
    install opencode, wire ``opencode.json`` to NOVA AI, and pick the model
    opencode talks to — interactive by default, ``--yes`` for scripted runs.
    """
    from nova_ai.opencode.config import (
        current_default_model,
        detect_opencode,
        install_opencode,
        opencode_version,
        set_default_model,
        write_project_config,
    )

    console = Console()
    console.print("[bold]NOVA AI ↔ opencode integration[/bold]\n")

    # 1/3 — CLI present?
    exe = detect_opencode()
    if exe:
        console.print(f"[green][1/3] opencode CLI: {opencode_version(exe)}[/green]")
    else:
        console.print("[yellow][1/3] opencode CLI: not found[/yellow]")
        if yes or click.confirm("Install opencode now?", default=True):
            ok, message = install_opencode()
            console.print(f"[green]{message}[/green]" if ok else f"[red]{message}[/red]")
            if not ok:
                console.print(
                    "[yellow]Continuing without the CLI — the config below "
                    "still works once you install it.[/yellow]"
                )
        else:
            console.print("[dim]Skipped install.[/dim]")

    # 2/3 — project config wired?
    path, reachable, models = write_project_config(".", local_only=local_only)
    console.print(
        f"[green][2/3] {path}: NOVA provider + MCP tools wired "
        f"(models: {', '.join(models)})[/green]"
    )
    if local_only:
        console.print(
            "[green]Local-only mode: cloud providers locked out, "
            "sharing disabled.[/green]"
        )
    if not reachable:
        console.print(
            "[yellow]NOVA server unreachable — start `nova serve` and re-run "
            "`nova connect opencode` to pick up live model IDs.[/yellow]"
        )

    # 3/3 — default model switch.
    wanted = (model or "").strip()
    if not wanted and not yes and reachable and len(models) > 1:
        current = current_default_model()
        if current:
            console.print(f"Current opencode default: [cyan]{current}[/cyan]")
        for i, mid in enumerate(models, 1):
            console.print(f"  [{i}] nova-ai/{mid}")
        pick = click.prompt("Default model (number, id, or Enter to keep)", default="")
        if pick.strip():
            try:
                wanted = models[int(pick.strip()) - 1]
            except (ValueError, IndexError):
                wanted = pick.strip()
    if wanted:
        ok, message = set_default_model(wanted)
        console.print(f"[green][3/3] {message}[/green]" if ok else f"[red]{message}[/red]")
    else:
        console.print("[green][3/3] default model: unchanged[/green]")

    console.print("\n[bold]Next steps[/bold]")
    console.print("  nova opencode launch              # TUI with NOVA models + tools")
    console.print('  nova ask --agent opencode "..."   # drive opencode from NOVA AI')
    console.print("  nova opencode model               # switch models anytime")


def _connect_source(registry: object, source: str, path: str = "") -> None:
    """Route connector setup by auth_type."""
    console = Console()

    if source == "opencode":
        _connect_opencode_wizard()
        return

    if not registry.contains(source):  # type: ignore[attr-defined]
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print(
            "[yellow]Available sources: "
            + ", ".join(list(registry.keys()) + ["opencode"])  # type: ignore[attr-defined]
            + "[/yellow]"
        )
        return

    connector_cls = registry.get(source)  # type: ignore[attr-defined]
    auth_type = getattr(connector_cls, "auth_type", "")

    if auth_type == "filesystem":
        # Filesystem connectors (e.g. Obsidian) need a path
        if not path:
            console.print(
                f"[red]{source} requires a --path argument (e.g. --path ~/vault).[/red]"
            )
            return
        try:
            instance = connector_cls(vault_path=path)
        except TypeError:
            try:
                instance = connector_cls(path)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Failed to create {source} connector: {exc}[/red]")
                return

        if instance.is_connected():
            console.print(f"[green]{source} connected at path: {path}[/green]")
        else:
            console.print(
                f"[red]{source}: path '{path}' does not exist or is not accessible."
                "[/red]"
            )

    elif auth_type == "oauth":
        # OAuth connectors — auto-open browser + catch callback
        from nova_ai.connectors.oauth import (
            get_client_credentials,
            get_provider_for_connector,
            run_connector_oauth,
            save_client_credentials,
        )

        try:
            instance = connector_cls()
            if instance.is_connected():
                console.print(f"[green]{source} is already connected.[/green]")
                return

            provider = get_provider_for_connector(source)
            if provider is None:
                console.print(f"[red]No OAuth provider configured for {source}.[/red]")
                return

            creds = get_client_credentials(provider)
            client_id = creds[0] if creds else ""
            client_secret = creds[1] if creds else ""

            if not client_id or not client_secret:
                console.print(f"[cyan]First-time setup for {source}.[/cyan]")
                console.print(
                    f"[yellow]Create an OAuth app at: {provider.setup_url}[/yellow]"
                )
                console.print(f"[dim]{provider.setup_hint}[/dim]")
                client_id = click.prompt("Client ID")
                client_secret = click.prompt("Client Secret")
                save_client_credentials(provider, client_id, client_secret)

            run_connector_oauth(source, client_id, client_secret)
            console.print(f"[green]{source} authorised successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]OAuth flow failed for {source}: {exc}[/red]")

    elif auth_type == "token":
        # Token-based connectors (e.g. Oura) — prompt for personal access token
        import json
        from pathlib import Path

        from nova_ai.connectors.oauth import save_tokens
        from nova_ai.core.config import DEFAULT_CONFIG_DIR

        try:
            instance = connector_cls()
            if instance.is_connected():
                console.print(f"[green]{source} is already connected.[/green]")
                return

            token = click.prompt(f"Enter your {source} personal access token")
            token_dir = Path(DEFAULT_CONFIG_DIR) / "connectors"
            token_dir.mkdir(parents=True, exist_ok=True)
            token_file = token_dir / f"{source}.json"
            token_file.write_text(json.dumps({"token": token}))
            save_tokens(source, {"token": token})
            console.print(f"[green]{source} connected successfully.[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Token setup failed for {source}: {exc}[/red]")

    else:
        # Generic / bridge connectors
        try:
            instance = connector_cls()
            connected = instance.is_connected()
            status = "connected" if connected else "disconnected"
            console.print(f"{source} status: {status}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Failed to connect {source}: {exc}[/red]")


@click.group(invoke_without_command=True)
@click.argument("source", required=False)
@click.option(
    "--list",
    "list_sources",
    is_flag=True,
    help="List connected sources and sync status.",
)
@click.option(
    "--sync",
    "trigger_sync",
    is_flag=True,
    help="Trigger incremental sync for all sources.",
)
@click.option(
    "--disconnect",
    "disconnect_source",
    default="",
    help="Disconnect a source.",
)
@click.option(
    "--path",
    default="",
    help="Path for filesystem connectors (e.g., Obsidian vault).",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Assume yes for prompts (used by 'connect opencode').",
)
@click.option(
    "--model",
    default="",
    help="Default model for 'connect opencode' (e.g., qwen3:8b).",
)
@click.option(
    "--local-only",
    is_flag=True,
    help="Private mode for 'connect opencode' (no cloud providers, no sharing).",
)
@click.pass_context
def connect(
    ctx: click.Context,
    source: str | None,
    list_sources: bool,
    trigger_sync: bool,
    disconnect_source: str,
    path: str,
    yes: bool,
    model: str,
    local_only: bool,
) -> None:
    """Manage connections (Gmail, Obsidian, opencode, etc.)."""
    # Lazy imports to avoid top-level side effects
    import nova_ai.connectors  # noqa: F401 — registers all connectors
    from nova_ai.core.registry import ConnectorRegistry

    if list_sources:
        _list_sources(ConnectorRegistry)
        return

    if trigger_sync:
        _sync_sources(ConnectorRegistry)
        return

    if disconnect_source:
        _disconnect_source(ConnectorRegistry, disconnect_source)
        return

    if source:
        if source == "opencode":
            _connect_opencode_wizard(yes=yes, model=model, local_only=local_only)
            return
        _connect_source(ConnectorRegistry, source, path=path)
        return

    # No arguments — show help
    click.echo(ctx.get_help())
