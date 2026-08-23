"""MemoryWiki — structured Markdown-based persistent memory and user knowledge base."""

from __future__ import annotations

import datetime
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

DEFAULT_WIKI_TEMPLATE = {
    "profile": "# User Profile\n\n- Name: User\n- Role: Developer / Researcher\n- Communication Style: Direct, concise, technical\n",
    "preferences": "# User Preferences\n\n- Default Tools: Python, Rust, TypeScript\n- Theme: Dark Mode\n- Guidelines: Keep answers clear and to the point.\n",
    "projects": "# Active Projects\n\n- NOVA AI: High-performance local-first personal AI assistant.\n",
    "knowledge": "# Accumulated Knowledge & Facts\n\n",
}

# Entry marker used for append-mode timestamps.
_ENTRY_MARKER = "### ["


class MemoryWiki:
    """Manages structured Markdown wiki pages under ~/.nova_ai/memory_wiki/."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = root_dir or (get_config_dir() / "memory_wiki")
        self._cache_lock = threading.Lock()
        # Cache: path -> (mtime_ns, text) so repeated searches skip unchanged files.
        self._file_cache: Dict[Path, Tuple[int, str]] = {}
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Create directory and default wiki files if they do not exist."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        for topic, template in DEFAULT_WIKI_TEMPLATE.items():
            topic_file = self.root_dir / f"{topic}.md"
            if not topic_file.exists():
                topic_file.write_text(template, encoding="utf-8")

    def _sanitize_topic(self, topic: str) -> str:
        """Sanitize topic name to a safe filename.

        Falls back to 'misc' (never a default template topic) so an empty or
        fully-invalid topic cannot silently overwrite the shared knowledge wiki.
        """
        clean = topic.strip().lower().replace(" ", "_").replace("-", "_")
        clean = "".join(c for c in clean if c.isalnum() or c == "_")
        return clean or "misc"

    def _read_cached(self, topic_path: Path) -> str:
        """Read file contents with mtime-based caching for search performance."""
        try:
            mtime = topic_path.stat().st_mtime_ns
        except OSError:
            return ""
        with self._cache_lock:
            cached = self._file_cache.get(topic_path)
            if cached is not None and cached[0] == mtime:
                return cached[1]
        try:
            text = topic_path.read_text(encoding="utf-8")
        except OSError:
            return ""
        with self._cache_lock:
            self._file_cache[topic_path] = (mtime, text)
        return text

    def read_topic(self, topic: str) -> str:
        """Read the Markdown content of a specific wiki topic."""
        clean = self._sanitize_topic(topic)
        topic_file = self.root_dir / f"{clean}.md"
        if not topic_file.exists():
            return f"Topic '{topic}' does not exist yet."
        return self._read_cached(topic_file)

    @staticmethod
    def _entry_exists(existing: str, trimmed_content: str) -> bool:
        """Line-level dedup check.

        Matches single-line entries exactly against existing lines, and
        multi-line entries as a contiguous line sequence. Avoids the old
        substring behavior where 'yes' matched any sentence containing it.
        """
        if not existing:
            return False
        lines = [line.strip() for line in existing.splitlines()]
        new_lines = [line.strip() for line in trimmed_content.splitlines()]

        if len(new_lines) == 1:
            return new_lines[0] in lines

        # Contiguous sub-sequence match for multi-line entries.
        n = len(new_lines)
        for i in range(len(lines) - n + 1):
            if lines[i : i + n] == new_lines:
                return True
        return False

    def write_topic(self, topic: str, content: str, mode: str = "append") -> str:
        """Write or append information to a wiki topic with deduplication."""
        clean = self._sanitize_topic(topic)
        topic_file = self.root_dir / f"{clean}.md"

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trimmed_content = content.strip()

        if not trimmed_content:
            return f"Error: cannot write empty content to topic '{clean}'."

        if mode == "replace":
            topic_file.write_text(trimmed_content + "\n", encoding="utf-8")
            # Invalidate cache for this file.
            with self._cache_lock:
                self._file_cache.pop(topic_file, None)
            return f"Updated topic '{clean}' ({len(trimmed_content)} chars written)."

        # Append mode: read once for deduplication, then stream-append without rewrite.
        header = f"# {clean.replace('_', ' ').title()}\n\n"
        existing = self._read_cached(topic_file) if topic_file.exists() else ""

        if not existing:
            # New topic file needs its header first.
            topic_file.write_text(header, encoding="utf-8")
            existing = header

        if self._entry_exists(existing, trimmed_content):
            return f"Entry already exists in topic '{clean}' (skipped duplicate)."

        entry = f"\n\n{_ENTRY_MARKER}{now}]\n{trimmed_content}\n"
        try:
            with topic_file.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError as exc:
            logger.error("Failed appending to wiki topic '%s': %s", clean, exc)
            return f"Error: could not append to topic '{clean}': {exc}"

        with self._cache_lock:
            self._file_cache.pop(topic_file, None)
        return f"Appended new entry to topic '{clean}'."

    def delete_topic(self, topic: str) -> str:
        """Delete a wiki topic file. Default template topics are recreated on next init."""
        clean = self._sanitize_topic(topic)
        topic_file = self.root_dir / f"{clean}.md"
        if not topic_file.exists():
            return f"Topic '{topic}' does not exist."
        try:
            topic_file.unlink()
        except OSError as exc:
            return f"Error: could not delete topic '{clean}': {exc}"
        with self._cache_lock:
            self._file_cache.pop(topic_file, None)
        return f"Deleted topic '{clean}'."

    def list_topics(self) -> List[str]:
        """Return list of all available topic names."""
        self._ensure_initialized()
        return sorted(p.stem for p in self.root_dir.glob("*.md"))

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search across all wiki files for query terms with relevance scoring."""
        results: List[Dict[str, Any]] = []
        if not query:
            return results

        keywords = [k.lower() for k in query.split() if len(k) > 2]
        if not keywords:
            keywords = [query.lower()]

        for topic_path in sorted(self.root_dir.glob("*.md")):
            text = self._read_cached(topic_path)
            if not text:
                continue
            topic_name = topic_path.stem

            score = 0
            # Boost matches in topic name
            if any(k in topic_name.lower() for k in keywords):
                score += 5

            matches = []
            for line_num, line in enumerate(text.splitlines(), start=1):
                line_lower = line.lower()
                matched_keywords = [k for k in keywords if k in line_lower]
                if matched_keywords:
                    score += len(matched_keywords)
                    matches.append({"line": line_num, "text": line.strip()})

            if score > 0:
                results.append(
                    {
                        "topic": topic_name,
                        "score": score,
                        "matches": matches,
                        "file_path": str(topic_path),
                    }
                )

        # Rank by highest score first
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def get_relevant_context(self, query: str, max_chars: int = 1500) -> str:
        """Dynamically retrieve the most relevant wiki snippets for a given query."""
        search_hits = self.search(query)
        if not search_hits:
            return self.get_summary(max_chars=max_chars)

        snippets: List[str] = []
        # Always include high-level profile when it exists.
        profile_file = self.root_dir / "profile.md"
        if profile_file.exists():
            profile = self.read_topic("profile")
            if profile and not profile.startswith("Topic '"):
                snippets.append(profile.strip())

        for hit in search_hits[:3]:
            topic = hit["topic"]
            if topic == "profile":
                continue
            topic_content = self.read_topic(topic)
            if topic_content:
                snippets.append(f"## Context: {topic}\n{topic_content.strip()}")

        full = "\n\n---\n\n".join(snippets)
        return full[:max_chars] if len(full) > max_chars else full

    def get_summary(self, max_chars: int = 2000) -> str:
        """Aggregate high-level profile, preferences, and projects into context string."""
        sections: List[str] = []
        for topic in ("profile", "preferences", "projects"):
            content = self.read_topic(topic)
            if content and not content.startswith("Topic '"):
                sections.append(content.strip())

        full = "\n\n---\n\n".join(sections)
        if len(full) > max_chars:
            full = full[:max_chars] + "\n..."
        return full


__all__ = ["MemoryWiki", "DEFAULT_WIKI_TEMPLATE"]
