"""File Converter tool — bidirectional format conversion between common file types.

Supports: Markdown ↔ HTML, JSON ↔ YAML, CSV ↔ JSON, JSON ↔ XML, text encoding conversion.
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# ── Conversion Functions ───────────────────────────────────────


def _markdown_to_html(md: str) -> str:
    """Lightweight Markdown to HTML converter."""
    lines = md.split("\n")
    html_lines = []
    in_code_block = False
    in_list = False

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                lang = line.strip()[3:].strip()
                html_lines.append(
                    f'<pre><code class="language-{lang}">' if lang else "<pre><code>"
                )
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(html.escape(line))
            continue

        stripped = line.strip()

        # Headers
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            text = stripped[level:].strip()
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue

        # Unordered list
        if stripped.startswith(("- ", "* ", "+ ")):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
            continue

        if in_list and not stripped.startswith(("- ", "* ", "+ ")):
            html_lines.append("</ul>")
            in_list = False

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            html_lines.append("<hr>")
            continue

        # Bold, italic, inline code
        processed = stripped
        processed = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", processed)
        processed = re.sub(r"\*(.+?)\*", r"<em>\1</em>", processed)
        processed = re.sub(r"`(.+?)`", r"<code>\1</code>", processed)
        processed = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', processed)

        if processed:
            html_lines.append(f"<p>{processed}</p>")
        else:
            html_lines.append("")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def _html_to_markdown(raw_html: str) -> str:
    """Strip HTML to clean Markdown."""
    text = re.sub(
        r"<h([1-6])[^>]*>(.*?)</h\1>",
        lambda m: f"{'#' * int(m.group(1))} {m.group(2)}",
        raw_html,
        flags=re.DOTALL,
    )
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL
    )
    text = re.sub(r"<li>(.*?)</li>", r"- \1", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


def _csv_to_json(csv_text: str) -> str:
    """Convert CSV text to JSON array."""
    reader = csv.DictReader(io.StringIO(csv_text))
    records = list(reader)
    return json.dumps(records, indent=2, ensure_ascii=False)


def _json_to_csv(json_text: str) -> str:
    """Convert JSON array of objects to CSV."""
    data = json.loads(json_text)
    if isinstance(data, dict):
        data = [data]
    if not data or not isinstance(data[0], dict):
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


def _json_to_yaml(json_text: str) -> str:
    """Convert JSON to YAML format."""
    try:
        import yaml

        data = json.loads(json_text)
        return yaml.dump(
            data, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    except ImportError:
        # Manual lightweight YAML output
        data = json.loads(json_text)
        return _dict_to_yaml(data, indent=0)


def _dict_to_yaml(obj: Any, indent: int = 0) -> str:
    """Minimal dict-to-YAML serializer (fallback when PyYAML unavailable)."""
    prefix = "  " * indent
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(_dict_to_yaml(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_dict_to_yaml(item, indent + 1))
            else:
                lines.append(f"{prefix}- {item}")
    else:
        lines.append(f"{prefix}{obj}")
    return "\n".join(lines)


def _yaml_to_json(yaml_text: str) -> str:
    """Convert YAML to JSON."""
    try:
        import yaml

        data = yaml.safe_load(yaml_text)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except ImportError:
        raise ImportError("Install PyYAML for YAML conversion: pip install pyyaml")


CONVERTERS = {
    ("markdown", "html"): _markdown_to_html,
    ("md", "html"): _markdown_to_html,
    ("html", "markdown"): _html_to_markdown,
    ("html", "md"): _html_to_markdown,
    ("csv", "json"): _csv_to_json,
    ("json", "csv"): _json_to_csv,
    ("json", "yaml"): _json_to_yaml,
    ("json", "yml"): _json_to_yaml,
    ("yaml", "json"): _yaml_to_json,
    ("yml", "json"): _yaml_to_json,
}


@ToolRegistry.register("file_converter")
class FileConverterTool(BaseTool):
    """Convert files between formats: Markdown ↔ HTML, CSV ↔ JSON, JSON ↔ YAML."""

    tool_id = "file_converter"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_converter",
            description=(
                "Convert files and data between formats. "
                "Supports: Markdown ↔ HTML, CSV ↔ JSON, JSON ↔ YAML. "
                "Accepts either a file path or raw text input."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Path to the source file to convert.",
                    },
                    "raw_input": {
                        "type": "string",
                        "description": "Raw text content to convert (alternative to input_path).",
                    },
                    "from_format": {
                        "type": "string",
                        "enum": [
                            "markdown",
                            "md",
                            "html",
                            "csv",
                            "json",
                            "yaml",
                            "yml",
                        ],
                        "description": "Source format.",
                    },
                    "to_format": {
                        "type": "string",
                        "enum": [
                            "markdown",
                            "md",
                            "html",
                            "csv",
                            "json",
                            "yaml",
                            "yml",
                        ],
                        "description": "Target format.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional output file path. If omitted, returns converted content inline.",
                    },
                },
                "required": ["from_format", "to_format"],
            },
            category="productivity",
            timeout_seconds=15.0,
        )

    @track_execution("file_converter")
    def execute(
        self,
        from_format: str,
        to_format: str,
        input_path: Optional[str] = None,
        raw_input: Optional[str] = None,
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        src = from_format.lower().strip()
        dst = to_format.lower().strip()

        converter = CONVERTERS.get((src, dst))
        if not converter:
            supported = ", ".join(f"{a}→{b}" for a, b in CONVERTERS)
            return ToolResult(
                tool_name="file_converter",
                content=f"Unsupported conversion: {src} → {dst}. Supported: {supported}",
                success=False,
            )

        # Load input
        if input_path:
            path = Path(input_path)
            if not path.exists():
                return ToolResult(
                    tool_name="file_converter",
                    content=f"File not found: {input_path}",
                    success=False,
                )
            source_text = path.read_text(encoding="utf-8", errors="replace")
        elif raw_input:
            source_text = raw_input
        else:
            return ToolResult(
                tool_name="file_converter",
                content="Provide 'input_path' or 'raw_input'.",
                success=False,
            )

        try:
            result = converter(source_text)
        except Exception as e:
            return ToolResult(
                tool_name="file_converter",
                content=f"Conversion failed: {e}",
                success=False,
            )

        # Write output if path specified
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(result, encoding="utf-8")
            return ToolResult(
                tool_name="file_converter",
                content=f"Converted {src} → {dst} and saved to {output_path}",
                success=True,
                metadata={
                    "from": src,
                    "to": dst,
                    "output_path": output_path,
                    "size": len(result),
                },
            )

        # Return inline
        truncated = result[:8000] + "\n...[truncated]" if len(result) > 8000 else result
        return ToolResult(
            tool_name="file_converter",
            content=truncated,
            success=True,
            metadata={"from": src, "to": dst, "size": len(result)},
        )


__all__ = ["FileConverterTool"]
