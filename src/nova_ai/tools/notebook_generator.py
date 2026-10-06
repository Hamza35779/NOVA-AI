"""Notebook Generator tool — emit valid nbformat 4.5 Jupyter notebooks (.ipynb).

Uses only the stdlib (json + uuid); no nbformat dependency. Source text is
normalised to newline-terminated string lists so the output round-trips
through nbformat/Jupyter validation. Unknown cell types are rejected rather
than guessed.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

_VALID_CELL_TYPES = ("code", "markdown", "raw")

_KERNELSPEC = {
    "name": "python3",
    "language": "python",
    "display_name": "Python 3 (ipykernel)",
}

_LANGUAGE_INFO = {
    "name": "python",
    "version": "3.10",
    "mimetype": "text/x-python",
    "file_extension": ".py",
}


def _normalise_source(source: Any) -> List[str]:
    """Convert string or list-of-strings source into newline-terminated lines.

    nbformat allows ``source`` as a plain string or a list of strings; the
    canonical on-disk form (and what Jupyter writes) is a list where every
    element ends with a newline. Accept both and emit the canonical form.
    """
    if isinstance(source, str):
        lines = source.splitlines()
    elif isinstance(source, list) and all(isinstance(part, str) for part in source):
        joined = "".join(source)
        lines = joined.splitlines()
    else:
        raise TypeError("source must be a string or a list of strings")

    if not lines:
        return [""]
    return [line + "\n" for line in lines]


def _cell_id() -> str:
    """Generate an nbformat-4.5 cell id (8 hex chars, unique per notebook)."""
    return uuid.uuid4().hex[:8]


def _build_cell(cell_type: str, source: List[str], cell_id: str) -> Dict[str, Any]:
    """Build one notebook cell dict for the requested type."""
    cell: Dict[str, Any] = {
        "cell_type": cell_type,
        "id": cell_id,
        "metadata": {},
        "source": source,
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


@ToolRegistry.register("notebook_generator")
class NotebookGeneratorTool(BaseTool):
    """Generate a valid .ipynb notebook from an ordered list of cells."""

    tool_id = "notebook_generator"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notebook_generator",
            description=(
                "Generate a Jupyter notebook (.ipynb, nbformat 4.5) from an ordered "
                "list of cells. Each cell needs a cell_type (one of 'code', "
                "'markdown', 'raw') and its source text; source may be a single "
                "string or a list of strings. Unknown cell types are rejected. "
                "The file is written with a python3 kernelspec and Python "
                "language_info metadata. The target path must end in .ipynb and "
                "must not already exist."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File path for the notebook. Must end with .ipynb "
                            "(e.g. 'analysis/report.ipynb'). The file must not "
                            "already exist; the tool never overwrites."
                        ),
                    },
                    "cells": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cell_type": {
                                    "type": "string",
                                    "enum": list(_VALID_CELL_TYPES),
                                    "description": (
                                        "Cell kind: 'code' for executable Python, "
                                        "'markdown' for formatted prose, 'raw' for "
                                        "plain text passed through unchanged."
                                    ),
                                },
                                "source": {
                                    "type": ["string", "array"],
                                    "description": (
                                        "Cell content. Either one string with "
                                        "newlines, or a list of strings (each a "
                                        "line). Stored newline-terminated."
                                    ),
                                },
                            },
                            "required": ["cell_type", "source"],
                        },
                        "description": (
                            "Ordered notebook cells, top to bottom. At least one "
                            "cell is required."
                        ),
                    },
                },
                "required": ["path", "cells"],
            },
            category="development",
            timeout_seconds=15.0,
        )

    @track_execution("notebook_generator")
    def execute(self, path: str, cells: List[Dict[str, Any]], **kwargs: Any) -> ToolResult:
        if not path:
            return ToolResult(
                tool_name="notebook_generator",
                content="Error: no path provided for the notebook.",
                success=False,
            )
        if not path.endswith(".ipynb"):
            return ToolResult(
                tool_name="notebook_generator",
                content=f"Error: path '{path}' must end with .ipynb.",
                success=False,
            )

        target = Path(path)
        if target.exists():
            return ToolResult(
                tool_name="notebook_generator",
                content=(
                    f"Error: notebook already exists at {target}. "
                    "Choose a different filename; this tool never overwrites."
                ),
                success=False,
            )

        if not isinstance(cells, list) or not cells:
            return ToolResult(
                tool_name="notebook_generator",
                content=(
                    "Error: cells must be a non-empty ordered list of "
                    "{'cell_type', 'source'} objects."
                ),
                success=False,
            )

        built: List[Dict[str, Any]] = []
        try:
            for index, raw in enumerate(cells):
                if not isinstance(raw, dict):
                    return ToolResult(
                        tool_name="notebook_generator",
                        content=(
                            f"Error: cell {index} is not an object with "
                            "'cell_type' and 'source'."
                        ),
                        success=False,
                    )
                cell_type = raw.get("cell_type")
                if cell_type not in _VALID_CELL_TYPES:
                    return ToolResult(
                        tool_name="notebook_generator",
                        content=(
                            f"Error: cell {index} has unknown cell_type "
                            f"{cell_type!r}. Valid types: "
                            f"{', '.join(_VALID_CELL_TYPES)}."
                        ),
                        success=False,
                    )
                if "source" not in raw:
                    return ToolResult(
                        tool_name="notebook_generator",
                        content=f"Error: cell {index} ({cell_type}) is missing 'source'.",
                        success=False,
                    )
                source = _normalise_source(raw["source"])
                built.append(_build_cell(cell_type, source, _cell_id()))
        except (TypeError, ValueError) as exc:
            return ToolResult(
                tool_name="notebook_generator",
                content=f"Error: invalid cell source — {exc}",
                success=False,
            )

        notebook = {
            "cells": built,
            "metadata": {
                "kernelspec": dict(_KERNELSPEC),
                "language_info": dict(_LANGUAGE_INFO),
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return ToolResult(
                tool_name="notebook_generator",
                content=f"Error: could not write notebook — {exc}",
                success=False,
            )

        counts: Dict[str, int] = {}
        for cell in built:
            counts[cell["cell_type"]] = counts.get(cell["cell_type"], 0) + 1
        breakdown = ", ".join(f"{n} {t}" for t, n in sorted(counts.items()))

        return ToolResult(
            tool_name="notebook_generator",
            content=(
                f"Created notebook: {target} "
                f"({len(built)} cells: {breakdown}, nbformat 4.5)."
            ),
            success=True,
            metadata={
                "path": str(target),
                "cell_count": len(built),
                "cell_types": counts,
                "nbformat": "4.5",
            },
        )


__all__ = ["NotebookGeneratorTool"]
