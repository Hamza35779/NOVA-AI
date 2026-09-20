"""Tests for the MCP stdio transport (opencode ↔ NOVA AI tools)."""

import io
import json

from nova_ai.mcp.server import MCPServer
from nova_ai.mcp.stdio import serve_stdio


def _run_stdio(lines: list[str], server=None) -> list[dict]:
    stdin = io.StringIO("".join(lines))
    stdout = io.StringIO()
    code = serve_stdio(server, stdin=stdin, stdout=stdout)
    assert code == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_initialize_and_tools_list():
    responses = _run_stdio(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n",
        ],
        server=MCPServer(),
    )
    assert len(responses) == 2
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "nova_ai"
    assert responses[1]["id"] == 2
    names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert "calculator" in names


def test_notification_gets_no_response():
    responses = _run_stdio(
        [
            # No "id" → JSON-RPC notification → silence.
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}) + "\n",
        ],
        server=MCPServer(),
    )
    assert len(responses) == 1
    assert responses[0]["id"] == 7


def test_malformed_line_returns_parse_error_and_continues():
    responses = _run_stdio(
        [
            "this is not json\n",
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}) + "\n",
        ],
        server=MCPServer(),
    )
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 3


def test_unknown_method_returns_method_not_found():
    responses = _run_stdio(
        [json.dumps({"jsonrpc": "2.0", "id": 4, "method": "nope/nope"}) + "\n"],
        server=MCPServer(),
    )
    assert responses[0]["error"]["code"] == -32601


def test_tools_call_calculator_end_to_end():
    responses = _run_stdio(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "calculator", "arguments": {"expression": "6*7"}},
                }
            )
            + "\n",
        ],
        server=MCPServer(),
    )
    assert len(responses) == 1
    assert responses[0]["id"] == 5
    assert responses[0]["result"]["isError"] is False
    assert "42" in responses[0]["result"]["content"][0]["text"]


def test_unknown_tool_is_invalid_params():
    responses = _run_stdio(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "does_not_exist", "arguments": {}},
                }
            )
            + "\n",
        ],
        server=MCPServer(),
    )
    assert responses[0]["error"]["code"] == -32602
