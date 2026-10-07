"""Excel tool — read and write .xlsx workbooks via openpyxl.

Requires the optional ``tools-excel`` extra:

    uv pip install "nova-ai-pro[tools-excel]"

Without it, requests fail loudly with an install hint rather than silently
degrading. Read returns rows as dicts (with a header row) or lists; write
creates a new sheet from rows of lists or dicts and never overwrites an
existing file unless explicitly asked. All cell values in responses are
JSON-safe (dates become ISO strings).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, List

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec


class ExcelLibraryMissing(RuntimeError):
    """Raised when openpyxl is absent for a requested .xlsx operation."""

    def __init__(self) -> None:
        super().__init__(
            "openpyxl is required to read or write .xlsx files with excel_tool. "
            'Install it with: uv pip install "nova-ai-pro[tools-excel]" '
            "(or: uv pip install openpyxl)"
        )


def _import_openpyxl() -> Any:
    """Import openpyxl or raise ExcelLibraryMissing with an install hint."""
    try:
        import openpyxl  # noqa: PLC0415 — optional dependency, loud failure
    except ImportError as exc:
        raise ExcelLibraryMissing() from exc
    return openpyxl


def _json_safe(value: Any) -> Any:
    """Convert a cell value to something json.dumps can serialise."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    return str(value)


def _load_workbook(path: Path, write_mode: bool = False) -> Any:
    openpyxl = _import_openpyxl()
    return openpyxl.load_workbook(
        path,
        read_only=not write_mode,
        data_only=True,
    )


def _pick_sheet(wb: Any, sheet: Any) -> Any:
    """Resolve a sheet by name (str) or 1-based index (int); default first."""
    if sheet is None or sheet == "":
        return wb[wb.sheetnames[0]]
    if isinstance(sheet, bool):
        raise ValueError("sheet must be a sheet name or a 1-based index")
    if isinstance(sheet, int):
        if not 1 <= sheet <= len(wb.sheetnames):
            raise ValueError(
                f"sheet index {sheet} is out of range; "
                f"workbook has {len(wb.sheetnames)} sheets"
            )
        return wb[wb.sheetnames[sheet - 1]]
    if sheet not in wb.sheetnames:
        raise ValueError(
            f"sheet '{sheet}' not found. Available: {', '.join(wb.sheetnames)}"
        )
    return wb[sheet]


def _validate_path(path: str) -> str | None:
    """Return an error message for an invalid .xlsx target path, else None."""
    if not path or not path.strip():
        return "Error: no path provided."
    if not path.lower().endswith(".xlsx"):
        return f"Error: path '{path}' must end with .xlsx (legacy .xls is not supported)."
    return None


def _rows_to_lists(rows: Any) -> tuple[list[list[Any]], str | None]:
    """Normalise rows (lists or dicts) into a list of lists.

    Returns (rows_as_lists, error_message). Dict rows are converted using
    the key order of the first row; a mismatch with a later row's keys is
    reported as an error rather than silently producing empty cells.
    """
    if not isinstance(rows, list) or not rows:
        return [], "Error: rows must be a non-empty list (lists or dicts)."

    converted: list[list[Any]] = []
    keys: list[str] | None = None
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            if keys is None:
                keys = [str(k) for k in row.keys()]
            elif [str(k) for k in row.keys()] != keys:
                return [], (
                    f"Error: row {index} has different keys than row 0. "
                    "Dict rows must share the same keys, or use plain lists."
                )
            converted.append([_json_safe(v) for v in row.values()])
        elif isinstance(row, (list, tuple)):
            converted.append([_json_safe(v) for v in row])
        else:
            converted.append([_json_safe(row)])
    return converted, None


