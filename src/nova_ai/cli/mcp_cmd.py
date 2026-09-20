"""``nova mcp`` — expose NOVA AI tools over the Model Context Protocol."""

from __future__ import annotations

import click
from rich.console import Console


@click.group()
def mcp() -> None:
    """Serve or inspect NOVA AI tools via MCP (e.g. for opencode)."""


@mcp.command("serve")
@click.option(
    "--transport",
    type=click.Choice(["stdio"]),
    default="stdio",
    show_default=True,
    help="MCP transport (only stdio is supported).",
)
def mcp_serve(transport: str) -> None:
    """Serve NOVA AI tools on stdin/stdout (JSON-RPC 2.0).

    Pair with opencode: ``"mcp": {"nova-ai-tools":
    {"type": "local", "command": ["nova", "mcp", "serve"]}}``.
    """
    del transport  # only stdio exists; flag kept for forward compat
    import logging

    # Protocol traffic owns stdout — force every log record to stderr.
    logging.basicConfig(level=logging.WARNING, stream=__import__("sys").stderr)
    from nova_ai.mcp.server import MCPServer
    from nova_ai.mcp.stdio import serve_stdio

    raise SystemExit(serve_stdio(MCPServer()))


@mcp.command("tools")
def mcp_tools() -> None:
    """List the tools ``mcp serve`` would expose."""
    from rich.table import Table

    from nova_ai.mcp.server import MCPServer

    console = Console(stderr=True)
    server = MCPServer()
    table = Table(title="NOVA AI MCP tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description", max_width=100)
    for tool in server.get_tools():
        table.add_row(tool.spec.name, tool.spec.description)
    console.print(table)


__all__ = ["mcp"]
