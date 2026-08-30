"""Web Search API routes with grounded AI synthesis."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    provider: str = "auto"  # auto | searxng | brave | tavily | duckduckgo
    max_results: int = 5
    synthesize: bool = True


@router.post("")
async def search_web(body: SearchRequest) -> Dict[str, Any]:
    """Execute web search and optionally synthesize an answer with citations."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    tool = WebSearchTool()
    res = tool.execute(query=body.query, max_results=body.max_results, provider=body.provider)

    results = getattr(res, "metadata", {}).get("results", []) if res.success else []
    raw_content = res.content or ""

    synthesis = ""
    if body.synthesize and results:
        context = "\n\n".join(
            f"[{i+1}] {r.get('title')}\nURL: {r.get('url')}\n{r.get('snippet') or r.get('content')}"
            for i, r in enumerate(results)
        )
        prompt = (
            f"Answer the question using the following search results. Cite sources as [1], [2], etc.\n\n"
            f"Query: {body.query}\n\n"
            f"Search Results:\n{context}\n\n"
            f"Answer:"
        )
        try:
            from nova_ai.sdk import Nova
            synthesis = Nova().ask(prompt)
        except Exception as exc:
            synthesis = raw_content

    return {
        "query": body.query,
        "provider": getattr(res, "metadata", {}).get("provider", body.provider),
        "results": results,
        "synthesis": synthesis or raw_content,
        "success": res.success,
    }
