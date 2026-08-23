"""Tools for reading, updating, and searching the active Memory Wiki."""

from __future__ import annotations

from typing import Any

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.memory.wiki import MemoryWiki
from nova_ai.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("memory_wiki_read")
class MemoryWikiReadTool(BaseTool):
    """Read structured notes from the user's Memory Wiki."""

    tool_id = "memory_wiki_read"
    is_local = True

    def __init__(self) -> None:
        self.wiki = MemoryWiki()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_wiki_read",
            description="Read content from the user's persistent Memory Wiki (e.g. 'profile', 'preferences', 'projects', 'knowledge', or any custom topic).",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic name to read (e.g. 'profile', 'preferences', 'projects', 'knowledge').",
                    }
                },
                "required": ["topic"],
            },
            category="memory",
            timeout_seconds=5.0,
        )

    def execute(self, topic: str, **kwargs: Any) -> ToolResult:
        content = self.wiki.read_topic(topic)
        return ToolResult(
            tool_name="memory_wiki_read",
            content=content,
            success=True,
            metadata={"topic": topic, "length": len(content)},
        )


@ToolRegistry.register("memory_wiki_update")
class MemoryWikiUpdateTool(BaseTool):
    """Append or update notes in the user's Memory Wiki."""

    tool_id = "memory_wiki_update"
    is_local = True

    def __init__(self) -> None:
        self.wiki = MemoryWiki()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_wiki_update",
            description="Record new facts, user preferences, project notes, or knowledge into the persistent Memory Wiki.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Target topic (e.g. 'profile', 'preferences', 'projects', 'knowledge', or a new topic name).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Information or notes to add.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace"],
                        "default": "append",
                        "description": "'append' adds a timestamped entry; 'replace' overwrites the whole topic.",
                    },
                },
                "required": ["topic", "content"],
            },
            category="memory",
            timeout_seconds=5.0,
        )

    def execute(
        self, topic: str, content: str, mode: str = "append", **kwargs: Any
    ) -> ToolResult:
        status_msg = self.wiki.write_topic(topic, content, mode=mode)
        return ToolResult(
            tool_name="memory_wiki_update",
            content=status_msg,
            success=True,
            metadata={"topic": topic, "mode": mode},
        )


@ToolRegistry.register("memory_wiki_search")
class MemoryWikiSearchTool(BaseTool):
    """Search across all Memory Wiki topics for relevant information."""

    tool_id = "memory_wiki_search"
    is_local = True

    def __init__(self) -> None:
        self.wiki = MemoryWiki()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="memory_wiki_search",
            description="Search across all persistent Memory Wiki pages for keywords or concepts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term or concept to find across all wiki files.",
                    }
                },
                "required": ["query"],
            },
            category="memory",
            timeout_seconds=5.0,
        )

    def execute(self, query: str, **kwargs: Any) -> ToolResult:
        results = self.wiki.search(query)
        formatted = []
        for r in results:
            formatted.append(f"### Topic: {r['topic']}")
            for m in r["matches"]:
                formatted.append(f"- Line {m['line']}: {m['text']}")

        summary_text = (
            "\n".join(formatted)
            if formatted
            else f"No mentions found for query '{query}'."
        )
        return ToolResult(
            tool_name="memory_wiki_search",
            content=summary_text,
            success=True,
            metadata={"query": query, "match_count": len(results)},
        )
