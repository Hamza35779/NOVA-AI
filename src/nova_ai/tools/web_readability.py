"""Web readability tool — extract clean Markdown content and tables from URLs."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, List, Optional
from urllib.parse import urlparse

import httpx

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.security.ssrf import check_ssrf
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# Content types we can never parse as HTML — reject early instead of emitting garbage.
_BINARY_CONTENT_TYPES = (
    "image/",
    "audio/",
    "video/",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/octet-stream",
    "application/msword",
    "application/vnd.",
)

# Precompiled cleanup patterns (module level so they are built once per process).
_RE_SCRIPT = re.compile(
    r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", re.IGNORECASE | re.DOTALL
)
_RE_STYLE = re.compile(
    r"<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>", re.IGNORECASE | re.DOTALL
)
_RE_SVG = re.compile(
    r"<svg\b[^<]*(?:(?!<\/svg>)<[^<]*)*<\/svg>", re.IGNORECASE | re.DOTALL
)
_RE_NOSCRIPT = re.compile(
    r"<noscript\b[^<]*(?:(?!<\/noscript>)<[^<]*)*<\/noscript>",
    re.IGNORECASE | re.DOTALL,
)
_RE_NAV = re.compile(
    r"<nav\b[^<]*(?:(?!<\/nav>)<[^<]*)*<\/nav>", re.IGNORECASE | re.DOTALL
)
_RE_HEADER = re.compile(
    r"<header\b[^<]*(?:(?!<\/header>)<[^<]*)*<\/header>", re.IGNORECASE | re.DOTALL
)
_RE_FOOTER = re.compile(
    r"<footer\b[^<]*(?:(?!<\/footer>)<[^<]*)*<\/footer>", re.IGNORECASE | re.DOTALL
)
_RE_ASIDE = re.compile(
    r"<aside\b[^<]*(?:(?!<\/aside>)<[^<]*)*<\/aside>", re.IGNORECASE | re.DOTALL
)
_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_UNWANTED_PATTERNS = (
    _RE_SCRIPT,
    _RE_STYLE,
    _RE_SVG,
    _RE_NOSCRIPT,
    _RE_NAV,
    _RE_HEADER,
    _RE_FOOTER,
    _RE_ASIDE,
    _RE_COMMENT,
)

_RE_MAIN = re.compile(r"<(article|main)\b[^>]*>(.*?)<\/\1>", re.IGNORECASE | re.DOTALL)
_RE_BODY = re.compile(r"<body\b[^>]*>(.*?)<\/body>", re.IGNORECASE | re.DOTALL)
_RE_TABLE = re.compile(r"<table\b[^>]*>(.*?)<\/table>", re.IGNORECASE | re.DOTALL)
_RE_TR = re.compile(r"<tr\b[^>]*>(.*?)<\/tr>", re.IGNORECASE | re.DOTALL)
_RE_TD = re.compile(r"<(?:td|th)\b[^>]*>(.*?)<\/(?:td|th)>", re.IGNORECASE | re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_HEADER_TAGS = tuple(
    (i, re.compile(rf"<h{i}\b[^>]*>(.*?)<\/h{i}>", re.IGNORECASE | re.DOTALL))
    for i in range(6, 0, -1)
)
_RE_PRE_CODE = re.compile(
    r"<pre\b[^>]*><code\b[^>]*>(.*?)<\/code><\/pre>", re.IGNORECASE | re.DOTALL
)
_RE_INLINE_CODE = re.compile(r"<code\b[^>]*>(.*?)<\/code>", re.IGNORECASE | re.DOTALL)
_RE_LI = re.compile(r"<li\b[^>]*>(.*?)<\/li>", re.IGNORECASE | re.DOTALL)
_RE_BOLD = re.compile(r"<(b|strong)\b[^>]*>(.*?)<\/\1>", re.IGNORECASE | re.DOTALL)
_RE_ITALIC = re.compile(r"<(i|em)\b[^>]*>(.*?)<\/\1>", re.IGNORECASE | re.DOTALL)
_RE_LINK = re.compile(
    r'<a\b[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)<\/a>', re.IGNORECASE | re.DOTALL
)
_RE_BR = re.compile(r"<br\s*\/?>", re.IGNORECASE)
_RE_BLOCK_END = re.compile(r"<\/(p|div|tr|blockquote)>", re.IGNORECASE)
_RE_TITLE = re.compile(r"<title\b[^>]*>(.*?)<\/title>", re.IGNORECASE | re.DOTALL)
_RE_SPACES = re.compile(r"[ \t]+")


def _convert_table_to_markdown(table_html: str) -> str:
    """Convert an HTML <table> element into a Markdown table."""
    rows: List[List[str]] = []
    # Find all rows
    for tr_match in _RE_TR.finditer(table_html):
        tr = tr_match.group(1)
        cells = [m.group(1) for m in _RE_TD.finditer(tr)]
        clean_cells = [_RE_TAG.sub("", c).strip().replace("\n", " ") for c in cells]
        if clean_cells:
            rows.append(clean_cells)

    if not rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    lines: List[str] = []
    # Header row
    header = rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n\n" + "\n".join(lines) + "\n\n"


def _clean_html_to_markdown(html_content: str) -> str:
    """Heuristic-based HTML to clean Markdown extractor.

    Strips boilerplate, scripts, styles, navigations, footers, headers, and ads.
    Converts tables, headers, lists, code blocks, and text formatting.
    """
    # 1. Remove non-content elements
    cleaned = html_content
    for pattern in _UNWANTED_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    # 2. Extract article or main if present, else use full body
    main_match = _RE_MAIN.search(cleaned)
    if main_match:
        cleaned = main_match.group(2)
    else:
        body_match = _RE_BODY.search(cleaned)
        if body_match:
            cleaned = body_match.group(1)

    # 3. Convert HTML tables before stripping other tags
    cleaned = _RE_TABLE.sub(lambda m: _convert_table_to_markdown(m.group(0)), cleaned)

    # 4. Convert headers
    for i, header_re in _RE_HEADER_TAGS:
        cleaned = header_re.sub(
            lambda m: f"\n\n{'#' * i} {m.group(1).strip()}\n\n", cleaned
        )

    # 5. Convert code blocks and pre
    cleaned = _RE_PRE_CODE.sub(
        lambda m: f"\n\n```\n{html.unescape(m.group(1).strip())}\n```\n\n", cleaned
    )
    cleaned = _RE_INLINE_CODE.sub(
        lambda m: f"`{html.unescape(m.group(1).strip())}`", cleaned
    )

    # 6. Convert lists
    cleaned = _RE_LI.sub(lambda m: f"\n* {m.group(1).strip()}", cleaned)

    # 7. Convert formatting (bold, italics)
    cleaned = _RE_BOLD.sub(r"**\2**", cleaned)
    cleaned = _RE_ITALIC.sub(r"*\2*", cleaned)

    # 8. Convert links
    cleaned = _RE_LINK.sub(
        lambda m: (
            f"[{m.group(2).strip()}]({m.group(1).strip()})"
            if m.group(2).strip()
            else ""
        ),
        cleaned,
    )

    # 9. Convert paragraphs and line breaks
    cleaned = _RE_BR.sub("\n", cleaned)
    cleaned = _RE_BLOCK_END.sub("\n\n", cleaned)

    # 10. Strip remaining HTML tags
    cleaned = _RE_TAG.sub("", cleaned)

    # 11. Decode HTML entities
    cleaned = html.unescape(cleaned)

    # 12. Normalize whitespace
    lines = [_RE_SPACES.sub(" ", line).strip() for line in cleaned.splitlines()]
    result = []
    blank = False
    for line in lines:
        if line:
            result.append(line)
            blank = False
        elif not blank:
            result.append("")
            blank = True

    return "\n".join(result).strip()


@ToolRegistry.register("web_readability")
class WebReadabilityTool(BaseTool):
    """Tool to fetch web URLs and extract clean, readable Markdown content."""

    tool_id = "web_readability"
    is_local = False

    def __init__(
        self, timeout: float = 15.0, user_agent: str | None = None, max_retries: int = 2
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 NOVA-AI/1.0"
        )

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_readability",
            description=(
                "Fetch a webpage URL and extract its clean, readable Markdown article content, "
                "including converted tables, stripping ads, navigation, headers, and footers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The HTTP or HTTPS URL to read and extract.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional maximum character length of the extracted markdown.",
                        "default": 10000,
                        "minimum": 1,
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Optional per-request fetch timeout in seconds (overrides tool default).",
                        "default": 15,
                        "minimum": 1,
                    },
                },
                "required": ["url"],
            },
            category="retrieval",
            timeout_seconds=25.0,
        )

    def execute(
        self,
        url: str,
        max_chars: int = 10000,
        timeout_seconds: Optional[float] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not url:
            return ToolResult(
                tool_name="web_readability",
                content="Error: URL parameter is required.",
                success=False,
            )

        # Validate max_chars — 0/negative would otherwise disable truncation entirely.
        try:
            max_chars = int(max_chars)
        except (TypeError, ValueError):
            max_chars = 10_000
        if max_chars <= 0:
            max_chars = 10_000

        # Validate timeout
        fetch_timeout = self.timeout
        try:
            if timeout_seconds is not None and float(timeout_seconds) > 0:
                fetch_timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            pass

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                tool_name="web_readability",
                content=f"Error: Invalid URL scheme '{parsed.scheme}'. Only http/https supported.",
                success=False,
            )

        # SSRF check
        try:
            check_ssrf(url)
        except Exception as exc:
            return ToolResult(
                tool_name="web_readability",
                content=f"SSRF policy blocked URL: {exc}",
                success=False,
            )

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        raw_html = ""
        last_error: Optional[Exception] = None
        status_code = 200

        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=fetch_timeout, follow_redirects=True, headers=headers
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    raw_html = response.text or ""
                    status_code = getattr(response, "status_code", 200)

                    # Reject binary payloads (PDFs, images, archives) before parsing.
                    try:
                        content_type = str(
                            response.headers.get("content-type", "") or ""
                        ).lower()
                    except Exception:
                        content_type = ""
                    if content_type and any(
                        ct in content_type for ct in _BINARY_CONTENT_TYPES
                    ):
                        return ToolResult(
                            tool_name="web_readability",
                            content=(
                                f"Error: URL returned non-HTML content type '{content_type}'. "
                                "Web readability only supports text/HTML pages."
                            ),
                            success=False,
                            metadata={
                                "url": url,
                                "status_code": status_code,
                                "content_type": content_type,
                            },
                        )
                    break
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)

        if not raw_html:
            logger.warning("Failed to fetch %s: %s", url, last_error)
            detail = f": {last_error}" if last_error else " (response body was empty)"
            return ToolResult(
                tool_name="web_readability",
                content=f"Error fetching URL '{url}'{detail}",
                success=False,
            )

        # Extract title
        title_match = _RE_TITLE.search(raw_html)
        title = (
            html.unescape(title_match.group(1).strip())
            if title_match
            else "Untitled Page"
        )

        markdown_body = _clean_html_to_markdown(raw_html)

        if len(markdown_body) > max_chars:
            markdown_body = markdown_body[:max_chars] + "\n\n...[content truncated]"

        final_content = f"# {title}\n\n**Source URL:** {url}\n\n---\n\n{markdown_body}"

        return ToolResult(
            tool_name="web_readability",
            content=final_content,
            success=True,
            metadata={
                "title": title,
                "url": url,
                "status_code": status_code,
                "extracted_length": len(markdown_body),
            },
        )
