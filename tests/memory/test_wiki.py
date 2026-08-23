from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from nova_ai.memory.wiki import MemoryWiki
from nova_ai.tools.memory_wiki_tools import (
    MemoryWikiReadTool,
    MemoryWikiSearchTool,
    MemoryWikiUpdateTool,
)


def test_memory_wiki_initialization() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))
        topics = wiki.list_topics()
        assert "profile" in topics
        assert "preferences" in topics
        assert "projects" in topics
        assert "knowledge" in topics


def test_memory_wiki_read_write_append() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))

        # Append
        wiki.write_topic("notes", "First point to remember", mode="append")
        content = wiki.read_topic("notes")
        assert "First point to remember" in content

        # Append second note
        wiki.write_topic("notes", "Second point to remember", mode="append")
        content2 = wiki.read_topic("notes")
        assert "First point to remember" in content2
        assert "Second point to remember" in content2


def test_memory_wiki_deduplication() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))
        wiki.write_topic("notes", "Duplicate item", mode="append")
        res2 = wiki.write_topic("notes", "Duplicate item", mode="append")
        assert "skipped duplicate" in res2


def test_memory_wiki_replace() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))
        wiki.write_topic(
            "profile", "# Custom Profile\n\nName: Nova Developer", mode="replace"
        )
        content = wiki.read_topic("profile")
        assert content.strip() == "# Custom Profile\n\nName: Nova Developer"


def test_memory_wiki_search_ranking() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))
        wiki.write_topic(
            "quantum", "Quantum entanglement in distributed systems", mode="append"
        )
        wiki.write_topic(
            "hardware", "Quantum computing processors and entanglement", mode="append"
        )

        results = wiki.search("quantum entanglement")
        assert len(results) >= 1
        # Ranked by score
        assert results[0]["score"] >= results[-1]["score"]


def test_memory_wiki_get_relevant_context() -> None:
    with TemporaryDirectory() as tmpdir:
        wiki = MemoryWiki(root_dir=Path(tmpdir))
        wiki.write_topic(
            "database", "Using PostgreSQL for analytics caching", mode="append"
        )
        context = wiki.get_relevant_context("analytics query")
        assert "database" in context
        assert "PostgreSQL" in context


def test_memory_wiki_tools() -> None:
    with TemporaryDirectory() as tmpdir:
        custom_root = Path(tmpdir)

        read_tool = MemoryWikiReadTool()
        read_tool.wiki = MemoryWiki(root_dir=custom_root)

        update_tool = MemoryWikiUpdateTool()
        update_tool.wiki = MemoryWiki(root_dir=custom_root)

        search_tool = MemoryWikiSearchTool()
        search_tool.wiki = MemoryWiki(root_dir=custom_root)

        # Execute update tool
        res_update = update_tool.execute(
            topic="skills", content="Learned Rust and Python async"
        )
        assert res_update.success is True

        # Execute read tool
        res_read = read_tool.execute(topic="skills")
        assert res_read.success is True
        assert "Learned Rust and Python async" in res_read.content

        # Execute search tool
        res_search = search_tool.execute(query="Rust")
        assert res_search.success is True
        assert "Learned Rust and Python async" in res_search.content
