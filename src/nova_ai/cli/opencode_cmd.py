"""``nova opencode`` — install, configure, and launch opencode with NOVA AI.

Flow for a fresh machine::

    nova opencode setup     # guided wizard: install + init + model pick
    nova opencode install   # no-op when opencode is already present
    nova opencode init      # writes/merges ./opencode.json (NOVA provider+MCP)
    nova serve              # start the local backend (another terminal)
    nova opencode launch    # opens opencode TUI wired to NOVA AI

Environment integration: opencode inherits this process' environment, so
``NOVA_AI_API_KEY`` set for ``nova`` automatically applies inside opencode.
No secrets are ever written to ``opencode.json`` — the template references
``{env:...}`` placeholders only.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table


@click.group()
def opencode() -> None:
    """Integrate opencode (AI coding agent) with NOVA AI models + tools."""


@opencode.command("status")
@click.option(
    "--server-url",
    default="http://127.0.0.1:8000",
    show_default=True,
    help="NOVA AI server base URL to probe.",
)
def opencode_status(server_url: str) -> None:
    """Show opencode + NOVA AI integration health."""
    from nova_ai.opencode.config import (
        detect_opencode,
        fetch_server_models,
        opencode_version,
        server_health,
    )

    console = Console(stderr=True)
    table = Table(title="opencode ↔ NOVA AI status")
    table.add_column("Check", style="cyan")
    table.add_column("Result")

    exe = detect_opencode()
    if exe:
        table.add_row("opencode CLI", f"ok — {opencode_version(exe)} ({exe})")
    else:
        table.add_row(
            "opencode CLI",
            "missing — run `nova opencode install`",
        )

    if server_health(server_url):
        models = fetch_server_models(server_url) or []
        shown = (
            ", ".join(models[:5])
            + (f" (+{len(models) - 5} more)" if len(models) > 5 else "")
        )
        table.add_row(
            "NOVA server", f"ok — {server_url} ({shown or 'no models'})"
        )
    else:
        table.add_row(
            "NOVA server",
            f"unreachable — start it with `nova serve` ({server_url})",
        )

    cfg = Path("opencode.json")
    if cfg.is_file():
        table.add_row("Project config", f"ok — {cfg.resolve()}")
        from nova_ai.opencode.config import privacy_report

        report = privacy_report(cfg)
        for pid, residency, selectable in report["providers"]:
            if residency == "local":
                table.add_row(
                    f"Provider: {pid}",
                    "local — code never leaves this machine"
                    + ("" if selectable else " (disabled)"),
                )
            else:
                table.add_row(
                    f"Provider: {pid}",
                    "CLOUD — prompts leave this machine"
                    + ("" if selectable else " (disabled)"),
                )
        table.add_row(
            "Sharing",
            "disabled — transcripts stay local"
            if report["share"] == "disabled"
            else f"{report['share']} — /share uploads transcripts to opencode.ai",
        )
        if report["local_only"]:
            table.add_row("Privacy mode", "LOCAL-ONLY — cloud providers locked out")
    else:
        table.add_row(
            "Project config", "missing — run `nova opencode init`"
        )
    console.print(table)


@opencode.command("install")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the install command without running it.",
)
def opencode_install(dry_run: bool) -> None:
    """Install the opencode CLI when missing (no-op when present)."""
    from nova_ai.opencode.config import install_opencode

    console = Console(stderr=True)
    ok, message = install_opencode(dry_run=dry_run)
    console.print(
        f"[green]{message}[/green]" if ok else f"[yellow]{message}[/yellow]"
    )
    if not ok and not dry_run:
        raise click.exceptions.Exit(code=1)


@opencode.command("init")
@click.option(
    "--server-url",
    default="http://127.0.0.1:8000",
    show_default=True,
    help="NOVA AI server base URL (provider baseURL + model discovery).",
)
@click.option(
    "--no-mcp", is_flag=True, help="Skip wiring the nova-ai-tools MCP server."
)
@click.option(
    "--force-model",
    is_flag=True,
    help="Replace existing model/small_model with NOVA defaults.",
)
@click.option(
    "--local-only",
    is_flag=True,
    help="Private mode: lock opencode to the local NOVA provider and "
    "disable session sharing (code never leaves this machine).",
)
@click.option(
    "--dir",
    "directory",
    default=".",
    show_default=True,
    help="Directory to write opencode.json into.",
)
def opencode_init(
    server_url: str,
    no_mcp: bool,
    force_model: bool,
    local_only: bool,
    directory: str,
) -> None:
    """Write/merge opencode.json with the NOVA AI provider + MCP tools."""
    from nova_ai.opencode.config import write_project_config

    console = Console(stderr=True)
    path, reachable, models = write_project_config(
        directory,
        server_url=server_url,
        with_mcp=not no_mcp,
        force_model=force_model,
        local_only=local_only,
    )
    console.print(
        f"[green]Wrote {path}[/green] (models: {', '.join(models)})"
    )
    if local_only:
        console.print(
            "[green]Local-only mode: cloud providers locked out, "
            "sharing disabled.[/green]"
        )
    if not reachable:
        console.print(
            "[yellow]NOVA server unreachable — used starter model list. "
            "Start `nova serve`, pull a model, then re-run "
            "`nova opencode init` to pick up real model IDs.[/yellow]"
        )


@opencode.command("launch")
@click.argument("prompt", nargs=-1)
@click.option(
    "--server-url",
    default="http://127.0.0.1:8000",
    show_default=True,
    help="NOVA AI server base URL (warns when down).",
)
def opencode_launch(prompt: tuple[str, ...], server_url: str) -> None:
    """Launch opencode wired to NOVA AI (TUI, or headless with PROMPT).

    Examples::

        nova opencode launch                         # interactive TUI
        nova opencode launch "explain this repo"     # headless one-shot
    """
    import subprocess

    from nova_ai.opencode.config import detect_opencode, server_health

    console = Console(stderr=True)
    exe = detect_opencode()
    if not exe:
        console.print(
            "[red]opencode CLI not found. Run `nova opencode install` first.[/red]"
        )
        raise click.exceptions.Exit(code=1)
    if not Path("opencode.json").is_file():
        console.print(
            "[yellow]No ./opencode.json — run `nova opencode init` first "
            "(continuing with global config).[/yellow]"
        )
    if not server_health(server_url):
        console.print(
            "[yellow]NOVA server unreachable at "
            f"{server_url} — start it with `nova serve` in another terminal, "
            "or opencode will fail to reach NOVA models.[/yellow]"
        )
    cmd = [exe, "run", " ".join(prompt)] if prompt else [exe]
    raise SystemExit(subprocess.run(cmd).returncode)


@opencode.command("model")
@click.argument("model_id", required=False)
@click.option(
    "--list", "list_models", is_flag=True, help="List NOVA models and exit."
)
@click.option(
    "--server-url",
    default="http://127.0.0.1:8000",
    show_default=True,
    help="NOVA AI server base URL for discovery.",
)
def opencode_model(model_id: str | None, list_models: bool, server_url: str) -> None:
    """Show or change the default model opencode uses (NOVA AI provider).

    Examples::

        nova opencode model --list   # show available NOVA models
        nova opencode model          # interactive picker
        nova opencode model phi4:14b # switch default (prefix optional)
    """
    from nova_ai.opencode.config import (
        current_default_model,
        fetch_server_models,
        list_configured_models,
        set_default_model,
    )

    console = Console(stderr=True)
    server_models = fetch_server_models(server_url)
    configured = list_configured_models()
    choices = server_models or configured or ["qwen3:8b"]
    if server_models is None:
        console.print(
            "[yellow]NOVA server unreachable — showing models from "
            "opencode.json (run `nova serve` for the live list).[/yellow]"
        )
    current = current_default_model()
    if current:
        console.print(f"Current default: [cyan]{current}[/cyan]")

    if list_models:
        for mid in choices:
            console.print(f"  [cyan]nova-ai/{mid}[/cyan]")
        return

    if not model_id:
        console.print("Available NOVA models:")
        for i, mid in enumerate(choices, 1):
            console.print(f"  [{i}] nova-ai/{mid}")
        pick = click.prompt("Pick a model (number or id)", default="1")
        try:
            model_id = choices[int(pick) - 1]
        except (ValueError, IndexError):
            model_id = pick.strip()

    ok, message = set_default_model(model_id)
    console.print(
        f"[green]{message}[/green]" if ok else f"[red]{message}[/red]"
    )
    if not ok:
        raise click.exceptions.Exit(code=1)


@opencode.command("setup")
@click.option(
    "--server-url",
    default="http://127.0.0.1:8000",
    show_default=True,
    help="NOVA AI server base URL.",
)
@click.option("--no-mcp", is_flag=True, help="Skip wiring the MCP server.")
def opencode_setup(server_url: str, no_mcp: bool) -> None:
    """Guided setup wizard: install opencode, init config, pick model.

    Runs the full integration flow in one command:

    1. Install opencode CLI (skip if already present)
    2. Write/merge opencode.json with NOVA AI provider + MCP
    3. Start the server if needed
    4. Let the user pick a default model
    """
    from nova_ai.opencode.config import (
        fetch_server_models,
        install_opencode,
        server_health,
        write_project_config,
    )

    console = Console(stderr=True)
    console.print("[bold]NOVA AI ↔ opencode setup wizard[/bold]\n")

    # Step 1: Install opencode
    console.print("[cyan]Step 1/4: Installing opencode CLI...[/cyan]")
    ok, message = install_opencode()
    console.print(
        f"  {'[green]' if ok else '[yellow]'}{message}[/green]" if ok
        else f"  [yellow]{message}[/yellow]"
    )

    # Step 2: Write config
    console.print("\n[cyan]Step 2/4: Writing opencode.json...[/cyan]")
    path, reachable, models = write_project_config(
        server_url=server_url,
        with_mcp=not no_mcp,
        force_model=False,
    )
    console.print(f"  [green]Wrote {path}[/green] (models: {', '.join(models)})")

    # Step 3: Check server
    console.print("\n[cyan]Step 3/4: Checking NOVA server...[/cyan]")
    if server_health(server_url):
        console.print(f"  [green]Server running at {server_url}[/green]")
    else:
        console.print(
            f"  [yellow]Server not running at {server_url}[/yellow]"
        )
        console.print(
            "  [yellow]Start it with: python -m nova_ai.cli serve[/yellow]"
        )

    # Step 4: Pick model
    console.print("\n[cyan]Step 4/4: Default model selection...[/cyan]")
    server_models = fetch_server_models(server_url)
    if server_models:
        console.print("Available models:")
        for i, mid in enumerate(server_models, 1):
            console.print(f"  [{i}] nova-ai/{mid}")
        pick = click.prompt(
            "Pick a default model (number or id)",
            default="1",
        )
        try:
            chosen = server_models[int(pick) - 1]
        except (ValueError, IndexError):
            chosen = pick.strip()
        from nova_ai.opencode.config import set_default_model

        ok, msg = set_default_model(chosen)
        if ok:
            console.print(f"  [green]{msg}[/green]")
    else:
        console.print(
            "  [yellow]No models available — start the server and run "
            "`nova opencode model` to pick one.[/yellow]"
        )

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print(
        "Run [cyan]nova opencode launch[/cyan] to start opencode, or "
        "[cyan]nova opencode status[/cyan] to verify."
    )


@opencode.command("set-key")
@click.argument("provider", required=False)
@click.option(
    "--env",
    "env_name",
    default="",
    help="Environment variable name (overrides the provider default).",
)
def opencode_set_key(provider: str | None, env_name: str) -> None:
    """Store a provider API key in your user environment (never in a file).

    The key is prompted with hidden input, double-confirmed, and persisted
    via setx (Windows) or your shell rc file (macOS/Linux) — opencode.json
    keeps referencing it as {env:...}.

    Examples::

        nova opencode set-key b.ai        # rotate a leaked/exposed key
        nova opencode set-key openrouter
    """
    from nova_ai.opencode.config import PROVIDER_ENV_VARS, persist_env_var

    console = Console(stderr=True)
    known = PROVIDER_ENV_VARS
    if not provider:
        console.print("Known providers: " + ", ".join(sorted(known)))
        provider = click.prompt("Provider", default="b.ai")
    assert provider is not None
    name = env_name.strip() or known.get(provider.strip(), "")
    if not name:
        console.print(
            f"[red]Unknown provider '{provider}'. Use --env NAME "
            f"(known: {', '.join(sorted(known))}).[/red]"
        )
        raise click.exceptions.Exit(code=1)

    first = click.prompt(f"New {name} value", hide_input=True, confirmation_prompt=True)
    if not first or not first.strip():
        console.print("[red]Empty value — nothing stored.[/red]")
        raise click.exceptions.Exit(code=1)
    ok, message = persist_env_var(name, first)
    console.print(f"[green]{message}[/green]" if ok else f"[red]{message}[/red]")
    if provider.strip() == "b.ai":
        console.print(
            "[yellow]Rotation reminder: revoke the OLD key on the provider "
            "dashboard so a leaked copy stops working. opencode.json already "
            "reads {env:B_AI_API_KEY} — no file edit needed.[/yellow]"
        )
    if not ok:
        raise click.exceptions.Exit(code=1)


__all__ = ["opencode"]
