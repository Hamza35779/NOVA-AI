"""Web search tool — SearXNG, Brave, Tavily API with DuckDuckGo fallback."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.security.ssrf import check_ssrf
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    """Search the web using various providers."""

    tool_id = "web_search"
    is_local = False

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._max_results = max_results

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description=(
                "Search the web for current information."
                " Returns relevant search results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return.",
                    },
                    "provider": {
                        "type": "string",
                        "description": "Provider to use (auto, searxng, brave, tavily, duckduckgo)."
                    }
                },
                "required": ["query"],
            },
            category="search",
            metadata={"requires_api_key": "TAVILY_API_KEY", "fallback": "duckduckgo"},
        )

    @staticmethod
    def _is_url(text: str) -> bool:
        """Check if text is a URL."""
        stripped = text.strip()
        return stripped.startswith("http://") or stripped.startswith("https://")

    @staticmethod
    def _extract_url(text: str) -> str | None:
        """Extract the first URL from text, if any."""
        import re as _re

        match = _re.search(r"https?://[^\s,;\"'<>]+", text)
        return match.group(0).rstrip(".,;)") if match else None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Convert known PDF URLs to their HTML equivalents."""
        import re as _re

        # arxiv: /pdf/ID → /abs/ID (abstract page with full metadata)
        m = _re.match(r"(https?://arxiv\.org)/pdf/(.+?)(?:\.pdf)?$", url)
        if m:
            return f"{m.group(1)}/abs/{m.group(2)}"
        return url

    @staticmethod
    def _fetch_url(url: str, max_chars: int = 6000) -> str:
        """Fetch a URL and return extracted text content.

        Entity-unescapes the markup and prefers a real HTML parser
        (BeautifulSoup) when available, falling back to a regex sweep for
        docstrings/comments/scripts so raw tag soup is never returned.
        """

        import httpx

        url = WebSearchTool._normalize_url(url)
        ssrf_error = check_ssrf(url)
        if ssrf_error:
            raise ValueError(ssrf_error)
        resp = httpx.get(
            url.strip(),
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; NOVA AI/1.0; +https://github.com/nova_ai)"
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return (
                "[This URL points to a PDF file which"
                f" cannot be read directly. URL: {url}]"
            )
        # ``resp.text`` can mis-decode when the header omits/mislabels the
        # charset; fall back to raw bytes with correct encoding detection.
        if not resp.encoding:
            resp.encoding = resp.charset_encoding or "utf-8"
        html = resp.text

        text = WebSearchTool._extract_text_from_html(html)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[Content truncated]"
        return text

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        """Convert markup to plain text, dropping scripts/styles/comments."""
        import html as _html
        import re as _re

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "template"]):
                tag.decompose()
            # Separate block elements with spaces so words don't run together.
            text = soup.get_text(separator=" ")
        except ImportError:
            cleaned = _re.sub(
                r"<!--.*?-->",
                " ",
                html,
                flags=_re.DOTALL,
            )
            cleaned = _re.sub(
                r"<(script|style|noscript|template)[^>]*>.*?</\1>",
                " ",
                cleaned,
                flags=_re.DOTALL | _re.IGNORECASE,
            )
            cleaned = _re.sub(r"<[^>]+>", " ", cleaned)
            text = cleaned

        # Decode entities (``&amp;`` -> ``&``) BEFORE collapsing whitespace so
        # the resulting characters are handled correctly.
        text = _html.unescape(text)
        return _re.sub(r"\s+", " ", text).strip()

    def _searxng_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        import httpx
        url = os.environ.get("SEARXNG_URL", "http://localhost:8080")
        resp = httpx.get(f"{url}/search", params={"q": query, "format": "json"}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            })
        return results

    def _brave_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        import httpx
        api_key = os.environ.get("BRAVE_API_KEY")
        if not api_key:
            raise ValueError("BRAVE_API_KEY environment variable not set")

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers=headers,
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            })
        return results

    def _tavily_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        from tavily import TavilyClient
        client = TavilyClient(api_key=self._api_key)
        response = client.search(
            query,
            max_results=max_results,
            search_depth="advanced",
            include_usage=True,
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url", ""),
                "snippet": r.get("content", "") or r.get("snippet", ""),
            })
        return results

    def _duckduckgo_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Search using DuckDuckGo as fallback."""
        from ddgs import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.text(query, max_results=max_results))
        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        return results

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(
                tool_name="web_search",
                content="No query provided.",
                success=False,
            )

        # If the query contains a URL, fetch it directly instead of searching
        url = self._extract_url(query) if not self._is_url(query) else query.strip()
        if url:
            try:
                content = self._fetch_url(url)
                return ToolResult(
                    tool_name="web_search",
                    content=content or "No content found at URL.",
                    success=True,
                    metadata={"url": url, "mode": "fetch"},
                )
            except Exception as exc:
                return ToolResult(
                    tool_name="web_search",
                    content=f"Failed to fetch URL: {exc}",
                    success=False,
                )

        max_results = params.get("max_results", self._max_results)
        provider = params.get("provider", "auto")

        providers = []
        if provider == "auto":
            if os.environ.get("SEARXNG_URL"):
                providers.append("searxng")
            if os.environ.get("BRAVE_API_KEY"):
                providers.append("brave")
            if self._api_key:
                providers.append("tavily")
            providers.append("duckduckgo")
        else:
            providers = [provider]

        results = []
        provider_used = None
        error_msgs = []

        for p in providers:
            try:
                if p == "searxng":
                    results = self._searxng_search(query, max_results)
                elif p == "brave":
                    results = self._brave_search(query, max_results)
                elif p == "tavily":
                    results = self._tavily_search(query, max_results)
                elif p == "duckduckgo":
                    results = self._duckduckgo_search(query, max_results)
                else:
                    continue

                provider_used = p
                break
            except Exception as exc:
                logger.debug(f"{p} search error: {exc}")
                error_msgs.append(f"{p}: {exc}")

        if not provider_used:
            return ToolResult(
                tool_name="web_search",
                content=f"All search providers failed: {'; '.join(error_msgs)}",
                success=False,
            )

        if isinstance(results, str):
            formatted = results
            num_res = 1 if results else 0
        elif isinstance(results, list):
            formatted_parts = []
            for r in results:
                if isinstance(r, dict):
                    title = r.get("title", "Untitled")
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")
                    formatted_parts.append(f"### {title}\nSource: {url}\nSummary: {snippet}")
                else:
                    formatted_parts.append(str(r))
            formatted = "\n\n---\n\n".join(formatted_parts)
            num_res = len(results)
        else:
            formatted = str(results)
            num_res = 1

        return ToolResult(
            tool_name="web_search",
            content=formatted or "No results found.",
            success=True,
            metadata={
                "num_results": num_res,
                "engine": provider_used,
                "provider": provider_used,
                "results": results if isinstance(results, list) else [{"title": "Result", "url": "", "snippet": str(results)}],
            },
        )

__all__ = ["WebSearchTool"]
