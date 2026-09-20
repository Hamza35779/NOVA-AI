"""MCP stdio transport — serve NOVA AI tools to MCP clients (e.g. opencode).

Reads newline-delimited JSON-RPC 2.0 requests from *stdin*, dispatches them
through :class:`nova_ai.mcp.server.MCPServer`, and writes responses to
*stdout*. Notifications (no ``id``) get no response, per spec.

Only ``stdout`` carries protocol traffic — logs go to ``stderr`` so the
byte stream stays parseable.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

from nova_ai.mcp.protocol import PARSE_ERROR
from nova_ai.mcp.server import MCPServer

logger = logging.getLogger(__name__)


def serve_stdio(
    server: MCPServer | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Run the stdio JSON-RPC loop until EOF. Returns process exit code."""
    from nova_ai.mcp.protocol import MCPRequest

    server = server if server is not None else MCPServer()
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            parsed: Any = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": PARSE_ERROR, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            stdout.flush()
            continue
        # Notifications carry no "id" → no response (JSON-RPC 2.0).
        if not isinstance(parsed, dict) or "id" not in parsed:
            logger.debug(
                "MCP notification ignored: %s",
                parsed.get("method") if isinstance(parsed, dict) else parsed,
            )
            continue
        try:
            request = MCPRequest.from_json(line)
        except (KeyError, TypeError, ValueError) as exc:
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": parsed.get("id"),
                        "error": {
                            "code": -32600,
                            "message": f"Invalid request: {exc}",
                        },
                    }
                )
                + "\n"
            )
            stdout.flush()
            continue
        try:
            response = server.handle(request)
        except Exception as exc:  # never kill the loop on a tool crash
            logger.warning("MCP handler error: %s", exc)
            response = None
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request.id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {exc}",
                        },
                    }
                )
                + "\n"
            )
            stdout.flush()
            continue
        stdout.write(response.to_json() + "\n")
        stdout.flush()
    return 0


__all__ = ["serve_stdio"]
