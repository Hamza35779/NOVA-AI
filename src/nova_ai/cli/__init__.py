"""Command-line interface for NOVA AI (Click-based).

Command modules are loaded **lazily**: the eager imports used to cost ~3.3s
before Click even parsed ``--help`` (the digest command alone pulls the
whole hybrid-agent stack → ``openai``). With :class:`LazyGroup`, a command
module is only imported when its subcommand is actually invoked; ``--help``
and ``--version`` are nearly instant.
"""

from __future__ import annotations

import importlib
from typing import Any, Optional

import click

# Lazy commands that must not appear in --help / completion listings.
# They stay invocable by name (resolution goes through get_command, not
# list_commands), matching click's hidden=True semantics for eager commands.
# _bootstrap is an install.sh-internal helper; click's hidden=True on the
# command object is not enough here because format_commands() renders static
# _SHORT_HELP entries without importing the command (so it can't see the flag).
_HIDDEN_LAZY_COMMANDS = frozenset({"_bootstrap"})


class LazyGroup(click.Group):
    """A Click group that resolves subcommands by import on first use.

    ``commands`` maps command names to ``(module_name, attribute)`` pairs
    relative to ``nova_ai.cli``. Nothing is imported at decoration time, so
    ``nova --help`` / ``--version`` skip ~50 command modules entirely. A
    miss falls back to :meth:`click.Group.get_command` (still supporting
    any commands registered eagerly, e.g. deep-research-setup).
    """

    def __init__(
        self,
        *args: Any,
        command_map: Optional[dict[str, tuple[str, str]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._command_map: dict[str, tuple[str, str]] = command_map or {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(
            {*super().list_commands(ctx), *self._command_map}
            - _HIDDEN_LAZY_COMMANDS
        )

    def get_command(self, ctx: click.Context, cmd_name: str) -> Optional[click.Command]:
        """Import-on-demand for commands in the map; pass through otherwise."""
        if cmd_name in self._command_map:
            module_name, attr = self._command_map.pop(cmd_name)
            try:
                module = importlib.import_module(f"nova_ai.cli.{module_name}")
            except Exception as exc:  # noqa: BLE001 — never kill the CLI on a
                # broken optional command; mirror the deep-research guard.
                import logging

                logging.getLogger(__name__).debug(
                    "command %s unavailable: %s", cmd_name, exc
                )
                return None
            cmd = getattr(module, attr)
            # Cache on the group so repeat lookups skip the import machinery.
            # NOTE: del-then-add, never add-then-del: add_command writes into
            # self.commands while list_commands()/format_commands() iterate
            # _command_map — mutating both dicts mid-iteration raised
            # "dictionary changed size during iteration" under --help.
            self.add_command(cmd, cmd_name)
            return cmd
        return super().get_command(ctx, cmd_name)

    def format_commands(self, ctx: click.Context, formatter: Any) -> None:
        """Render the command list without importing lazy commands.

        Click's default ``MultiCommand.format_commands`` resolves every
        subcommand via ``get_command`` (importing ~50 modules) just to read
        ``short_help``. Lazy commands instead use the static ``_SHORT_HELP``
        table — only explicitly-invoked commands are ever imported.
        """
        commands = self.list_commands(ctx)
        if not commands:
            return
        limit = formatter.width - 6 - max(len(cmd) for cmd in commands)
        rows: list[tuple[str, str]] = []
        for subcommand in commands:
            help_text = self._short_help_for(ctx, subcommand, limit)
            if help_text is not None:
                rows.append((subcommand, help_text))
        if not rows:
            return
        with formatter.section("Commands"):
            formatter.write_dl(rows)

    def _short_help_for(
        self, ctx: click.Context, cmd_name: str, limit: int
    ) -> Optional[str]:
        """Short help for *cmd_name* without importing it, when possible."""
        if cmd_name in self._command_map:
            static = _SHORT_HELP.get(cmd_name)
            if static:
                return static[:limit]
            return f"Run `nova {cmd_name} --help`."
        cmd = super().get_command(ctx, cmd_name)
        if cmd is None:
            return None
        return (cmd.short_help or "")[:limit]


def _lazy_version(ctx: click.Context, _param: Any, value: Any) -> Any:
    """Version callback that avoids importing ``nova_ai`` (pulls the SDK).

    Reads the installed distribution metadata directly; falls back to a
    static string on lookup failure (import-time cost of ``nova_ai``
    dominates CLI startup, and ``--version`` must be instant).
    """
    if not value or ctx.resilient_parsing:
        return value
    try:
        from importlib.metadata import version as _pkg_version

        click.echo(f"nova, version {_pkg_version('nova-ai-pro')}")
    except Exception:  # noqa: BLE001 — version must never crash the CLI
        click.echo("nova, version 0.0.0+unknown")
    ctx.exit()


# name → (module under nova_ai.cli, attribute)
_COMMAND_MAP: dict[str, tuple[str, str]] = {
    "init": ("init_cmd", "init"),
    "ask": ("ask", "ask"),
    "chat": ("chat_cmd", "chat"),
    "serve": ("serve", "serve"),
    "model": ("model", "model"),
    "memory": ("memory_cmd", "memory"),
    "mine": ("mine_cmd", "mine"),
    "mcp": ("mcp_cmd", "mcp"),
    "opencode": ("opencode_cmd", "opencode"),
    "pearl": ("pearl_cmd", "pearl"),
    "plugin": ("plugin_cmd", "plugin"),
    "telemetry": ("telemetry_cmd", "telemetry"),
    "bench": ("bench_cmd", "bench"),
    "channel": ("channel_cmd", "channel"),
    "channels": ("channels_cmd", "channels"),
    "scheduler": ("scheduler_cmd", "scheduler"),
    "doctor": ("doctor_cmd", "doctor"),
    "agents": ("agent_cmd", "agent"),
    "workflow": ("workflow_cmd", "workflow"),
    "skill": ("skill_cmd", "skill"),
    "start": ("daemon_cmd", "start"),
    "stop": ("daemon_cmd", "stop"),
    "restart": ("daemon_cmd", "restart"),
    "status": ("daemon_cmd", "status"),
    "vault": ("vault_cmd", "vault"),
    "add": ("add_cmd", "add"),
    "operators": ("operators_cmd", "operators"),
    "eval": ("eval_cmd", "eval_group"),
    "host": ("host_cmd", "host"),
    "quickstart": ("quickstart_cmd", "quickstart"),
    "optimize": ("optimize_cmd", "optimize_group"),
    "feedback": ("feedback_cmd", "feedback_group"),
    "compose": ("compose_cmd", "compose"),
    "gateway": ("gateway_cmd", "gateway"),
    "tool": ("tool_cmd", "tool"),
    "train": ("train_cmd", "train"),
    "prove": ("prove_cmd", "prove"),
    "forge": ("forge_cmd", "forge"),
    "conversation": ("conversation_cmd", "conversation"),
    "oracle": ("oracle_cmd", "oracle"),
    "registry": ("registry_cmd", "registry"),
    "config": ("config_cmd", "config"),
    "scan": ("scan_cmd", "scan"),
    "connect": ("connect_cmd", "connect"),
    "digest": ("digest_cmd", "digest"),
    "dev-watch": ("dev_watch_cmd", "dev_watch"),
    "router": ("router_cmd", "router_cmd"),
    "voice": ("voice_cmd", "voice"),
    "clip": ("clip_cmd", "clip"),
    "screen": ("screen_cmd", "screen_group"),
    "canvas": ("canvas_cmd", "canvas_group"),
    "memory-wiki": ("memory_wiki_cmd", "memory_wiki_group"),
    "integrations": ("integrations_cmd", "integrations_group"),
    "self-update": ("self_update_cmd", "self_update"),
    "_bootstrap": ("_bootstrap", "bootstrap_cmd"),
    # Formerly eager "guarded import" fallbacks: deep_research_setup_cmd
    # alone cost ~0.9s (it pulls the connectors stack) on every CLI run.
    # LazyGroup.get_command keeps the guarded behavior — an import failure
    # logs at debug and the command is simply unavailable.
    "deep-research-setup": ("deep_research_setup_cmd", "deep_research_setup"),
    "research": ("deep_research_setup_cmd", "deep_research_setup"),
    "auth": ("auth_cmd", "auth"),
    "tunnel": ("tunnel_cmd", "tunnel"),
    "logs": ("logs_cmd", "logs"),
}


def _print_version(ctx: click.Context, _param: Any, value: bool) -> None:
    """Eager-flag ``--version`` handler (replaces click.version_option).

    click 8.5 dropped the ``callback=`` parameter of ``version_option``, so
    the previous wiring silently degraded to printing the static
    "0.0.0+unknown" placeholder on every invocation ("nova --version" and
    "pip show" disagreed). An eager flag option invokes a callback on all
    supported click versions and keeps the metadata lookup off the import
    path ("--version" stays instant).
    """
    if not value or ctx.resilient_parsing:
        return
    try:
        from importlib.metadata import version as _pkg_version

        click.echo(f"nova, version {_pkg_version('nova-ai-pro')}")
    except Exception:  # noqa: BLE001 — version must never crash the CLI
        click.echo("nova, version 0.0.0+unknown")
    ctx.exit()


@click.group(
    cls=LazyGroup,
    command_map=_COMMAND_MAP,
    help="NOVA AI — modular AI assistant backend",
    invoke_without_command=True,
)
@click.option(
    "--version",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=_print_version,
    help="Show the version and exit.",
)
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Top-level CLI group."""
    from nova_ai.cli.log_config import setup_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    setup_logging(verbose=verbose, quiet=quiet)

    # Check for updates on interactive commands. The banner is noise in
    # demo recordings of ``nova ask --research``, so skip it whenever
    # the research flag is in argv (cheap argv sniff — Click hasn't
    # parsed the subcommand's args yet at this point).
    import sys

    research_mode_active = "--research" in sys.argv
    if not quiet and ctx.invoked_subcommand and not research_mode_active:
        import threading

        from nova_ai.cli._version_check import check_for_updates

        # Run the PyPI version poll off the hot path: on a cache miss it does
        # a blocking urlopen (up to 3s) that otherwise delays every command,
        # notably `nova serve` startup (#263). It's best-effort and never
        # raises, and the nudge prints to stderr, so a daemon thread is safe —
        # for long-lived commands (serve) it finishes; for short commands that
        # exit first, the check is simply skipped this run (same as a miss).
        threading.Thread(
            target=check_for_updates,
            args=(ctx.invoked_subcommand,),
            daemon=True,
        ).start()

    # First-run guard — routes bare `nova` to chat or init.
    if ctx.invoked_subcommand is None:
        from nova_ai.cli._first_run import check_and_route

        check_and_route(ctx)


# Static short-help for lazy commands: rendered in `nova --help` without
# importing any command module. Extracted from each command's help docstring
# (first line); keep in sync when adding a command to _COMMAND_MAP.
_SHORT_HELP: dict[str, str] = {
    "logs": "Show NOVA AI log files (server daemon + CLI); -f to follow",
    "init": "Detect hardware and generate ~/.nova_ai/config.toml",
    "ask": "Ask Nova a question",
    "chat": "Start an interactive multi-turn chat session",
    "serve": "Start the OpenAI-compatible API server",
    "model": "Manage language models",
    "memory": "Manage the memory store",
    "mine": "Configure and run Pearl mining",
    "mcp": "Serve or inspect NOVA AI tools via MCP (e.g. for opencode)",
    "opencode": "Integrate opencode (AI coding agent) with NOVA AI models + tools",
    "pearl": "Access Pearl node, wallet, and RPC tools",
    "plugin": "Scaffold NOVA AI plugins",
    "telemetry": "Query and manage inference telemetry data",
    "bench": "Run inference benchmarks",
    "channel": "Manage messaging channels",
    "channels": "Manage messaging channels (iMessage/SMS via SendBlue, Slack)",
    "scheduler": "Manage scheduled tasks",
    "doctor": "Run diagnostic checks on your NOVA AI installation",
    "agents": "Manage persistent agents — create, inspect, chat, bind channels",
    "workflow": "Manage workflows — list, run, status",
    "skill": "Manage reusable skills",
    "start": "Start the NOVA AI server as a background daemon",
    "stop": "Stop the running NOVA AI server daemon",
    "restart": "Restart the NOVA AI server daemon",
    "status": "Show status of the NOVA AI server daemon",
    "vault": "Manage encrypted credentials",
    "add": "Add an MCP server configuration",
    "operators": "Manage operators — persistent, scheduled autonomous agents",
    "eval": "Evaluation framework — benchmark models, agents, and learning",
    "host": "Download (if needed) and serve a model locally",
    "quickstart": "Guided 5-step setup for new users",
    "optimize": "LLM-driven configuration optimization",
    "feedback": "Trace feedback management",
    "compose": "Compose, run, benchmark, and deploy NOVA AI configurations",
    "gateway": "Manage the NOVA AI multi-channel gateway",
    "tool": "Manage tools — list, inspect",
    "train": "Self-training: fine-tune a model from your own usage traces",
    "prove": "Prove whether a new model actually beats the incumbent on your traces",
    "forge": "Forge skills from your repeated multi-step tool workflows",
    "conversation": "Conversation trees: forks, sibling answers, preference pairs",
    "oracle": "Fleet Oracle: pooled, anonymized performance answers",
    "registry": "Inspect registered components — list registries, show entries",
    "config": "Inspect configuration — show loaded settings, hardware, and config files",
    "scan": "Audit your environment for privacy and security risks",
    "connect": "Manage connections (Gmail, Obsidian, opencode, etc.)",
    "digest": "Display and play the morning digest",
    "dev-watch": "Watch a build/test command and self-diagnose failures",
    "router": "Smart Model Router commands",
    "voice": "Start a voice conversation with Nova",
    "clip": "Clipboard AI — quickly summarize, translate, or explain clipboard content",
    "screen": "Screen perception and OCR tools",
    "canvas": "Manage interactive Canvas visual artifacts",
    "memory-wiki": "Manage structured Memory Wiki knowledge base",
    "integrations": "Manage app integrations, software connectors, and MCP servers (like Claude Desktop)",
    "self-update": "Upgrade NOVA AI to the latest release. Detects how you installed (pip, uv tool, editable git) and runs the right command. Use --check to only print the upgrade command without running it",
    "_bootstrap": "Internal helper used by install.sh — not for direct user invocation",
    "deep-research-setup": "Configure local deep-research sources (Obsidian vault, docs)",
    "research": "Run multi-hop deep research with citations",
    "auth": "Manage authentication credentials for connectors",
    "tunnel": "Expose the local API server via a Cloudflare Tunnel",
}


def main() -> None:
    """Entry point registered as ``nova`` console script."""
    import sys

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
    cli()


__all__ = ["LazyGroup", "cli", "main"]