@ToolRegistry.register("excel_tool")
class ExcelTool(BaseTool):
    """Read, inspect, and create .xlsx workbooks."""

    tool_id = "excel_tool"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="excel_tool",
            description=(
                "Read, inspect, or create Excel .xlsx workbooks. Actions: 'read' "
                "returns sheet rows as JSON (dicts when the sheet has a header "
                "row, lists otherwise), 'sheets' lists sheet names with their "
                "dimensions, 'write' creates a new .xlsx from rows (lists or "
                "dicts; dict rows get a header row from their keys). Requires "
                "the openpyxl library; fails with an install hint if missing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "sheets"],
                        "description": (
                            "'read' to extract rows from an existing workbook, "
                            "'sheets' to list sheets and dimensions, 'write' to "
                            "create a new workbook file."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Workbook file path. Must end with .xlsx (legacy "
                            ".xls is not supported). For 'write' the file must "
                            "not exist unless overwrite is true."
                        ),
                    },
                    "sheet": {
                        "type": ["string", "integer"],
                        "description": (
                            "Sheet to operate on: a sheet name ('Data') or a "
                            "1-based index (1 = first sheet). Defaults to the "
                            "first sheet. Only used by 'read'."
                        ),
                    },
                    "header": {
                        "type": "boolean",
                        "description": (
                            "For 'read': treat the first row as column headers "
                            "and return rows as objects keyed by header. "
                            "Defaults to true; set false to get plain row lists."
                        ),
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": (
                            "For 'read': limit how many data rows are returned "
                            "after the header (e.g. 100). Omit for all rows; "
                            "large sheets should use a limit to keep the "
                            "response small."
                        ),
                    },
                    "rows": {
                        "type": "array",
                        "description": (
                            "For 'write': the data to write, one element per "
                            "row. Each row is a list of cell values, or an "
                            "object whose keys become the header row. "
                            "Cell values may be strings, numbers, booleans, or "
                            "null; other types are converted to strings."
                        ),
                        "items": {},
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "For 'write': optional header row written above "
                            "'rows'. Ignored when rows are objects (keys are "
                            "used as headers instead)."
                        ),
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": (
                            "For 'write': name of the sheet to create. "
                            "Defaults to 'Sheet1'."
                        ),
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "For 'write': replace the file if it already "
                            "exists. Defaults to false; without it an existing "
                            "file is never modified."
                        ),
                    },
                },
                "required": ["action", "path"],
            },
            category="productivity",
            timeout_seconds=30.0,
        )

    @track_execution("excel_tool")
    def execute(
        self,
        action: str,
        path: str,
        sheet: Any = None,
        header: bool = True,
        max_rows: int | None = None,
        rows: Any = None,
        headers: List[str] | None = None,
        sheet_name: str = "Sheet1",
        overwrite: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        path_error = _validate_path(path)
        if path_error:
            return ToolResult(
                tool_name="excel_tool", content=path_error, success=False
            )

        try:
            if action == "read":
                return self._read(path, sheet, header, max_rows)
            if action == "sheets":
                return self._sheets(path)
            if action == "write":
                return self._write(
                    path, rows, headers, sheet_name, overwrite
                )
        except ExcelLibraryMissing as exc:
            return ToolResult(
                tool_name="excel_tool",
                content=f"Error: {exc}",
                success=False,
                metadata={"missing_package": "openpyxl"},
            )
        except (ValueError, KeyError) as exc:
            return ToolResult(
                tool_name="excel_tool",
                content=f"Error: {exc}",
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name="excel_tool",
                content=f"Error: could not access workbook — {exc}",
                success=False,
            )
        return ToolResult(
            tool_name="excel_tool",
            content=(
                f"Error: unknown action '{action}'. "
                "Valid actions: read, write, sheets."
            ),
            success=False,
        )

    def _read(
        self,
        path: str,
        sheet: Any,
        header: bool,
        max_rows: int | None,
    ) -> ToolResult:
        target = Path(path)
        if not target.exists():
            return ToolResult(
                tool_name="excel_tool",
                content=f"Error: workbook does not exist: {target.resolve()}",
                success=False,
            )

        wb = _load_workbook(target)
        try:
            ws = _pick_sheet(wb, sheet)
            grid: List[List[Any]] = []
            limit = None if max_rows is None else max(0, int(max_rows))
            for row in ws.iter_rows(values_only=True):
                if limit is not None and len(grid) >= limit + (1 if header else 0):
                    break
                grid.append([_json_safe(v) for v in row])
        finally:
            wb.close()

        if header and grid:
            headers = [f"column_{i + 1}" if h in (None, "") else str(h) for i, h in enumerate(grid[0])]
            data_rows = grid[1:]
            records = [dict(zip(headers, row)) for row in data_rows]
        else:
            records = grid
            headers = None

        return ToolResult(
            tool_name="excel_tool",
            content=(
                f"Read {len(records)} row(s) from "
                f"'{ws.title}' in {target} ({len(grid[0]) if grid else 0} columns)."
            ),
            success=True,
            metadata={
                "path": str(target),
                "sheet": ws.title,
                "row_count": len(records),
                "column_count": len(grid[0]) if grid else 0,
                "headers": headers,
                "rows": records,
            },
        )

    def _sheets(self, path: str) -> ToolResult:
        target = Path(path)
        if not target.exists():
            return ToolResult(
                tool_name="excel_tool",
                content=f"Error: workbook does not exist: {target.resolve()}",
                success=False,
            )

        wb = _load_workbook(target)
        try:
            sheets = [
                {"name": name, "rows": wb[name].max_row, "cols": wb[name].max_column}
                for name in wb.sheetnames
            ]
        finally:
            wb.close()

        listing = ", ".join(f"{s['name']} ({s['rows']}x{s['cols']})" for s in sheets)
        return ToolResult(
            tool_name="excel_tool",
            content=f"{target} contains {len(sheets)} sheet(s): {listing}",
            success=True,
            metadata={"path": str(target), "sheets": sheets},
        )

    def _write(
        self,
        path: str,
        rows: Any,
        headers: List[str] | None,
        sheet_name: str,
        overwrite: bool,
    ) -> ToolResult:
        data, error = _rows_to_lists(rows)
        if error:
            return ToolResult(
                tool_name="excel_tool", content=error, success=False
            )

        if headers is not None:
            if not isinstance(headers, list) or not all(
                isinstance(h, str) for h in headers
            ):
                return ToolResult(
                    tool_name="excel_tool",
                    content="Error: headers must be a list of strings.",
                    success=False,
                )
            data = [list(headers)] + data
        elif rows and all(isinstance(r, dict) for r in rows):
            # _rows_to_lists kept the dict key order; emit the header row.
            data = [list(rows[0].keys())] + data

        target = Path(path)
        if target.exists() and not overwrite:
            return ToolResult(
                tool_name="excel_tool",
                content=(
                    f"Error: workbook already exists at {target}. "
                    "Pass overwrite=true to replace it."
                ),
                success=False,
            )

        openpyxl = _import_openpyxl()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = str(sheet_name or "Sheet1")
        for row in data:
            ws.append(row)
        target.parent.mkdir(parents=True, exist_ok=True)
        wb.save(target)

        return ToolResult(
            tool_name="excel_tool",
            content=(
                f"Created {target}: sheet '{ws.title}' with "
                f"{len(data)} row(s), {len(data[0]) if data else 0} column(s)."
            ),
            success=True,
            metadata={
                "path": str(target),
                "sheet": ws.title,
                "row_count": len(data),
                "column_count": len(data[0]) if data else 0,
            },
        )


__all__ = ["ExcelTool"]
