"""API Tester tool — HTTP request builder and response validator for REST APIs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _format_response(
    status: int,
    headers: Dict[str, str],
    body: str,
    duration_ms: float,
    method: str,
    url: str,
) -> str:
    """Format HTTP response into a readable report."""
    lines = [
        "## HTTP Response",
        f"**{method.upper()} {url}**",
        f"**Status:** {status}",
        f"**Duration:** {duration_ms:.0f}ms",
        "",
        "### Headers",
    ]
    for k, v in sorted(headers.items()):
        lines.append(f"  - `{k}`: {v}")

    lines.append("")
    lines.append("### Body")

    # Try to pretty-print JSON
    try:
        parsed = json.loads(body)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        if len(pretty) > 6000:
            pretty = pretty[:6000] + "\n...[truncated]"
        lines.append(f"```json\n{pretty}\n```")
    except (json.JSONDecodeError, TypeError):
        preview = body[:4000] + "...[truncated]" if len(body) > 4000 else body
        lines.append(f"```\n{preview}\n```")

    return "\n".join(lines)


@ToolRegistry.register("api_tester")
class APITesterTool(BaseTool):
    """Send HTTP requests to REST APIs and validate responses."""

    tool_id = "api_tester"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="api_tester",
            description=(
                "Send HTTP requests (GET, POST, PUT, PATCH, DELETE) to REST API endpoints. "
                "Returns status code, headers, parsed body, and timing. "
                "Useful for API testing, health checks, and webhook debugging."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL of the API endpoint.",
                    },
                    "method": {
                        "type": "string",
                        "enum": [
                            "GET",
                            "POST",
                            "PUT",
                            "PATCH",
                            "DELETE",
                            "HEAD",
                            "OPTIONS",
                        ],
                        "description": "HTTP method to use.",
                        "default": "GET",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Custom HTTP headers as key-value pairs.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Request body (JSON string for POST/PUT/PATCH).",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Request timeout in seconds.",
                        "default": 15,
                    },
                    "expected_status": {
                        "type": "integer",
                        "description": "Optional expected status code for validation.",
                    },
                },
                "required": ["url"],
            },
            category="development",
            timeout_seconds=30.0,
        )

    @track_execution("api_tester")
    def execute(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
        timeout_seconds: float = 15,
        expected_status: Optional[int] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not url:
            return ToolResult(
                tool_name="api_tester", content="Error: URL is required.", success=False
            )

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                tool_name="api_tester",
                content=f"Invalid URL scheme: {parsed.scheme}. Use http or https.",
                success=False,
            )

        try:
            import httpx
        except ImportError:
            return ToolResult(
                tool_name="api_tester",
                content="httpx is required. Install with: pip install httpx",
                success=False,
            )

        method = method.upper().strip()
        req_headers = {
            "User-Agent": "NOVA-AI-APITester/1.0",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        # Auto-set Content-Type for POST/PUT/PATCH with body
        if (
            body
            and method in ("POST", "PUT", "PATCH")
            and "Content-Type" not in req_headers
        ):
            try:
                json.loads(body)
                req_headers["Content-Type"] = "application/json"
            except (json.JSONDecodeError, TypeError):
                req_headers["Content-Type"] = "text/plain"

        try:
            start = time.perf_counter()
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    content=body.encode("utf-8") if body else None,
                )
            duration_ms = (time.perf_counter() - start) * 1000

            resp_headers = dict(response.headers)
            resp_body = response.text

            report = _format_response(
                status=response.status_code,
                headers=resp_headers,
                body=resp_body,
                duration_ms=duration_ms,
                method=method,
                url=url,
            )

            success = True
            if expected_status and response.status_code != expected_status:
                report += f"\n\n⚠️ **Validation Failed:** Expected status {expected_status}, got {response.status_code}"
                success = False

            return ToolResult(
                tool_name="api_tester",
                content=report,
                success=success,
                metadata={
                    "status_code": response.status_code,
                    "method": method,
                    "url": url,
                    "duration_ms": round(duration_ms, 1),
                    "content_length": len(resp_body),
                },
            )

        except httpx.TimeoutException:
            return ToolResult(
                tool_name="api_tester",
                content=f"Request timed out after {timeout_seconds}s",
                success=False,
            )
        except httpx.ConnectError as e:
            return ToolResult(
                tool_name="api_tester", content=f"Connection failed: {e}", success=False
            )
        except Exception as e:
            return ToolResult(
                tool_name="api_tester", content=f"Request failed: {e}", success=False
            )


__all__ = ["APITesterTool"]
